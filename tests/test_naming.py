"""命名与目录组织测试（图床三级目录 + 去作者标题）。"""
import os
import sys
from pathlib import Path

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from ptf_output.naming import (
    DEFAULT_CATEGORY,
    MANUAL_CATEGORY,
    extract_title,
    guess_category,
    safe_file_name,
    safe_folder_name,
)


# ---- 标题提取 ----

def test_extract_title_author_year():
    assert extract_title(
        "Riedijk和Huijsing - 1991 - An integrated absolute temperature sensor with digital output"
    ) == "An integrated absolute temperature sensor with digital output"


def test_extract_title_author_deng_year():
    assert extract_title(
        "Yoshii 等 - 1997 - 1 chip integrated software calibrated CMOS pressure sensor"
    ) == "1 chip integrated software calibrated CMOS pressure sensor"


def test_extract_title_english_authors():
    assert extract_title(
        "Smith and Jones - 2001 - A study of things"
    ) == "A study of things"


def test_extract_title_year_first():
    assert extract_title("1997 - Some title") == "Some title"


def test_extract_title_no_prefix_unchanged():
    assert extract_title("Some plain title") == "Some plain title"


def test_extract_title_manual_like_kept():
    # LTC2991 不像人名，不应被剥离
    assert extract_title("LTC2991 - Manual") == "LTC2991 - Manual"


# ---- 类别判断 ----

def test_guess_category_default_paper():
    assert guess_category("An integrated temperature sensor") == DEFAULT_CATEGORY


def test_guess_category_manual_by_keyword():
    assert guess_category("LTC2991 datasheet") == MANUAL_CATEGORY
    assert guess_category("用户手册 v2") == MANUAL_CATEGORY
    assert guess_category("Product brief") == MANUAL_CATEGORY


# ---- 文件夹/文件名安全化 ----

def test_safe_folder_name_illegal_chars():
    out = safe_folder_name('A/B: test <ok>?')
    for ch in ':*/"<>|\\?':
        assert ch not in out


def test_safe_folder_name_truncates():
    long = "x" * 100
    assert len(safe_folder_name(long)) <= 64


def test_safe_folder_name_long_gets_hash_suffix():
    base = "A very long paper title that exceeds the folder segment character limit easily"
    a = safe_folder_name(base + " alpha")
    b = safe_folder_name(base + " beta")
    assert a != b
    assert len(a) <= 64
    assert len(b) <= 64


def test_safe_folder_name_empty_falls_back():
    assert safe_folder_name("") == "untitled"
    assert safe_folder_name("   ") == "untitled"


def test_safe_folder_name_no_leading_trailing_separators():
    out = safe_folder_name("  .Title with dots.  ")
    assert not out.startswith(" ")
    assert not out.endswith(".")


def test_safe_file_name():
    assert safe_file_name("An integrated temperature sensor") == "An integrated temperature sensor"
