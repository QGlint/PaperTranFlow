"""图片引用清理。

迁移自 ref/markdownchange/script/clean_images.py（独立重写）：

历史逻辑解决的问题：
    1. MinerU 会输出一些 markdown 未引用的图片文件（无用图片）
    2. markdown 里可能引用不存在的图片（失效引用）

PaperTranFlow 的策略（spec §18，正确性优先）：
    - 从 markdown 提取所有被引用的图片（相对路径 images/*.jpg 等）
    - 只保留被引用的图片，未引用的不落盘（省空间）
    - 不因「看起来像重复」删除正文图片引用，只删除确凿的失效引用
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

# Markdown 图片：![alt](path)
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")
# HTML 图片：<img src="path">
_HTML_IMAGE_RE = re.compile(r"<img[^>]*?\ssrc=[\"\']([^\"\']+)[\"\']", re.IGNORECASE)


def extract_referenced_images(markdown_text: str) -> set[str]:
    """从 markdown 提取所有被引用的图片路径（相对路径，如 images/xxx.jpg）。

    返回相对路径集合（不含协议 URL、data URI）。
    """
    refs: set[str] = set()
    for m in _MD_IMAGE_RE.finditer(markdown_text):
        refs.add(_clean_ref(m.group(1)))
    for m in _HTML_IMAGE_RE.finditer(markdown_text):
        refs.add(_clean_ref(m.group(1)))
    return {r for r in refs if r}


def _clean_ref(url: str) -> str:
    """规范化图片引用：去掉 URL 参数、协议前缀，返回相对路径；非本地路径返回空。"""
    url = url.strip().strip("<>")
    # 跳过协议 URL 和 data URI
    if url.startswith(("http://", "https://", "data:", "//")):
        return ""
    # 去掉可能的 URL 查询/锚点
    url = url.split("?")[0].split("#")[0]
    # 统一分隔符
    url = url.replace("\\", "/")
    # 去掉 ./ 前缀
    while url.startswith("./"):
        url = url[2:]
    return url


def filter_assets_by_reference(
    assets: dict[str, bytes], markdown_text: str
) -> dict[str, bytes]:
    """只保留 markdown 实际引用的图片资产。

    assets 是 MinerU ZIP 里的 {相对路径: bytes}。
    返回被引用的图片子集（保持相对路径结构）。
    """
    referenced = extract_referenced_images(markdown_text)
    if not referenced:
        # 无法解析引用时，保守保留所有 images/* 资产（正确性优先）
        return {k: v for k, v in assets.items() if k.lower().startswith("images/")}

    result: dict[str, bytes] = {}
    for name, data in assets.items():
        norm = name.replace("\\", "/")
        if norm in referenced:
            result[name] = data
        else:
            # 也匹配去掉 images/ 前缀后的文件名（兼容不同引用写法）
            base = norm.split("/")[-1]
            if base in {r.split("/")[-1] for r in referenced}:
                result[name] = data
    return result
