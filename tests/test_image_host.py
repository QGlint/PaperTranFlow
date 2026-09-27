"""图床批次文件夹名约束测试。

图床侧 batchFolder.js 规定：每段上限 64 字符，非法字符 : * ? " < > | \\ / 需清洗。
PaperTranFlow 必须先生成合法文件夹名，否则会被图床以 INVALID_REQUEST 拒绝。
"""
import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from ptf_core.pipeline import FOLDER_SEGMENT_MAX, _safe_folder_name


def test_short_title_kept_readable():
    assert _safe_folder_name("Attention Is All You Need") == "Attention_Is_All_You_Need"


def test_illegal_chars_replaced():
    out = _safe_folder_name('A/B test: with <illegal> chars?')
    for ch in ':*/"<>|\\?':
        assert ch not in out
    assert "A_B_test" in out


def test_long_title_truncated_to_limit():
    long_title = (
        "Riedijk和Huijsing - 1991 - An integrated absolute temperature "
        "sensor with digital output"
    )
    out = _safe_folder_name(long_title)
    assert len(out) <= FOLDER_SEGMENT_MAX


def test_long_title_gets_hash_suffix_for_uniqueness():
    """两篇前 64 字符相同、但后续不同的标题应得到不同文件夹名。"""
    base = "A very long paper title that exceeds the folder segment character limit easily"
    a = _safe_folder_name(base + " alpha")
    b = _safe_folder_name(base + " beta")
    assert a != b
    assert len(a) <= FOLDER_SEGMENT_MAX
    assert len(b) <= FOLDER_SEGMENT_MAX


def test_empty_title_falls_back():
    assert _safe_folder_name("") == "paper"
    assert _safe_folder_name("   ") == "paper"


def test_no_leading_trailing_separators():
    out = _safe_folder_name("  .Title with dots.  ")
    assert not out.startswith("_")
    assert not out.endswith("_")
    assert not out.endswith(".")
