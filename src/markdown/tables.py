"""HTML/CSS 表格 → 原生 Markdown 表格。

迁移自 ref/markdownchange/script/html_table_to_md2.py 的算法（独立重写）：
    用 (r, c) 坐标矩阵展开 rowspan / colspan，避免信息丢失。
    文本处理：get_text(separator=" ") 防粘连、竖线转义、换行转 <br>。

安全兜底：若表格无法安全转换（无 <table>、无 <tr> 等），返回 None，
由调用方决定保留原 HTML（正确性优先，spec §16）。
"""
from __future__ import annotations

from bs4 import BeautifulSoup


def _cell_text(td) -> str:
    text = td.get_text(separator=" ", strip=True)
    text = text.replace("|", "\\|").replace("\n", "<br>")
    return text


def parse_html_table_to_rows(html: str) -> list[list[str]] | None:
    """将 HTML table 展开为二维字符串矩阵（处理 rowspan/colspan）。失败返回 None。"""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return None

    trs = table.find_all("tr")
    if not trs:
        return None

    matrix: dict[tuple[int, int], str] = {}
    max_r = 0
    max_c = 0

    for r_idx, tr in enumerate(trs):
        c_idx = 0
        cells = tr.find_all(["td", "th"])
        if not cells:
            max_r = max(max_r, r_idx + 1)
            continue
        for cell in cells:
            # 跳过被 rowspan 占据的位置
            while (r_idx, c_idx) in matrix:
                c_idx += 1
            try:
                rs = int(cell.get("rowspan", 1) or 1)
                cs = int(cell.get("colspan", 1) or 1)
            except ValueError:
                rs = cs = 1
            rs = max(rs, 1)
            cs = max(cs, 1)
            text = _cell_text(cell)
            for r_off in range(rs):
                for c_off in range(cs):
                    matrix[(r_idx + r_off, c_idx + c_off)] = text
            c_idx += cs
            max_c = max(max_c, c_idx)
        max_r = max(max_r, r_idx + 1)

    rows: list[list[str]] = []
    for r in range(max_r):
        rows.append([matrix.get((r, c), "") for c in range(max_c)])
    return rows


def rows_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    max_cols = max(len(r) for r in rows)
    rows = [r + [""] * (max_cols - len(r)) for r in rows]

    lines = ["| " + " | ".join(rows[0]) + " |"]
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")
    for r in rows[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def convert_html_table(html: str) -> str | None:
    """HTML table → Markdown table；无法安全转换返回 None。"""
    rows = parse_html_table_to_rows(html)
    if not rows:
        return None
    return rows_to_markdown(rows)
