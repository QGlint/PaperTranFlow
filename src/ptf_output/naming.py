"""图床目录命名工具。

用于图片上传时构造图床上的三级目录：
    一级：paper / Manual 等（自动判断，可手动覆盖）
    二级：类别（可选；没有类别时省略这一级）
    三级：文档标题（去掉作者/年份前缀）

示例：
    "Riedijk和Huijsing - 1991 - An integrated absolute temperature sensor.pdf"
        -> 标题 "An integrated absolute temperature sensor"
        -> 图床目录 paper/An integrated absolute temperature sensor/
"""
from __future__ import annotations

import re

# 一级类别：按关键词自动判断（顺序敏感，先匹配更具体的）
_MANUAL_KEYWORDS = (
    "manual", "datasheet", "data sheet", "handbook", "user guide", "userguide",
    "应用笔记", "应用手册", "数据手册", "用户手册", "规格书", "参考手册",
    "specification", "product brief",
)
_PAPER_KEYWORDS = (
    "paper", "article", "journal", "conference", "proceedings", "thesis",
    "dissertation", "论文", "期刊",
)

DEFAULT_CATEGORY = "paper"
MANUAL_CATEGORY = "Manual"


def guess_category(*hints: str) -> str:
    """根据文件名/路径等线索猜测一级类别（paper / Manual）。"""
    text = " ".join(h for h in hints if h).lower()
    for kw in _MANUAL_KEYWORDS:
        if kw in text:
            return MANUAL_CATEGORY
    for kw in _PAPER_KEYWORDS:
        if kw in text:
            return DEFAULT_CATEGORY
    return DEFAULT_CATEGORY


# Zotero / 常见导出命名：「作者 - 年份 - 标题」或「作者 - 标题」或「年份 - 标题」
_YEAR = r"(?:1[89]\d{2}|20\d{2}[a-z]?)"
# 形如 "Author 等 - 1997 - Title" / "Author and Other - 1997 - Title"
_PREFIX_WITH_YEAR = re.compile(
    rf"^\s*(?P<authors>[^-]{{1,120}}?)\s*[-–—]\s*(?P<year>{_YEAR})\s*[-–—]\s*(?P<title>.+)$"
)
# 形如 "Author - Title"（无年份），仅当作者部分明显像人名时才剥离
_PREFIX_NO_YEAR = re.compile(
    r"^\s*(?P<authors>[^-–—]{1,60}?)\s*[-–—]\s*(?P<title>.+)$"
)
# 形如 "1997 - Title"
_YEAR_FIRST = re.compile(rf"^\s*{_YEAR}\s*[-–—]\s*(?P<title>.+)$")

# 作者部分的特征：含「等 / and / & / ,」或多个大写开头单词
_AUTHORISH = re.compile(
    r"(等|和|,|&|\band\b|\bet al\b|^[A-Z][a-zA-Z\.\-]+(\s+[A-Z][a-zA-Z\.\-]+){1,3}$)"
)


def extract_title(stem: str) -> str:
    """从文件名（不含扩展名）提取纯标题，去掉作者/年份前缀。

    兼容：
        "Riedijk和Huijsing - 1991 - An integrated absolute temperature sensor"
            -> "An integrated absolute temperature sensor"
        "Yoshii 等 - 1997 - 1 chip integrated software calibrated CMOS..."
            -> "1 chip integrated software calibrated CMOS..."
        "1997 - Some title"                -> "Some title"
        "Some plain title"                 -> "Some plain title"（不变）
    """
    name = (stem or "").strip()
    if not name:
        return name

    # 1) 「年份 - 标题」
    m = _YEAR_FIRST.match(name)
    if m:
        return m.group("title").strip()

    # 2) 「作者 - 年份 - 标题」
    m = _PREFIX_WITH_YEAR.match(name)
    if m:
        return m.group("title").strip()

    # 3) 「作者 - 标题」（无年份）：仅当作者部分确实像人名时才剥离
    m = _PREFIX_NO_YEAR.match(name)
    if m:
        authors = m.group("authors").strip()
        if _AUTHORISH.search(authors):
            return m.group("title").strip()

    return name


def safe_folder_name(name: str, max_len: int = 64) -> str:
    """把标题转成安全的文件夹名（保留可读性，去掉非法字符）。"""
    import hashlib

    cleaned = re.sub(r'[:*?"<>|\\/]+', "_", name or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._")
    if not cleaned:
        cleaned = "untitled"
    if len(cleaned) > max_len:
        digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
        keep = max_len - len(digest) - 1
        cleaned = f"{cleaned[:keep].rstrip(' ._')}_{digest}"
    return cleaned


def safe_file_name(name: str, max_len: int = 120) -> str:
    """把标题转成安全的文件名（比文件夹名宽松一些，但同样去非法字符）。"""
    cleaned = re.sub(r'[:*?"<>|\\/]+', "_", name or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._")
    if not cleaned:
        cleaned = "untitled"
    return cleaned[:max_len].rstrip(" ._") or "untitled"
