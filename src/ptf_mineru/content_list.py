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

# 阿拉伯数字编号：1. / 1.1 / 1.1.1 / 1) / (1) / (1.1)
# 编号形如 "1"、"3.1"、"3.2.1"。贪婪匹配数字段，之后跟 "." / ")" / 空格。
# "1." 的 "." 是结束符，"3.1" 的 ".1" 是编号一部分（贪婪优先吞掉 .数字）。
_ARABIC = re.compile(r"^\(?(\d+(?:\.\d+)*)(?:[\.\)]\s+|\s+)(?=\S)")
# 罗马数字编号：I. / II. / III. / IV. （大写，用于大章节）
_ROMAN = re.compile(
    r"^\(?(M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3}))[\.\)]\s+"
)
# 字母编号：A. / B. / (A) / (a)（子节）
_ALPHA = re.compile(r"^\(?([A-Za-z])[\.\)]\s+")


def infer_level_from_numbering(title: str) -> int:
    """从标题文本的编号格式推断层级。返回 0 表示无法从编号推断。

    约定：
        阿拉伯数字段数 -> 层级：1 -> 2, 1.1 -> 3, 1.1.1 -> 4
        罗马数字      -> 2（大章节）
        单个字母      -> 3（子节）
    """
    t = title.strip()
    if not t:
        return 0

    # 阿拉伯数字编号（1. / 1.1 / 1.1.1）
    m = _ARABIC.match(t)
    if m:
        segments = m.group(1).count(".") + 1
        # 1 -> level2, 1.1 -> level3, 1.1.1 -> level4
        return segments + 1

    # 罗马数字（I. II. III.）
    if _ROMAN.match(t):
        return 2

    # 字母（A. B.）
    if _ALPHA.match(t):
        return 3

    return 0


def build_heading_levels(items: list[ContentItem]) -> dict[str, int]:
    """根据 content_list 中的标题项，返回 {规范化标题文本: level}。

    优先级：
        1. text_level > 2（MinerU 给出可靠的多级层级时直接采用）
        2. 编号推断（标题带 1. / 1.1 / I. / A. 编号时，从编号推层级）
        3. text_level（1/2 的基础层级）
    """
    mapping: dict[str, int] = {}
    for it in items:
        is_heading = (
            it.type in ("title", "heading", "h1", "h2", "h3", "h4", "h5", "h6")
            or it.text_level > 0
        )
        if not is_heading:
            continue

        text = _norm_title(it.text)
        if not text:
            continue

        level = _resolve_level(it, text)
        if level <= 0:
            continue
        if text not in mapping:
            mapping[text] = min(level, 6)
    return mapping


def _resolve_level(item: ContentItem, text: str) -> int:
    """综合 text_level 与编号推断，得出标题层级。"""
    # MinerU 给出可靠的多级层级（>2）时优先采用
    if item.text_level > 2:
        return item.text_level

    # 编号推断（覆盖 text_level 只有 1/2 的缺陷）
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
