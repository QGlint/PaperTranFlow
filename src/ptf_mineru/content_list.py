"""content_list.json 解析与结构信息提取。

MinerU 的 content_list.json 是结构恢复的重要依据（spec §13）。
本模块把 JSON 解析为轻量 dataclass，暴露 type / text_level / page_idx / bbox 等字段，
并对不同 MinerU 版本的可能字段做容错。

关键：MinerU 的 text_level 常常只给到 2（三级标题丢失）。因此本模块
额外提供「编号推断层级」：从标题文本的编号格式（1. / 1.1 / I. / A.）推断
真实层级，覆盖 MinerU 的 text_level 缺陷。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContentItem:
    type: str = ""
    text_level: int = 0
    page_idx: int = 0
    bbox: list[float] = field(default_factory=list)
    text: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def _as_float_list(v: Any) -> list[float]:
    if not isinstance(v, (list, tuple)):
        return []
    out: list[float] = []
    for x in v:
        try:
            out.append(float(x))
        except (TypeError, ValueError):
            continue
    return out


def parse_content_list(raw_json: str) -> list[ContentItem]:
    """解析 content_list.json 文本为 ContentItem 列表。容错处理空/非法输入。"""
    if not raw_json or not raw_json.strip():
        return []
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return []

    # MinerU 不同版本可能返回 list 或 {"content_list": [...]} 等包装
    items: list[Any]
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("content_list", "contents", "data", "items"):
            v = data.get(key)
            if isinstance(v, list):
                items = v
                break
        else:
            return []
    else:
        return []

    result: list[ContentItem] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        result.append(
            ContentItem(
                type=str(raw.get("type", "")),
                text_level=_int_field(raw, "text_level"),
                page_idx=_int_field(raw, "page_idx"),
                bbox=_as_float_list(raw.get("bbox")),
                text=str(raw.get("text", "")),
                raw=raw,
            )
        )
    return result


def _int_field(raw: dict, key: str) -> int:
    v = raw.get(key, 0)
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


# ---- 编号推断层级 ----
#
# 设计要点（这是「三级标题恢复」的核心）：
#   MinerU 的 text_level 常常只给到 2，三级标题丢失。但标题文本里的编号
#   （1. / 1.1 / 3.2.1 / I. / A.）泄露了真实层级。
#
#   难点：编号的**绝对层级**取决于论文自己的编号约定，不能硬编码：
#     - Hu/Youn 论文：`1. Introduction` 是顶层章节          -> 1. = level 2
#     - Riedijk  论文：顶层章节不编号，`1./2./3.` 是子节    -> 1. = level 3
#   因此先做**文档级**分析，推断出「编号体系起点」anchor，再据此定层级。

# 阿拉伯编号：1. / 3.1 / 3.2.1 / 1) / (1)
#   "1." 的 "." 是结束符；"3.1" 的 ".1" 属于编号本身（贪婪吞掉 .数字），
#   编号后直接跟空格。因此结尾允许是 "." / ")" / 空白。
_TOKEN_ARABIC = re.compile(r"^\(?(\d+(?:\.\d+)*)\)?(?:[\.\)]\s+|\s+)")
# 字母/罗马编号：A. / (A) / I. / II. / III.
_TOKEN_LETTER = re.compile(r"^\(?([A-Za-z]{1,5})\)?[\.\)]\s+")
# 罗马数字字符集
_ROMAN_CHARS = set("IVXLCDM")


def _extract_token(title: str) -> tuple[str, str]:
    """取出标题开头的编号 token，返回 (kind_hint, token)。

    kind_hint: 'arabic' / 'letter' / ''（无编号）
    """
    t = title.strip()
    m = _TOKEN_ARABIC.match(t)
    if m:
        return "arabic", m.group(1)
    m = _TOKEN_LETTER.match(t)
    if m:
        return "letter", m.group(1)
    return "", ""


def _is_multi_roman(token: str) -> bool:
    return len(token) > 1 and all(c in _ROMAN_CHARS for c in token.upper())


def _has_alpha_run(tokens: list[str]) -> bool:
    """是否存在从 A 开始的连续字母递增序列（A,B,C / B,C,D ...）。"""
    singles = [t.upper() for t in tokens if len(t) == 1 and t.isalpha()]
    for i in range(len(singles) - 2):
        a, b, c = singles[i], singles[i + 1], singles[i + 2]
        if ord(b) - ord(a) == 1 and ord(c) - ord(b) == 1:
            return True
    return False


class NumberingStyle:
    """一个文档的编号体系分析结果。"""

    def __init__(self, headings: list[tuple[str, int]]):
        self.anchor = 2
        self._kinds: dict[str, str] = {}
        self._analyse(headings)

    def _analyse(self, headings: list[tuple[str, int]]) -> None:
        kinds: list[tuple[str, str, int]] = []  # (kind_hint, token, text_level)
        for text, lv in headings:
            hint, token = _extract_token(text)
            kinds.append((hint, token, lv))

        has_multi_roman = any(_is_multi_roman(tok) for h, tok, _ in kinds if h == "letter")
        all_tokens = [tok for h, tok, _ in kinds if h == "letter"]
        alpha_run = _has_alpha_run(all_tokens)

        # 逐条判定编号类型
        for (hint, token, lv), (text, _) in zip(kinds, headings):
            if hint == "arabic":
                self._kinds[text] = "arabic"
            elif hint == "letter":
                if _is_multi_roman(token):
                    self._kinds[text] = "roman"
                elif has_multi_roman and alpha_run and not _in_alpha_run(all_tokens, token):
                    # 文档同时有罗马章节 + 字母子节：不在字母序列里的单字符视为罗马
                    self._kinds[text] = "roman" if token.upper() in _ROMAN_CHARS else "alpha"
                else:
                    self._kinds[text] = "alpha"
            else:
                self._kinds[text] = ""

        self.anchor = self._infer_anchor(headings)

    def kind(self, text: str) -> str:
        return self._kinds.get(text, "")

    def _infer_anchor(self, headings: list[tuple[str, int]]) -> int:
        unnumbered = [
            lv for text, lv in headings if self.kind(text) == "" and lv > 0
        ]
        numbered = [text for text, _ in headings if self.kind(text) != ""]
        if not numbered:
            return 2

        if unnumbered:
            base = max(set(unnumbered), key=unnumbered.count)
            first_numbered = next(
                i for i, (text, _) in enumerate(headings) if self.kind(text) != ""
            )
            nested = any(
                self.kind(text) == "" and lv >= base
                for text, lv in headings[:first_numbered]
            )
            return min(base + (1 if nested else 0), 6)

        levels = [lv for _, lv in headings if lv > 0]
        return min(max(set(levels), key=levels.count) if levels else 2, 6)

    def level_for(self, text: str, token_segments: int = 1) -> int:
        """根据编号类型与段数计算层级。返回 0 表示无编号。"""
        kind = self.kind(text)
        if kind == "arabic":
            return self.anchor + (token_segments - 1)
        if kind == "roman":
            return self.anchor
        if kind == "alpha":
            return self.anchor + 1
        return 0


def _in_alpha_run(tokens: list[str], target: str) -> bool:
    singles = [t.upper() for t in tokens if len(t) == 1 and t.isalpha()]
    for i in range(len(singles) - 2):
        a, b, c = singles[i], singles[i + 1], singles[i + 2]
        if ord(b) - ord(a) == 1 and ord(c) - ord(b) == 1:
            if target.upper() in (a, b, c):
                return True
    return False


def infer_level_from_numbering(title: str, anchor: int = 2, style: "NumberingStyle | None" = None) -> int:
    """从标题编号推断层级（独立函数，供测试/单标题场景使用）。

    若提供文档级 style，则使用其编号类型判定与 anchor；否则用简单启发式。
    """
    if style is not None:
        hint, token = _extract_token(title)
        if hint == "arabic":
            return style.anchor + (token.count(".") + 1 - 1)
        return style.level_for(title)

    hint, token = _extract_token(title)
    if hint == "arabic":
        return anchor + (token.count(".") + 1 - 1)
    if hint == "letter":
        if _is_multi_roman(token):
            return anchor
        return anchor + 1
    return 0


def infer_numbering_anchor(headings: list[tuple[str, int]]) -> int:
    """从文档全部标题推断「编号体系起点」层级（对外保留此接口）。"""
    return NumberingStyle(headings).anchor


def build_heading_levels(items: list[ContentItem]) -> dict[str, int]:
    """根据 content_list 中的标题项，返回 {规范化标题文本: level}。

    优先级：
        1. text_level > 2（MinerU 给出可靠的多级层级时直接采用）
        2. 编号推断（用文档级 NumberingStyle，兼容不同编号约定）
        3. text_level（1/2 的基础层级）
    """
    headings: list[tuple[str, int]] = []
    heading_items: list[tuple[ContentItem, str]] = []
    for it in items:
        if not _is_heading(it):
            continue
        text = _norm_title(it.text)
        if not text:
            continue
        headings.append((text, it.text_level))
        heading_items.append((it, text))

    style = NumberingStyle(headings)

    mapping: dict[str, int] = {}
    for it, text in heading_items:
        level = _resolve_level(it, text, style)
        if level <= 0:
            continue
        if text not in mapping:
            mapping[text] = min(level, 6)
    return mapping


def _is_heading(item: ContentItem) -> bool:
    return (
        item.type in ("title", "heading", "h1", "h2", "h3", "h4", "h5", "h6")
        or item.text_level > 0
    )


def _resolve_level(
    item: ContentItem, text: str, style: "NumberingStyle | None" = None
) -> int:
    """综合 text_level 与编号推断，得出标题层级。"""
    hint, token = _extract_token(text)

    # MinerU 给出可靠的多级层级（>2）且该标题无编号时，直接采用
    if item.text_level > 2 and hint == "":
        return item.text_level

    # 编号推断（文档级 anchor / 编号类型）
    if style is not None:
        segments = token.count(".") + 1 if hint == "arabic" else 1
        inferred = style.level_for(text, segments) if hint else 0
        if inferred > 0:
            return inferred
    elif hint:
        inferred = infer_level_from_numbering(text)
        if inferred > 0:
            return inferred

    # 回退：text_level，或从 type 推断
    if item.text_level > 0:
        return item.text_level
    return _level_from_type(item.type)



def _level_from_type(type_: str) -> int:
    t = type_.lower()
    for i in range(1, 7):
        if t == f"h{i}":
            return i
    if t in ("title", "heading"):
        return 1
    return 0


def _norm_title(text: str) -> str:
    t = (text or "").strip()
    while t.endswith("."):
        t = t[:-1].rstrip()
    return t
