"""content_list.json 解析与结构信息提取。

MinerU 的 content_list.json 是结构恢复的重要依据（spec §13）。
本模块把 JSON 解析为轻量 dataclass，暴露 type / text_level / page_idx / bbox 等字段，
并对不同 MinerU 版本的可能字段做容错。
"""
from __future__ import annotations

import json
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


def build_heading_levels(items: list[ContentItem]) -> dict[str, int]:
    """根据 content_list 中的标题项，返回 {规范化标题文本: level}。

    用于结构恢复：text_level=1 -> '#', 2 -> '##', ...
    标题文本做轻度规范化（去首尾空白、去结尾点号）以便与 Markdown 标题匹配。
    """
    mapping: dict[str, int] = {}
    for it in items:
        if it.type not in ("title", "heading", "h1", "h2", "h3", "h4", "h5", "h6"):
            continue
        level = it.text_level
        if level <= 0:
            # 回退：从 type 推断（如 "h3"）
            level = _level_from_type(it.type)
        if level <= 0:
            continue
        text = _norm_title(it.text)
        if not text:
            continue
        # 优先保留首个出现的
        if text not in mapping:
            mapping[text] = min(level, 6)
    return mapping


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
