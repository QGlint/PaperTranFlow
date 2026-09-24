"""Markdown 标准化（MarkdownNormalizer）。

目标：MinerU Markdown -> 稳定、统一、可预测的 Markdown。

重点：
    - HTML 表格 -> 原生 Markdown 表格（无法安全转换则保留原结构）
    - 公式保护（$ / $$ 不动）
    - 图片引用保护
    - 代码块保护
    - 列表/引用保持完整
"""
from __future__ import annotations

from markdown.models import MarkdownBlock, MarkdownDocument
from markdown.tables import convert_html_table


class MarkdownNormalizer:
    def __init__(self):
        pass

    def normalize(self, document: MarkdownDocument) -> MarkdownDocument:
        for block in document.blocks:
            block.normalized_text = block.source_text

        self._convert_html_tables(document)
        return document

    def _convert_html_tables(self, document: MarkdownDocument) -> None:
        for block in document.blocks:
            if block.type != "table":
                continue
            if block.metadata.get("kind") != "html":
                continue
            html = block.normalized_text or block.source_text
            converted = convert_html_table(html)
            if converted is not None:
                block.normalized_text = converted
                block.metadata["kind"] = "md"
                block.metadata["converted"] = True
            # 无法安全转换：保留原 HTML（normalized_text 已等于 source_text）
