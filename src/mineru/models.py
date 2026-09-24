"""MinerU 数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MinerUResult:
    """MinerU 完成后的原始产物。"""

    markdown: str = ""
    content_list_json: str = ""
    # ZIP 内其它文件（图片等）按 name -> bytes 保留，供后续复用
    assets: dict[str, bytes] = field(default_factory=dict)

    @property
    def has_content_list(self) -> bool:
        return bool(self.content_list_json.strip())
