"""GLM 后端（GLM-4.7-Flash）。

OpenAI 兼容 /chat/completions。清理 <think>...</think> 前缀（GLM 强思考模型）。
"""
from __future__ import annotations

import re
import time

import httpx

from pf_config.models import GLMConfig
from pf_translation.backend import TranslationBackend
from pf_translation.retry import RETRYABLE_GLM_CODES, RetryPolicy

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
                if resp.status_code >= 400:
                    last_status = resp.status_code
                    raise GLMHTTPError(resp.status_code, resp.text)
                result = resp.json()
                # 业务错误（GLM 在 HTTP 200 中也可能返回 {"error": {...}}）
                err = result.get("error")
                if err:
                    code = _error_code(err)
                    last_status = code
                    raise GLMHTTPError(code, str(err))
                content = self._extract_content(result)
                return self._sanitize(content)
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
                # 负载过高（1305）用更长退避
                if last_status in RETRYABLE_GLM_CODES:
                    time.sleep(self.retry_policy.overload_delay(attempt))
                else:
                    self.retry_policy.sleep(attempt)

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


def _error_code(err: object) -> int:
    """从 GLM 业务错误中提取错误码（如 1305）。返回整数或 -1。"""
    if isinstance(err, dict):
        v = err.get("code")
        try:
            return int(v)
        except (TypeError, ValueError):
            return -1
    return -1
