"""编号标题层级推断测试（spec §13 / markdownchange mark_c.py 迁移）。

核心：MinerU 的 text_level 常只到 2（三级标题丢失），
需要从标题编号推断真实层级；而编号的绝对层级取决于论文自己的约定，
因此必须做文档级分析（NumberingStyle）。
"""
import json
import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from ptf_mineru.content_list import (
    NumberingStyle,
    build_heading_levels,
    infer_level_from_numbering,
    infer_numbering_anchor,
    parse_content_list,
)
from ptf_markdown.normalize import MarkdownNormalizer
from ptf_markdown.parser import parse_markdown
from ptf_markdown.structure import StructureRestorer


def _levels(headings: list[tuple[str, int]]) -> dict[str, int]:
    items = parse_content_list(
        json.dumps([{"type": "text", "text": t, "text_level": lv} for t, lv in headings])
    )
    return build_heading_levels(items)


# ---- 1. 阿拉伯编号（顶层章节编号）: Hu 风格 ----

def test_arabic_top_level_numbering():
    levels = _levels([
        ("Title", 1),
        ("1. Introduction", 2),
        ("2. Operating principle", 2),
        ("3. Proposed structure", 2),
        ("3.1 Temperature sensing", 2),
        ("3.2 SAR ADC", 2),
        ("3.2.1 Hybrid DAC", 2),
        ("3.2.2 MOM capacitor", 2),
        ("4. Measurement results", 2),
        ("5. Conclusion", 2),
    ])
    assert levels["1. Introduction"] == 2
    assert levels["3. Proposed structure"] == 2
    assert levels["3.1 Temperature sensing"] == 3
    assert levels["3.2 SAR ADC"] == 3
    assert levels["3.2.1 Hybrid DAC"] == 4
    assert levels["3.2.2 MOM capacitor"] == 4
    assert levels["4. Measurement results"] == 2


# ---- 2. 阿拉伯编号（仅子节编号）: Riedijk 风格 ----

def test_arabic_nested_under_unnumbered_chapters():
    """顶层章节无编号，1./2./3. 是子节 -> anchor 应为 3。"""
    headings = [
        ("Abstract", 2),
        ("Introduction", 2),
        ("Temperature sensor", 2),
        ("Restraints in signal conversion", 2),
        ("1. Limited chip area", 2),
        ("2. Poor accuracy of components", 2),
        ("3. Digital interference", 2),
        ("Suitable A-to-D converters", 2),
        ("Measurement results", 2),
        ("References", 2),
    ]
    assert infer_numbering_anchor(headings) == 3
    levels = _levels(headings)
    assert levels["Restraints in signal conversion"] == 2
    assert levels["1. Limited chip area"] == 3
    assert levels["2. Poor accuracy of components"] == 3
    assert levels["3. Digital interference"] == 3
    assert levels["Suitable A-to-D converters"] == 2


# ---- 3. 罗马数字章节 + 字母子节: Youn 风格 ----

def test_roman_chapters_with_alpha_subsections():
    headings = [
        ("Title", 1),
        ("I. INTRODUCTION", 2),
        ("II. CDC PERFORMANCE METRICS", 2),
        ("III. RECENT WORKS ADDRESSING THE TRADEOFFS", 2),
        ("A. SAR CDCS", 2),
        ("B. DSM CDCS", 2),
        ("C. PM CDCS", 2),
        ("D. HYBRID ARCHITECTURES", 2),
        ("IV. DISCUSSION", 2),
        ("A. COMPARISON OF CDC PERFORMANCE METRICS", 2),
        ("B. SYSTEM-LEVEL PERFORMANCE", 2),
        ("V. CONCLUSION", 2),
        ("REFERENCES", 2),
    ]
    levels = _levels(headings)
    # 罗马数字 -> 章节 level 2
    assert levels["I. INTRODUCTION"] == 2
    assert levels["II. CDC PERFORMANCE METRICS"] == 2
    assert levels["III. RECENT WORKS ADDRESSING THE TRADEOFFS"] == 2
    assert levels["IV. DISCUSSION"] == 2
    assert levels["V. CONCLUSION"] == 2
    # 字母 -> 子节 level 3（含形似罗马数字的 C./D.）
    assert levels["A. SAR CDCS"] == 3
    assert levels["B. DSM CDCS"] == 3
    assert levels["C. PM CDCS"] == 3
    assert levels["D. HYBRID ARCHITECTURES"] == 3
    assert levels["A. COMPARISON OF CDC PERFORMANCE METRICS"] == 3
    assert levels["B. SYSTEM-LEVEL PERFORMANCE"] == 3


# ---- 4. 无编号 ----

def test_no_numbering_returns_zero():
    assert infer_level_from_numbering("CALIBRATION METHOD") == 0
    assert infer_level_from_numbering("Introduction") == 0


def test_unnumbered_document_keeps_text_levels():
    levels = _levels([
        ("SUMMARY", 2),
        ("INTRODUCTION", 2),
        ("CALIBRATION METHOD", 2),
    ])
    assert levels["SUMMARY"] == 2
    assert levels["INTRODUCTION"] == 2
    assert levels["CALIBRATION METHOD"] == 2


# ---- 5. MinerU 给出可靠 >2 层级时优先采用 ----

def test_trust_mineru_deep_levels_when_no_numbering():
    levels = _levels([
        ("Chapter", 1),
        ("Section", 2),
        ("Subsection", 3),
        ("Subsubsection", 4),
    ])
    assert levels["Chapter"] == 1
    assert levels["Section"] == 2
    assert levels["Subsection"] == 3
    assert levels["Subsubsection"] == 4


# ---- 6. 集成：restore + normalize 不丢层级（回归 bug） ----

def test_restore_applies_numbering_level():
    cl = json.dumps([
        {"type": "text", "text": "Abstract", "text_level": 2},
        {"type": "text", "text": "1. Limited chip area", "text_level": 2},
    ])
    doc = parse_markdown("## Abstract\n\nbody\n\n## 1. Limited chip area\n\ntext\n")
    StructureRestorer(cl).restore(doc)
    assert doc.blocks[0].metadata["level"] == 2
    assert doc.blocks[2].metadata["level"] == 3
    assert doc.blocks[2].normalized_text.startswith("### ")


def test_normalize_preserves_restored_level():
    """normalize 不得覆盖 restore 已设置的层级（历史 bug）。"""
    cl = json.dumps([
        {"type": "text", "text": "1. Introduction", "text_level": 2},
        {"type": "text", "text": "3. Proposed structure", "text_level": 2},
        {"type": "text", "text": "3.1 Temperature sensing", "text_level": 2},
    ])
    doc = parse_markdown(
        "## 1. Introduction\n\nbody\n\n## 3. Proposed structure\n\nx\n\n"
        "## 3.1 Temperature sensing\n\ntext\n"
    )
    StructureRestorer(cl).restore(doc)
    MarkdownNormalizer().normalize(doc)
    # 3.1 应为 ### (level 3)，且 normalize 后不被重置
    assert doc.blocks[4].metadata["level"] == 3
    assert doc.blocks[4].normalized_text.startswith("### ")


# ---- 7. NumberingStyle 直接接口 ----

def test_numbering_style_exposes_anchor_and_kinds():
    style = NumberingStyle([
        ("I. INTRODUCTION", 2),
        ("II. METRICS", 2),
        ("A. SAR CDCS", 2),
        ("B. DSM CDCS", 2),
        ("C. PM CDCS", 2),
    ])
    assert style.kind("I. INTRODUCTION") == "roman"
    assert style.kind("A. SAR CDCS") == "alpha"
    assert style.kind("C. PM CDCS") == "alpha"
    assert style.anchor == 2
