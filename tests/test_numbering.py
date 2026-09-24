"""编号标题层级推断测试（spec §13 / markdownchange mark_c.py 迁移）。"""
import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from ptf_mineru.content_list import infer_level_from_numbering, build_heading_levels, parse_content_list
from ptf_markdown.structure import StructureRestorer
from ptf_markdown.parser import parse_markdown


def test_arabic_numbering_levels():
    assert infer_level_from_numbering("1. Introduction") == 2
    assert infer_level_from_numbering("2. Operating principle") == 2
    assert infer_level_from_numbering("3.1 Temperature sensing") == 3
    assert infer_level_from_numbering("3.2 SAR ADC") == 3
    assert infer_level_from_numbering("3.2.1 Hybrid DAC") == 4
    assert infer_level_from_numbering("3.2.2 MOM capacitor") == 4


def test_roman_and_alpha_numbering():
    assert infer_level_from_numbering("I. INTRODUCTION") == 2
    assert infer_level_from_numbering("II. CDC PERFORMANCE METRICS") == 2
    assert infer_level_from_numbering("A. SAR CDCS") == 3
    assert infer_level_from_numbering("B. DSM CDCS") == 3


def test_no_numbering_returns_zero():
    assert infer_level_from_numbering("CALIBRATION METHOD") == 0
    assert infer_level_from_numbering("Introduction") == 0


def test_build_heading_levels_with_numbering():
    """MinerU 把 3.1/3.2.1 都标 text_level=2 时，编号推断应恢复真实层级。"""
    cl = [
        {"type": "text", "text": "1. Introduction", "text_level": 2},
        {"type": "text", "text": "3. Proposed structure", "text_level": 2},
        {"type": "text", "text": "3.1 Temperature sensing", "text_level": 2},
        {"type": "text", "text": "3.2 SAR ADC", "text_level": 2},
        {"type": "text", "text": "3.2.1 Hybrid DAC", "text_level": 2},
    ]
    import json

    items = parse_content_list(json.dumps(cl))
    mapping = build_heading_levels(items)
    assert mapping["1. Introduction"] == 2
    assert mapping["3. Proposed structure"] == 2
    assert mapping["3.1 Temperature sensing"] == 3
    assert mapping["3.2 SAR ADC"] == 3
    assert mapping["3.2.1 Hybrid DAC"] == 4


def test_restore_applies_numbering_level():
    """restore 应把 markdown 里的 3.1 标题重写为 ###。"""
    import json

    cl = json.dumps([
        {"type": "text", "text": "3.1 Temperature sensing", "text_level": 2},
    ])
    doc = parse_markdown("## 3.1 Temperature sensing\n\nbody\n")
    StructureRestorer(cl).restore(doc)
    heading = doc.blocks[0]
    assert heading.metadata["level"] == 3
    assert heading.normalized_text.startswith("### ")


def test_normalize_preserves_restored_level():
    """normalize 不应覆盖 restore 已设置的标题层级（回归 bug 修复）。"""
    import json

    from ptf_markdown.normalize import MarkdownNormalizer

    cl = json.dumps([
        {"type": "text", "text": "3.1 Temperature sensing", "text_level": 2},
    ])
    doc = parse_markdown("## 3.1 Temperature sensing\n\nbody\n")
    StructureRestorer(cl).restore(doc)
    # 关键：normalize 之后，restore 设置的 ### 应保留
    MarkdownNormalizer().normalize(doc)
    heading = doc.blocks[0]
    assert heading.metadata["level"] == 3
    assert heading.normalized_text.startswith("### ")
