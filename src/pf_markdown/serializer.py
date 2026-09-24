"""MarkdownBlock 列表 → Markdown 文本序列化器。

翻译完成后，把 block 的 normalized_text（译文）按顺序拼回，
块之间用空行分隔；代码/公式/图片等原样保留。
"""
from __future__ import annotations

from .models import MarkdownDocument


class MarkdownSerializer:
    def __init__(self, block_separator: str = "\n\n"):
        self.block_separator = block_separator

    def serialize(self, document: MarkdownDocument) -> str:
        parts: list[str] = []
        for block in document.blocks:
            text = block.normalized_text or block.source_text
            if text:
                parts.append(text.rstrip("\n"))
        text = self.block_separator.join(parts)
        if text and not text.endswith("\n"):
            text += "\n"
        return text


def serialize_markdown(document: MarkdownDocument) -> str:
    return MarkdownSerializer().serialize(document)
