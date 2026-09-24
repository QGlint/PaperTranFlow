"""结构恢复：结合 content_list.json 恢复 heading 层级。

依据（spec §13）：
    - content_list.json 提供 text_level / type 等结构信息
    - text_level=1 -> '#', 2 -> '##', ...
    - Markdown 本身用于文本内容、顺序、现有格式

实现：
    1. 解析 content_list 得到 {规范化标题文本: level}
    2. 对 Markdown 中的 heading block，若其标题文本能匹配到 level，
       则把标题重写为对应层级；否则保留原层级。
"""
from __future__ import annotations

from pf_markdown.models import MarkdownBlock, MarkdownDocument
from pf_mineru.content_list import build_heading_levels, parse_content_list


def _norm_title(text: str) -> str:
    t = (text or "").strip()
    while t.endswith("."):
        t = t[:-1].rstrip()
    return t


class StructureRestorer:
    def __init__(self, content_list_json: str = ""):
        items = parse_content_list(content_list_json)
        self._level_map = build_heading_levels(items)

    def restore(self, document: MarkdownDocument) -> MarkdownDocument:
        if not self._level_map:
            return document
        for block in document.blocks:
            if block.type != "heading":
                continue
            level = block.metadata.get("level", 0)
            title = block.metadata.get("title", "")
            mapped = self._level_map.get(_norm_title(title))
            if mapped and mapped != level:
                new_line = f"{'#' * mapped} {title}"
                block.normalized_text = new_line
                block.metadata["level"] = mapped
                block.metadata["restored"] = True
        return document

    def heading_level(self, title: str, default: int = 1) -> int:
        return self._level_map.get(_norm_title(title), default)
