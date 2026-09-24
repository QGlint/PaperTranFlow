"""markdownchange 历史问题回归测试（spec §38）。

基于 ref/markdownchange 中已解决的实际问题建立 regression case，
验证重写后的 PaperFlow 模块通过。
"""
import os
import sys
from pathlib import Path

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

FIXTURES = Path(__file__).parent / "fixtures"

from pf_markdown.parser import parse_markdown
from pf_markdown.structure import StructureRestorer
from pf_markdown.tables import convert_html_table
from pf_markdown.cleanup import MarkdownCleaner


def test_case_001_html_table_rowspan_colspan():
    """markdownchange-case-001: HTML table 含 rowspan/colspan 正确展开。"""
    html = (FIXTURES / "markdownchange-case-001.html").read_text(encoding="utf-8")
    md = convert_html_table(html)
    assert md is not None
    # 表头
    assert "SYMBOL" in md
    assert "PARAMETER" in md
    # rowspan 展开：INL 出现在两行
    assert "INL" in md
    # 单元格内公式保留（$V_{CC}$ 不被破坏）
    assert "V_{CC}" in md


def test_case_002_heading_restore_from_content_list():
    """markdownchange-case-002: 依据 content_list.json 恢复 heading 层级。"""
    md_text = (FIXTURES / "markdownchange-case-002.md").read_text(encoding="utf-8")
    cl = (FIXTURES / "markdownchange-case-002.content_list.json").read_text(encoding="utf-8")

    doc = parse_markdown(md_text)
    restorer = StructureRestorer(cl)
    restorer.restore(doc)

    levels = {
        b.metadata.get("title", ""): b.metadata.get("level", 0)
        for b in doc.blocks
        if b.type == "heading"
    }
    # SYSTEM CONFIGURATION 应为 level 3（content_list 中 text_level=3）
    assert levels.get("SYSTEM CONFIGURATION") == 3
    # SUMMARY 应为 level 2
    assert levels.get("SUMMARY") == 2


def test_case_003_image_cleanup_dedup():
    """markdownchange-case-003: 重复图片引用去重。"""
    from pf_markdown.models import MarkdownBlock, MarkdownDocument

    doc = MarkdownDocument(blocks=[
        MarkdownBlock("b1", "image", "![](images/a.jpg)"),
        MarkdownBlock("b2", "image", "![](images/a.jpg)"),  # 重复
        MarkdownBlock("b3", "paragraph", "text"),
        MarkdownBlock("b4", "image", "![](images/b.jpg)"),
    ])
    MarkdownCleaner().clean(doc)
    # 相邻重复图片只保留一个
    assert len(doc.blocks) == 3
    assert doc.blocks[0].type == "image"
    assert doc.blocks[1].type == "paragraph"
