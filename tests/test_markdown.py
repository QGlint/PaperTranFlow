"""Markdown 解析、表格转换、结构恢复、chunking 测试。"""
import os
import sys
from pathlib import Path

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from ptf_config.models import ChunkingConfig
from ptf_markdown.models import MarkdownDocument
from ptf_markdown.parser import parse_markdown
from ptf_markdown.structure import StructureRestorer
from ptf_markdown.tables import convert_html_table
from ptf_markdown.serializer import serialize_markdown
from ptf_mineru.content_list import build_heading_levels, parse_content_list
from ptf_translation.chunker import SmartChunker


# ---- parser ----

def test_parse_heading_and_paragraph():
    doc = parse_markdown("# Title\n\nSome paragraph text.\n")
    types = [b.type for b in doc.blocks]
    assert types == ["heading", "paragraph"]
    assert doc.blocks[0].metadata["level"] == 1


def test_parse_code_fence_is_atomic():
    doc = parse_markdown("```python\nprint(1)\nprint(2)\n```\n")
    assert doc.blocks[0].type == "code"
    assert "print(1)" in doc.blocks[0].source_text
    assert "print(2)" in doc.blocks[0].source_text


def test_parse_display_math_is_atomic():
    doc = parse_markdown("$$\nx^2 + y^2 = z^2\n$$\n")
    assert doc.blocks[0].type == "math"


def test_parse_list_is_one_block():
    doc = parse_markdown("- a\n- b\n- c\n")
    assert doc.blocks[0].type == "list"
    assert "b" in doc.blocks[0].source_text


# ---- tables ----

def test_html_table_rowspan_colspan():
    html = (
        '<table><tr><td>SYMBOL</td><td>PARAM</td><td colspan="2">COND</td></tr>'
        '<tr><td colspan="2">General</td><td>X</td><td>Y</td></tr>'
        '<tr><td rowspan="2">INL</td><td>a</td><td>1</td><td>2</td></tr>'
        '<tr><td>b</td><td>3</td><td>4</td></tr></table>'
    )
    md = convert_html_table(html)
    assert md is not None
    assert "SYMBOL" in md
    assert "PARAM" in md
    assert "INL" in md


def test_html_table_invalid_returns_none():
    assert convert_html_table("no table here") is None


# ---- structure ----

def test_heading_restore_from_content_list():
    cl = [
        {"type": "title", "text_level": 1, "text": "Introduction"},
        {"type": "title", "text_level": 2, "text": "Background"},
    ]
    import json

    doc = parse_markdown("# Introduction\n\n# Background\n")
    restorer = StructureRestorer(json.dumps(cl))
    restorer.restore(doc)
    levels = [b.metadata["level"] for b in doc.blocks if b.type == "heading"]
    assert levels == [1, 2]


def test_build_heading_levels():
    items = parse_content_list('[{"type":"title","text_level":3,"text":"Deep"}]')
    mapping = build_heading_levels(items)
    assert mapping == {"Deep": 3}


# ---- chunking ----

def test_chunker_skips_non_translatable_blocks():
    """不可翻译 block（code/math/image）不进入 chunk，不发送给 LLM。"""
    cfg = ChunkingConfig(target=5000, hard_limit=6500)
    doc = MarkdownDocument(blocks=[
        _block("b1", "heading", "# H"),
        _block("b2", "code", "```\n" + "x" * 10000 + "\n```"),
        _block("b3", "paragraph", "short"),
    ])
    chunker = SmartChunker(cfg)
    result = chunker.chunk(doc)
    # code block 不进入任何 chunk
    all_block_ids = [bid for c in result.chunks for bid in c.block_ids]
    assert "b2" not in all_block_ids
    # heading 和 paragraph 各成一个 chunk
    assert "b1" in all_block_ids
    assert "b3" in all_block_ids


def test_chunker_one_chunk_per_translatable_block():
    """每个可翻译 block 对应一个 chunk（1:1 block 对应）。"""
    cfg = ChunkingConfig(target=5000, hard_limit=6500)
    doc = MarkdownDocument(blocks=[
        _block("b1", "heading", "# H"),
        _block("b2", "paragraph", "hello"),
        _block("b3", "math", "$$\nx\n$$"),
    ])
    result = SmartChunker(cfg).chunk(doc)
    # 只有 b1、b2 是可翻译的，各一个 chunk
    assert len(result.chunks) == 2
    ids = [c.block_ids[0] for c in result.chunks]
    assert ids == ["b1", "b2"]


def _block(bid, btype, text):
    from ptf_markdown.models import MarkdownBlock

    return MarkdownBlock(block_id=bid, type=btype, source_text=text, normalized_text=text)


# ---- serializer ----

def test_serializer_roundtrip():
    doc = parse_markdown("# H\n\npara\n")
    out = serialize_markdown(doc)
    assert "# H" in out
    assert "para" in out
