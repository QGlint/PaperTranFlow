"""MinerU 云 API 客户端。

流程（参考 DocuTranslate 的 converter_mineru.py，独立重新实现）：
    submit  -> POST /file-urls/batch 得到 batch_id + 上传 URL
    upload  -> PUT 上传 PDF 到返回 URL
    poll    -> GET /extract-results/batch/{batch_id} 轮询 state
    download-> GET full_zip_url 下载 ZIP
    extract -> 解出 full.md + content_list.json (+ 其它资产)

API 地址与认证全部来自 ConfigLoader，不硬编码。
"""
from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import httpx

from config.models import MinerUConfig
from mineru.models import MinerUResult

_MD_FILENAMES = ("full.md", "result.md", "auto.md", "output.md")


class MinerUError(RuntimeError):
    pass


class MinerUClient:
    def __init__(self, config: MinerUConfig):
        self.config = config

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.token}",
        }

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=httpx.Timeout(
                connect=self.config.connect_timeout,
                read=self.config.read_timeout,
                write=self.config.write_timeout,
                pool=10.0,
            ),
            verify=False,
            trust_env=False,
        )

    # ---- 单步 API ----

    def submit(self, filename: str) -> tuple[str, str]:
        """申请上传 URL，返回 (batch_id, upload_url)。"""
        payload = {
            "enable_formula": self.config.enable_formula,
            "language": self.config.language,
            "enable_table": True,
            "model_version": self.config.model_version,
            "files": [{"name": filename, "is_ocr": True}],
        }
        url = f"{self.config.base_url}/file-urls/batch"
        with self._client() as client:
            resp = client.post(url, headers=self._headers(), json=payload)
            resp.raise_for_status()
            result = resp.json()
        if result.get("code") != 0:
            raise MinerUError(f"申请上传 URL 失败: {result}")
        data = result.get("data") or {}
        batch_id = data.get("batch_id")
        file_urls = data.get("file_urls") or []
        if not batch_id or not file_urls:
            raise MinerUError(f"申请上传 URL 返回异常: {result}")
        return batch_id, file_urls[0]

    def upload(self, upload_url: str, content: bytes) -> None:
        with self._client() as client:
            resp = client.put(upload_url, content=content)
            resp.raise_for_status()

    def poll(self, batch_id: str) -> str:
        """轮询直到 done，返回 full_zip_url。"""
        url = f"{self.config.base_url}/extract-results/batch/{batch_id}"
        deadline = time.time() + self.config.poll_timeout
        while True:
            with self._client() as client:
                resp = client.get(url, headers=self._headers())
                resp.raise_for_status()
                result = resp.json()
            data = result.get("data") or {}
            extract_result = data.get("extract_result") or []
            if not extract_result:
                raise MinerUError(f"轮询返回缺少 extract_result: {result}")
            fileinfo = extract_result[0]
            state = fileinfo.get("state")
            if state == "done":
                file_url = fileinfo.get("full_zip_url")
                if not file_url:
                    raise MinerUError("MinerU 完成但缺少 full_zip_url")
                return file_url
            if state == "failed":
                msg = fileinfo.get("err_msg") or fileinfo.get("message") or "Unknown error"
                raise MinerUError(f"MinerU 处理失败: {msg}")
            if time.time() > deadline:
                raise MinerUError("MinerU 轮询超时")
            time.sleep(self.config.poll_interval)

    def download(self, zip_url: str) -> bytes:
        with self._client() as client:
            resp = client.get(zip_url)
            resp.raise_for_status()
            return resp.content

    def extract(self, zip_bytes: bytes) -> MinerUResult:
        """从 ZIP 解出 markdown + content_list.json + 其它资产。"""
        result = MinerUResult()
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                names = zf.namelist()
                md_name = self._find_markdown(names)
                if md_name:
                    result.markdown = zf.read(md_name).decode("utf-8", errors="ignore")

                cl_name = self._find_content_list(names)
                if cl_name:
                    result.content_list_json = zf.read(cl_name).decode(
                        "utf-8", errors="ignore"
                    )

                for name in names:
                    if name == md_name or name == cl_name:
                        continue
                    if name.endswith("/"):
                        continue
                    try:
                        result.assets[name] = zf.read(name)
                    except KeyError:
                        continue
        except zipfile.BadZipFile as e:
            raise MinerUError(f"下载的结果不是有效 ZIP: {e}") from e

        if not result.markdown:
            raise MinerUError("ZIP 中未找到 Markdown 文件")
        return result

    # ---- 组合入口 ----

    def parse(self, pdf_path: Path) -> MinerUResult:
        """完整流程：submit -> upload -> poll -> download -> extract。"""
        content = pdf_path.read_bytes()
        batch_id, upload_url = self.submit(pdf_path.name)
        self.upload(upload_url, content)
        zip_url = self.poll(batch_id)
        zip_bytes = self.download(zip_url)
        return self.extract(zip_bytes)

    # ---- 内部 ----

    @staticmethod
    def _find_markdown(names: list[str]) -> str | None:
        for name in names:
            lower = name.lower()
            if lower in _MD_FILENAMES or lower.endswith((".md", ".markdown")):
                return name
        return None

    @staticmethod
    def _find_content_list(names: list[str]) -> str | None:
        for name in names:
            if name.lower().endswith("content_list.json"):
                return name
        return None
