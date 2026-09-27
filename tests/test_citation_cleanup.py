"""引用编号被误判为公式的还原测试（MinerU `$[2]$` 问题）。

MinerU 常把方括号引用写成 `$[3–8]$`，导致引用按数学公式渲染且可能被 LLM 误改。
PaperFlow 的 cleanup 需还原为纯文本 `[3–8]`，同时不破坏真公式。
"""
import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from ptf_markdown.cleanup import MarkdownCleaner, normalize_citation_math
from ptf_markdown.models import MarkdownBlock, MarkdownDocument


def test_single_citation_in_math():
    assert normalize_citation_math("results $[6]$ show") == "results [6] show"


def test_range_citation_in_math():
    assert normalize_citation_math("shown $[3–8]$ here") == "shown [3–8] here"
    assert normalize_citation_math("shown $[3-8]$ here") == "shown [3-8] here"


def test_multi_citation_in_math():
    assert normalize_citation_math("$[4, 17, 18]$") == "[4, 17, 18]"
    assert normalize_citation_math("$[12, 13]$") == "[12, 13]"


def test_superscript_citation_in_math():
    # $^{[2]}$ -> ^[2]（保留上标语义，去掉 $ 包裹）
    assert normalize_citation_math("$^{[2]}$") == "^[2]"


def test_real_formula_not_touched():
    cases = [
        "$\\pm 1.5^{\\circ}\\mathrm{C}$",
        "$V_{CC}$",
        "$0.074\\mathrm{mm}^2$",
        "$182\\mu \\mathrm{W}$",
        "$[1, 2]$ is a citation but $x^2 + y^2$ is math",
    ]
    # 前 4 个完全不应变化
    for c in cases[:4]:
        assert normalize_citation_math(c) == c, c
    # 最后一个：引用被还原，真公式保留
    out = normalize_citation_math(cases[4])
    assert "[1, 2]" in out
    assert "$x^2 + y^2$" in out


def test_no_dollar_returns_unchanged():
    s = "plain text [3] without math"
    assert normalize_citation_math(s) == s


def test_cleaner_applies_citation_fix_to_paragraph():
    doc = MarkdownDocument(blocks=[
        MarkdownBlock("b1", "paragraph", "As shown $[3–8]$ and $[12, 13]$."),
    ])
    MarkdownCleaner().clean(doc)
    out = doc.blocks[0].normalized_text
    assert "$[" not in out
    assert "[3–8]" in out
    assert "[12, 13]" in out


def test_cleaner_does_not_touch_math_block():
    doc = MarkdownDocument(blocks=[
        MarkdownBlock("b1", "math", "$$\n[3-8]\n$$"),
    ])
    MarkdownCleaner().clean(doc)
    # math block 内容原样保留
    assert doc.blocks[0].normalized_text == "$$\n[3-8]\n$$"
