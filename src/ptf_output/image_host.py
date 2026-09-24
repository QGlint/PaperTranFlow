"""cf 图床图片上传（默认关闭）。

迁移自 ref/markdownchange/script/batch_upload_and_rewrite.py 的上传逻辑（独立重写）：

上传协议（与历史 batchimage 一致）：
    POST {base_url}/upload
    表单：multipart form-data，字段名 "file"
    认证：Authorization: Bearer {token}
    返回：[{"src": "..."}]，取 src 作为远程 URL

流程：
    1. 上传 out_dir/images/ 下的本地图片到图床
    2. 把 markdown 里的本地引用 images/xxx.jpg 重写为远程 URL
    3. 重写后的 markdown 写回（或写到新文件）

注意：默认关闭，需显式开启。图床 API 尚未测试（图床服务待完善）。
"""
from __future__ import annotations

import json
import mimetypes
import time
import uuid
from pathlib import Path

import httpx


class ImageHostError(RuntimeError):
    pass


class ImageHostUploader:
    """把本地图片上传到 cf 图床，返回 {本地相对路径: 远程 URL}。"""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _endpoint(self) -> str:
        return f"{self.base_url}/upload"

    def _headers(self, boundary: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }

    def upload_one(self, file_path: Path) -> str:
        """上传单个图片，返回远程 URL。"""
        if not file_path.is_file():
            raise ImageHostError(f"图片不存在: {file_path}")

        data = file_path.read_bytes()
        mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        boundary = f"----PaperTranFlow{time.time_ns()}"

        # 构造 multipart body
        header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8")
        tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
        body = header + data + tail

        try:
            with httpx.Client(timeout=180, trust_env=False) as client:
                resp = client.post(self._endpoint(), headers=self._headers(boundary), content=body)
            resp.raise_for_status()
            result = resp.json()
        except httpx.HTTPError as e:
            raise ImageHostError(f"图床上传失败: {e}") from e
        except json.JSONDecodeError as e:
            raise ImageHostError(f"图床返回非 JSON: {e}") from e

        src = self._extract_src(result)
        if src.startswith(("http://", "https://")):
            return src
        return f"{self.base_url}{src}"

    @staticmethod
    def _extract_src(result) -> str:
        if isinstance(result, list) and result:
            item = result[0]
            if isinstance(item, dict) and item.get("src"):
                return item["src"]
        if isinstance(result, dict) and result.get("src"):
            return result["src"]
        raise ImageHostError(f"图床返回缺少 src: {result}")


def rewrite_markdown_images(markdown_text: str, image_map: dict[str, str]) -> str:
    """把 markdown 里的本地图片引用重写为远程 URL。

    image_map: {本地相对路径（如 images/xxx.jpg）: 远程 URL}
    """
    import re

    def repl(m: re.Match) -> str:
        alt = m.group(1)
        ref = m.group(2).strip().strip("<>")
        # 只替换 image_map 里的本地路径
        for local, remote in image_map.items():
            if ref == local or ref.endswith(local) or local.endswith(ref):
                return f"![{alt}]({remote})"
        return m.group(0)

    pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    return pattern.sub(repl, markdown_text)
