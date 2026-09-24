"""Markdown 清理（cleanup）。

迁移自 ref/markdownchange 的历史逻辑（独立重写）：
    - 重复/相邻相同 block 去重
    - 标题/加粗文本的尾随空格清理
    - 明显异常字符（不破坏公式/代码）
    - 重复图片引用

原则：不因「看起来像重复」直接删正文（spec §18），只清理高置信度的
明显重复（相邻、内容完全相同且类型相同的 block）。
"""
from __future__ import annotations

import re

from .models import MarkdownBlock, MarkdownDocument

# 标题或加粗文本尾随的空白
_TRAILING_WS_IN_HEADING = re.compile(r"(\s+)\*{0,2}\s*$")


def cleanup_block(block: MarkdownBlock) -> MarkdownBlock:
    """单 block 清理：返回规范化后的 block（原地修改 normalized_text）。"""
    text = block.normalized_text or block.source_text
    if block.type == "heading":
        # 去掉标题尾部空白；保持 '#' 前缀
        stripped = text.rstrip()
        if stripped != text:
            block.normalized_text = stripped
    elif block.type == "paragraph":
        # 合并段落内部多余空白（保留单空格），但不触碰 $...$ 公式/代码
        cleaned = _clean_paragraph_ws(text)
        block.normalized_text = cleaned
    else:
        block.normalized_text = text
    return block


def _clean_paragraph_ws(text: str) -> str:
    # 不处理包含 $$ 或 ``` 的文本（交给 math/code 类型）
    if "$$" in text or "```" in text:
        return text
    # 把连续空白折叠为单空格，但保留换行结构
    lines = text.split("\n")
    out = []
    for ln in lines:
        # 行内多个空格 → 单空格
        ln = re.sub(r"[ \t]{2,}", " ", ln).rstrip()
        out.append(ln)
    return "\n".join(out)


def dedupe_adjacent(document: MarkdownDocument) -> MarkdownDocument:
    """去除相邻、类型与内容完全相同的重复 block（高置信度去重）。"""
    result: list[MarkdownBlock] = []
    for block in document.blocks:
        text = block.normalized_text or block.source_text
        key = (block.type, text.strip())
        if result:
            prev = result[-1]
            prev_text = (prev.normalized_text or prev.source_text).strip()
            prev_key = (prev.type, prev_text)
            # 跳过完全相同的相邻 block（尤其 image / math / raw 的 OCR 重复）
            if key == prev_key:
                continue
        result.append(block)
    document.blocks = result
    return document


def dedupe_images(document: MarkdownDocument) -> MarkdownDocument:
    """去除重复的图片引用 block（相同 URL 的相邻图片只保留一个）。"""
    result: list[MarkdownBlock] = []
    last_image_src: str | None = None
    for block in document.blocks:
        if block.type == "image":
            src = _extract_image_src(block.normalized_text or block.source_text)
            if src and src == last_image_src:
                continue
            last_image_src = src
        else:
            last_image_src = None
        result.append(block)
    document.blocks = result
    return document


def _extract_image_src(text: str) -> str | None:
    m = re.search(r"!\[[^\]]*\]\(([^)\s]+)", text)
    return m.group(1) if m else None


class MarkdownCleaner:
    def clean(self, document: MarkdownDocument) -> MarkdownDocument:
        for block in document.blocks:
            cleanup_block(block)
        dedupe_adjacent(document)
        dedupe_images(document)
        return document
