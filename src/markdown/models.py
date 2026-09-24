"""Markdown Block Model。

定义 MarkdownDocument / MarkdownBlock，每个 block 至少具有：
    block_id / type / source_text / normalized_text / metadata
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal

BlockType = Literal[
    "heading",
    "paragraph",
    "list",
    "table",
    "blockquote",
    "code",
    "math",
    "image",
    "thematic_break",
    "raw",
]

# 不可翻译（序列化时原样保留）的 block 类型
NON_TRANSLATABLE = {"code", "math", "image", "thematic_break"}


@dataclass
class MarkdownBlock:
    block_id: str
    type: BlockType
    source_text: str
    normalized_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_translatable(self) -> bool:
        return self.type not in NON_TRANSLATABLE

    def content_hash(self) -> str:
        text = self.normalized_text or self.source_text
        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


@dataclass
class MarkdownDocument:
    blocks: list[MarkdownBlock] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __iter__(self):
        return iter(self.blocks)

    def __len__(self) -> int:
        return len(self.blocks)

    @property
    def block_count(self) -> int:
        return len(self.blocks)
