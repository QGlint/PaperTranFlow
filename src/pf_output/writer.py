"""输出写入。

把翻译后的 block 序列化，写 input.zh.md。保证与 input.md 的
block 数量/顺序/结构严格对应（代码/公式/图片原样保留）。
"""
from __future__ import annotations

from pathlib import Path

from pf_markdown.models import MarkdownDocument
from pf_markdown.serializer import serialize_markdown


class OutputWriter:
    def __init__(self, zh_suffix: str = ".zh.md"):
        self.zh_suffix = zh_suffix

    def zh_path(self, source_path: Path) -> Path:
        return source_path.with_suffix(self.zh_suffix)

    def write(self, document: MarkdownDocument, source_path: Path) -> Path:
        text = serialize_markdown(document)
        out_path = self.zh_path(source_path)
        out_path.write_text(text, encoding="utf-8")
        return out_path
