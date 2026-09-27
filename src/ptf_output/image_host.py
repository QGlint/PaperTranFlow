"""cf 图床图片上传（默认关闭）。

对接 CloudFlare-ImgBed 的批量上传接口：
    POST {base_url}/upload/huggingface/batchCommit
    Authorization: Bearer {token}
    Content-Type: application/json
    Body: {"folderName": "...", "commitMessage": "...", "requestId": "...",
           "files": [{"name": "...", "contentBase64": "data:image/png;base64,...",
                      "mimeType": "image/png", "sha256": "..."}]}

一次调用上传多张图并指定 folderName（图床据此建文件夹，GUI 目录树清晰）。

响应：
    {"success": true, "folder": "...", "files": [{"name","src","fullId"}, ...]}
    files[] 顺序与请求一致，可按下标对应回本地文件名。

错误码：
    400 INVALID_REQUEST / CHANNEL_NOT_FOUND  -> 不重试
    401 AUTH_ERROR                            -> 不重试
    429 RATE_LIMIT                            -> 按 retryAfterSeconds 重试
    502 PARTIAL_UPLOAD_NOT_COMMITTED          -> 同一 requestId 重试安全
    500 INTERNAL_ERROR                        -> 可重试

映射与重写：
    图片本地引用为 images/xxx.jpg；本地文件名为 MinerU 生成的哈希名，天然防冲突。
    上传后把 markdown 里的 images/xxx.jpg 重写为远程 URL。
"""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import time
from pathlib import Path

import httpx

# 图床默认限额（服务端同样有校验）
MAX_FILES_PER_BATCH = 50
MAX_TOTAL_BYTES = 80 * 1024 * 1024
MAX_SINGLE_BYTES = 20 * 1024 * 1024

_RETRYABLE_CODES = {"RATE_LIMIT", "INTERNAL_ERROR", "PARTIAL_UPLOAD_NOT_COMMITTED"}


class ImageHostError(RuntimeError):
    """图床上传失败。code 为服务端错误码（若可解析）。"""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


class ImageHostUploader:
    """批量上传图片到 cf 图床。"""

    def __init__(self, base_url: str, token: str, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _endpoint(self) -> str:
        return f"{self.base_url}/upload/huggingface/batchCommit"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    # ---- 主入口 ----

    def upload_batch(
        self,
        files: list[Path],
        folder_name: str,
        commit_message: str | None = None,
        request_id: str | None = None,
        max_retries: int = 3,
    ) -> dict[str, str]:
        """批量上传并返回 {本地文件名: 远程 URL}。

        files 会被自动分片（服务端单批上限 50 张 / 80MB）。
        """
        if not files:
            return {}

        result: dict[str, str] = {}
        for group_index, group in enumerate(self._split_batches(files)):
            payload_files = [self._prepare(f) for f in group]
            rid = f"{request_id}-{group_index}" if request_id else None
            resp = self._post_with_retry(
                folder_name=folder_name,
                files=payload_files,
                commit_message=commit_message,
                request_id=rid,
                max_retries=max_retries,
            )
            returned = resp.get("files") or []
            # 响应 files[] 顺序与请求一致
            for local, remote_item in zip(group, returned):
                src = str(remote_item.get("src", ""))
                result[local.name] = self._absolute_url(src)
        return result

    # ---- 内部分片 ----

    @staticmethod
    def _split_batches(files: list[Path]) -> list[list[Path]]:
        batches: list[list[Path]] = []
        current: list[Path] = []
        current_bytes = 0
        for f in files:
            try:
                size = f.stat().st_size
            except OSError:
                size = 0
            too_many = len(current) >= MAX_FILES_PER_BATCH
            too_big = current and (current_bytes + size) > MAX_TOTAL_BYTES
            if current and (too_many or too_big):
                batches.append(current)
                current = []
                current_bytes = 0
            current.append(f)
            current_bytes += size
        if current:
            batches.append(current)
        return batches

    # ---- 单个文件 → 请求体 ----

    def _prepare(self, file_path: Path) -> dict:
        data = file_path.read_bytes()
        if len(data) > MAX_SINGLE_BYTES:
            raise ImageHostError(
                f"图片超过单文件上限（{MAX_SINGLE_BYTES} 字节）: {file_path.name}"
            )
        mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        b64 = base64.b64encode(data).decode("ascii")
        return {
            "name": file_path.name,
            "contentBase64": f"data:{mime};base64,{b64}",
            "mimeType": mime,
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    # ---- HTTP + 重试 ----

    def _post_with_retry(
        self,
        folder_name: str,
        files: list[dict],
        commit_message: str | None,
        request_id: str | None,
        max_retries: int,
    ) -> dict:
        payload: dict = {
            "folderName": folder_name,
            "files": files,
        }
        if commit_message:
            payload["commitMessage"] = commit_message
        if request_id:
            payload["requestId"] = request_id

        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                result = self._post_once(payload)
                return result
            except _RetryableImageHostError as e:
                last_error = e
                if attempt >= max_retries:
                    break
                delay = e.retry_after if e.retry_after else 2.0 * (2 ** attempt)
                time.sleep(min(delay, 60.0))
            except ImageHostError:
                raise

        raise ImageHostError(
            f"图床上传失败（已重试 {max_retries} 次）: {last_error}",
            code=getattr(last_error, "code", None),
        )

    def _post_once(self, payload: dict) -> dict:
        try:
            with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                resp = client.post(self._endpoint(), headers=self._headers(), json=payload)
        except httpx.HTTPError as e:
            # 网络错误可重试
            raise _RetryableImageHostError(f"网络错误: {e}", retry_after=None) from e

        body: dict | None = None
        try:
            body = resp.json()
        except (json.JSONDecodeError, ValueError):
            body = None

        if resp.status_code == 200:
            if isinstance(body, dict) and body.get("success"):
                return body
            # 200 但 success=false：按业务错误处理
            code = (body or {}).get("code") if isinstance(body, dict) else None
            raise ImageHostError(
                f"图床返回失败: {(body or {}).get('error') if isinstance(body, dict) else resp.text[:200]}",
                code=code,
            )

        code = (body or {}).get("code") if isinstance(body, dict) else None
        error_msg = (body or {}).get("error") if isinstance(body, dict) else resp.text[:200]

        # 429 / 5xx / 可重试业务码
        if resp.status_code == 429 or resp.status_code >= 500 or code in _RETRYABLE_CODES:
            retry_after = None
            if isinstance(body, dict):
                ra = body.get("retryAfterSeconds")
                if isinstance(ra, (int, float)) and ra > 0:
                    retry_after = float(ra)
            raise _RetryableImageHostError(
                f"HTTP {resp.status_code} {code or ''}: {error_msg}",
                retry_after=retry_after,
                code=code,
            )

        # 400 / 401 等不可重试
        raise ImageHostError(
            f"图床拒绝上传（HTTP {resp.status_code}, code={code}）: {error_msg}",
            code=code,
        )

    def _absolute_url(self, src: str) -> str:
        if src.startswith(("http://", "https://")):
            return src
        if not src:
            return src
        return f"{self.base_url}{src}"


class _RetryableImageHostError(ImageHostError):
    def __init__(self, message: str, retry_after: float | None, code: str | None = None):
        super().__init__(message, code=code)
        self.retry_after = retry_after


def rewrite_markdown_images(markdown_text: str, image_map: dict[str, str]) -> str:
    """把 markdown 里的本地图片引用重写为远程 URL。

    image_map: {本地文件名或相对路径（如 images/xxx.jpg）: 远程 URL}
    """
    if not image_map:
        return markdown_text

    # 建立「文件名 → 远程 URL」索引，兼容 images/xxx.jpg 与 xxx.jpg 两种写法
    by_name: dict[str, str] = {}
    for local, remote in image_map.items():
        by_name[local] = remote
        by_name[Path(local).name] = remote

    def repl(m: re.Match) -> str:
        alt = m.group(1)
        ref = m.group(2).strip().strip("<>")
        if ref.startswith(("http://", "https://", "data:")):
            return m.group(0)
        url = by_name.get(ref) or by_name.get(Path(ref).name)
        if url:
            return f"![{alt}]({url})"
        return m.group(0)

    pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    return pattern.sub(repl, markdown_text)
