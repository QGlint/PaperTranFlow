"""Markdown → MarkdownBlock 列表解析器。

把 Markdown 文本转换为结构化 block。支持的 block 类型：
heading / paragraph / list / table / blockquote / code / math / image /
thematic_break / raw

解析策略：行扫描 + 状态机。代码围栏、$$ 公式块、HTML <table>、列表、
引用块作为整体 block，不按行拆散，以保证后续 chunking 不在其内部切割。
"""
from __future__ import annotations

import re

from .models import MarkdownBlock, MarkdownDocument

_FENCE_RE = re.compile(r"^\s*(```+|~~~+)\s*(\S*)\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_THEMATIC_RE = re.compile(r"^\s*(\*{3,}|-{3,}|_{3,})\s*$")
_LIST_ITEM_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+")
_QUOTE_RE = re.compile(r"^\s*>\s?")
_HTML_TABLE_START = re.compile(r"^\s*<table\b", re.IGNORECASE)
_HTML_TABLE_END = re.compile(r"</table\s*>\s*$", re.IGNORECASE)
_IMAGE_RE = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$")
_DISPLAY_MATH_OPEN = re.compile(r"^\s*\$\$\s*$")
_DISPLAY_MATH_INLINE = re.compile(r"^\s*\$\$.*\$\$\s*$")
_BLANK_RE = re.compile(r"^\s*$")


class MarkdownParser:
    def __init__(self):
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"block-{self._counter:06d}"

    def parse(self, text: str) -> MarkdownDocument:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")
        blocks: list[MarkdownBlock] = []
        n = len(lines)
        i = 0

        while i < n:
            line = lines[i]

            # 空行
            if _BLANK_RE.match(line):
                i += 1
                continue

            # 代码围栏
            m = _FENCE_RE.match(line)
            if m:
                fence = m.group(1)
                info = m.group(2)
                block, i = self._consume_code_fence(lines, i, fence, info)
                blocks.append(block)
                continue

            # 显示公式块
            if _DISPLAY_MATH_OPEN.match(line):
                block, i = self._consume_display_math(lines, i)
                blocks.append(block)
                continue
            if _DISPLAY_MATH_INLINE.match(line):
                blocks.append(
                    MarkdownBlock(self._next_id(), "math", line, normalized_text=line)
                )
                i += 1
                continue

            # HTML 表格（整体，可能跨多行）
            if _HTML_TABLE_START.match(line):
                block, i = self._consume_html_table(lines, i)
                blocks.append(block)
                continue

            # 标题
            m = _HEADING_RE.match(line)
            if m:
                level = len(m.group(1))
                title = m.group(2).strip()
                blocks.append(
                    MarkdownBlock(
                        self._next_id(),
                        "heading",
                        line,
                        metadata={"level": level, "title": title},
                    )
                )
                i += 1
                continue

            # 主题分割线
            if _THEMATIC_RE.match(line):
                blocks.append(
                    MarkdownBlock(self._next_id(), "thematic_break", line, normalized_text=line)
                )
                i += 1
                continue

            # 图片（单独成行的图片）
            if _IMAGE_RE.match(line):
                blocks.append(
                    MarkdownBlock(self._next_id(), "image", line, normalized_text=line)
                )
                i += 1
                continue

            # 列表项（收集相邻列表项为一个 list block）
            if _LIST_ITEM_RE.match(line):
                block, i = self._consume_list(lines, i)
                blocks.append(block)
                continue

            # 引用块（收集相邻引用行为一个 blockquote block）
            if _QUOTE_RE.match(line):
                block, i = self._consume_blockquote(lines, i)
                blocks.append(block)
                continue

            # 原生 Markdown 表格（| 开头且下一行是分隔行）
            if line.lstrip().startswith("|") and self._is_md_table(lines, i):
                block, i = self._consume_md_table(lines, i)
                blocks.append(block)
                continue

            # 其余：段落（收集连续非空非特殊行）
            block, i = self._consume_paragraph(lines, i)
            blocks.append(block)
            continue

        return MarkdownDocument(blocks=blocks)

    # ---- 消费辅助 ----

    def _consume_code_fence(self, lines, i, fence, info):
        start = i
        collected = [lines[i]]
        i += 1
        while i < len(lines):
            collected.append(lines[i])
            if lines[i].strip().startswith(fence) and lines[i].strip() == fence:
                i += 1
                break
            i += 1
        raw = "\n".join(collected)
        block = MarkdownBlock(
            self._next_id(),
            "code",
            raw,
            normalized_text=raw,
            metadata={"lang": info},
        )
        return block, i

    def _consume_display_math(self, lines, i):
        start = i
        collected = [lines[i]]
        i += 1
        while i < len(lines):
            collected.append(lines[i])
            if _DISPLAY_MATH_OPEN.match(lines[i]):
                i += 1
                break
            i += 1
        raw = "\n".join(collected)
        block = MarkdownBlock(self._next_id(), "math", raw, normalized_text=raw)
        return block, i

    def _consume_html_table(self, lines, i):
        collected = [lines[i]]
        i += 1
        while i < len(lines):
            collected.append(lines[i])
            if _HTML_TABLE_END.search(lines[i]):
                i += 1
                break
            i += 1
        raw = "\n".join(collected)
        block = MarkdownBlock(self._next_id(), "table", raw, metadata={"kind": "html"})
        return block, i

    def _consume_list(self, lines, i):
        collected = [lines[i]]
        i += 1
        while i < len(lines):
            line = lines[i]
            if _BLANK_RE.match(line):
                break
            if _LIST_ITEM_RE.match(line):
                collected.append(line)
                i += 1
                continue
            # 列表项的续行（缩进内容）
            if line.startswith((" ", "\t")) and not _BLANK_RE.match(line):
                collected.append(line)
                i += 1
                continue
            break
        raw = "\n".join(collected)
        return MarkdownBlock(self._next_id(), "list", raw), i

    def _consume_blockquote(self, lines, i):
        collected = [lines[i]]
        i += 1
        while i < len(lines):
            line = lines[i]
            if _QUOTE_RE.match(line) or (
                line.startswith(">") or (_BLANK_RE.match(line) and i + 1 < len(lines) and _QUOTE_RE.match(lines[i + 1]))
            ):
                collected.append(line)
                i += 1
                continue
            break
        raw = "\n".join(collected)
        return MarkdownBlock(self._next_id(), "blockquote", raw), i

    def _is_md_table(self, lines, i):
        if i + 1 >= len(lines):
            return False
        nxt = lines[i + 1].strip()
        return bool(re.match(r"^\|?[\s:|-]+\|?\s*$", nxt)) and "|" in nxt

    def _consume_md_table(self, lines, i):
        collected = [lines[i]]
        i += 1
        # 分隔行
        if i < len(lines):
            collected.append(lines[i])
            i += 1
        while i < len(lines):
            line = lines[i]
            if line.lstrip().startswith("|"):
                collected.append(line)
                i += 1
                continue
            break
        raw = "\n".join(collected)
        return MarkdownBlock(self._next_id(), "table", raw, metadata={"kind": "md"}), i

    def _consume_paragraph(self, lines, i):
        collected = [lines[i]]
        i += 1
        while i < len(lines):
            line = lines[i]
            if _BLANK_RE.match(line):
                break
            # 遇到任何新的特殊行，段落结束
            if (
                _FENCE_RE.match(line)
                or _DISPLAY_MATH_OPEN.match(line)
                or _HEADING_RE.match(line)
                or _THEMATIC_RE.match(line)
                or _HTML_TABLE_START.match(line)
                or _LIST_ITEM_RE.match(line)
                or _QUOTE_RE.match(line)
            ):
                break
            collected.append(line)
            i += 1
        raw = "\n".join(collected)
        return MarkdownBlock(self._next_id(), "paragraph", raw), i


def parse_markdown(text: str) -> MarkdownDocument:
    return MarkdownParser().parse(text)
