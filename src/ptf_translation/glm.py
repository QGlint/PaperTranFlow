"""GLM 后端（GLM-4.7-Flash）。

OpenAI 兼容 /chat/completions。清理 <think>...</think> 前缀（GLM 强思考模型）。
"""
from __future__ import annotations

import re
import time

import httpx

from ptf_config.models import GLMConfig
from ptf_translation.backend import TranslationBackend
from ptf_translation.retry import RETRYABLE_GLM_CODES, RetryPolicy

# 伪状态码：表示「模型返回了空内容」。用于触发重试，
# 并在多次重试仍为空时由上层保留原文。
GLM_EMPTY_RESPONSE = 1300

_SYSTEM_PROMPT = """# 角色
你是一名专业的机器翻译引擎。

# 任务
将输入的 Markdown 文本准确翻译为 {target_lang}。

# 要求
- 只输出译文，不要添加解释、注释，不要用代码块包裹结果。
- 准确翻译，不总结、不扩写、不删除信息。
- 保持原始语义，保持术语一致。
- 不翻译数学公式（$...$、$$...$$ 内的 LaTeX 原样保留）。
- 不修改代码（``` 代码块原样保留）。
- 不改变结构、格式、顺序。
- 保留图片引用 ![...](...) 原样。
"""

_THINK_RE = re.compile(r"^\s*<think>.*?</think>", re.DOTALL)


class GLMBackend(TranslationBackend):
    def __init__(self, config: GLMConfig, retry_policy: RetryPolicy | None = None):
        self.config = config
        self.retry_policy = retry_policy or RetryPolicy()

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=httpx.Timeout(
                connect=self.config.connect_timeout,
                read=self.config.read_timeout,
                write=self.config.write_timeout,
                pool=10.0,
            ),
            trust_env=False,
        )

    def _url(self) -> str:
        base = self.config.base_url.rstrip("/")
        return f"{base}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }

    def _payload(self, text: str, target_lang: str) -> dict:
        system = _SYSTEM_PROMPT.format(target_lang=target_lang)
        return {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
        }

    def translate(self, text: str, target_lang: str = "简体中文") -> str:
        if not text.strip():
            return text
        payload = self._payload(text, target_lang)
        last_error: BaseException | None = None
        last_status: int | None = None

        for attempt in range(self.retry_policy.max_retries + 1):
            try:
                with self._client() as client:
                    resp = client.post(self._url(), headers=self._headers(), json=payload)
                # 优先解析 body 中的业务错误码（如 1302/1305），
                # 否则 429 会被当成通用状态码，丢失「限流」语义。
                body = _parse_json(resp)
                if resp.status_code >= 400:
                    code = _business_code(body) or resp.status_code
                    last_status = code
                    raise GLMHTTPError(code, _error_text(body, resp))
                # 业务错误（HTTP 200 也可能返回 {"error": {...}}）
                err = body.get("error") if isinstance(body, dict) else None
                if err:
                    code = _error_code(err)
                    last_status = code
                    raise GLMHTTPError(code, str(err))
                content = self._extract_content(body)
                text = self._sanitize(content)
                # GLM 偶尔对短输入（如单行标题）返回空内容。
                # 这不是有效译文，应重试而不是接受（否则会产出空标题）。
                if text.strip():
                    return text
                last_status = GLM_EMPTY_RESPONSE
                last_error = GLMHTTPError(
                    GLM_EMPTY_RESPONSE, "GLM 返回空内容"
                )
            except GLMHTTPError as e:
                last_error = e
                last_status = e.status_code
                if not self.retry_policy.is_retryable(e.status_code):
                    raise
            except (httpx.RequestError, httpx.TimeoutException, KeyError, IndexError, ValueError) as e:
                last_error = e
                if not self.retry_policy.is_retryable(None, error=e):
                    raise
            if attempt < self.retry_policy.max_retries:
                # 限流类错误（1302/1305）用更长退避；其它用普通退避
                self.retry_policy.sleep(attempt, last_status)

        # 全部重试后仍为空：返回空串交由上层保留原文（不阻断整个任务）
        if last_status == GLM_EMPTY_RESPONSE:
            return ""
        raise GLMHTTPError(
            last_status,
            f"翻译失败，已重试 {self.retry_policy.max_retries} 次: {_safe_err(last_error)}",
        )

    @staticmethod
    def _extract_content(result: dict) -> str:
        choices = result.get("choices") or []
        if not choices:
            raise ValueError("GLM 响应缺少 choices")
        message = choices[0].get("message") or {}
        content = message.get("content", "")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(item.get("text", item.get("content", "")))
            content = "".join(parts)
        return content

    @staticmethod
    def _sanitize(text: str) -> str:
        return _THINK_RE.sub("", text).strip()


class GLMHTTPError(RuntimeError):
    def __init__(self, status_code: int | None, message: str):
        super().__init__(message)
        self.status_code = status_code


def _safe_err(error: BaseException | None) -> str:
    if error is None:
        return "unknown"
    text = str(error)
    return text[:200]


def _parse_json(resp) -> object:
    """尽量解析响应 JSON；失败返回 None（不抛异常）。"""
    try:
        return resp.json()
    except Exception:
        return None


def _business_code(body: object) -> int | None:
    """从响应体提取业务错误码（如 1302/1305）；无则返回 None。

    这样即使 HTTP 状态是 429，也能拿到精确的业务码，
    从而应用对应的退避策略（1305 比 1302 更长）。
    """
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            code = _error_code(err)
            if code > 0:
                return code
        # 有些形态把 code 放在顶层
        for key in ("code", "msgCode"):
            v = body.get(key)
            try:
                iv = int(v)
                if iv > 0:
                    return iv
            except (TypeError, ValueError):
                pass
    return None


def _error_text(body: object, resp) -> str:
    """构造错误描述文本。"""
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if body.get("message"):
            return str(body["message"])
    return (resp.text or "")[:200]


def _error_code(err: object) -> int:
    """从 GLM 业务错误中提取错误码（如 1305）。返回整数或 -1。"""
    if isinstance(err, dict):
        v = err.get("code")
        try:
            return int(v)
        except (TypeError, ValueError):
            return -1
    return -1
