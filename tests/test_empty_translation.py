"""空译文防御测试。

背景：GLM 偶尔对短输入（如单行标题 `## Abstract`）返回空内容。
若不防御，会产出空的 `##` 标题并丢失内容（真实发生的 bug）。
"""
import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from ptf_core.models import Chunk
from ptf_core.pipeline import Pipeline, _has_translatable_content, _reassert_heading_level
from ptf_markdown.models import MarkdownBlock, MarkdownDocument


def test_has_translatable_content():
    assert _has_translatable_content("摘要") is True
    assert _has_translatable_content("## 摘要") is True
    assert _has_translatable_content("") is False
    assert _has_translatable_content("   ") is False
    assert _has_translatable_content("##") is False          # 只剩 # 前缀
    assert _has_translatable_content("## ") is False
    assert _has_translatable_content("#\n#") is False


def test_reassert_heading_level_normal():
    assert _reassert_heading_level("## 摘要", 2) == "## 摘要"
    assert _reassert_heading_level("摘要", 3) == "### 摘要"
    assert _reassert_heading_level("##### 摘要", 2) == "## 摘要"


def test_empty_translation_keeps_original():
    """空译文不得覆盖原文（否则出现空标题/丢内容）。"""
    doc = MarkdownDocument(blocks=[
        MarkdownBlock("b1", "heading", "## Abstract", metadata={"level": 2}),
        MarkdownBlock("b2", "paragraph", "Some body text."),
    ])
    chunks = [Chunk("c1", ["b1"], "## Abstract"), Chunk("c2", ["b2"], "Some body text.")]
    # GLM 对标题返回空、对正文返回正常译文
    translations = {"c1": "", "c2": "一些正文。"}
    Pipeline._apply_translations(doc, chunks, translations)

    # 标题保留原文（不产生空的 ##）
    assert doc.blocks[0].normalized_text in ("", "## Abstract")
    assert doc.blocks[0].normalized_text != "##"
    # 正文正常翻译
    assert doc.blocks[1].normalized_text == "一些正文。"


def test_heading_only_hash_not_applied():
    """译文只剩 '#' 时也不应写入。"""
    doc = MarkdownDocument(blocks=[
        MarkdownBlock("b1", "heading", "## Introduction", metadata={"level": 2}),
    ])
    Pipeline._apply_translations(
        doc, [Chunk("c1", ["b1"], "## Introduction")], {"c1": "##"}
    )
    assert doc.blocks[0].normalized_text != "##"


def test_whitespace_translation_keeps_original():
    doc = MarkdownDocument(blocks=[
        MarkdownBlock("b1", "paragraph", "Original text."),
    ])
    Pipeline._apply_translations(
        doc, [Chunk("c1", ["b1"], "Original text.")], {"c1": "   \n  "}
    )
    # 未设置 normalized_text（保留源文本，序列化时回退）
    assert doc.blocks[0].normalized_text == ""
