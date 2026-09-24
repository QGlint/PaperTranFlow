# markdownchange 分析

> 阶段：Phase 1
> `ref/markdownchange/` 是过去针对 MinerU/Markdown 实际问题编写的一组定制化 Python 脚本。
> 定位：历史参考，不作为 PaperFlow runtime dependency。

## 1. 脚本清单与用途

| 文件 | 用途 | 输入 | 输出 | 是否值得迁移 |
|------|------|------|------|--------------|
| `html_table_to_md.py` | HTML `<table>` → Markdown（rowspan 复制填充） | 含 `<table>` 的 .md | 替换后的 .md | ✅ 迁移算法 |
| `html_table_to_md2.py` | HTML `<table>` → Markdown（**rowspan+colspan** 坐标矩阵展开，转义 `\|`、`<br>`） | 同上 | 同上 | ✅ **重点迁移** |
| `process_md_by_contents.py` | 依据 `Contents.txt` 缩进层级恢复 `# ` 标题层级 | `Contents.txt` + `full.md` | 层级修正后的 .md | ✅ 思路迁移（改用 content_list.json） |
| `mark_c.py` | 编号标题（`# 1.2 Title`）层级推导；说明性行转加粗 | .md | .md | ⚠️ 部分思路（编号标题识别） |
| `clean_images.py` | 删除未被引用的图片 + 清理失效图片引用行 | `full.md` + `images/` | 清理后的 .md | ✅ 思路迁移（图片清理） |
| `delete.py` | 仅删除未被引用图片（`clean_images.py` 的子集） | 同上 | 删除图片 | ✅ 并入 cleanup |
| `split_md.py` | 按一级标题拆分成多文件 | .md | 多个 .md | ❌ 不需要 |
| `md_together.py` | 合并多个 .md | 多个 .md | 单个 .md | ❌ 不需要 |
| `copy_to_full.py` | 拷贝图片/重命名 md（目录整理） | 目录 | 目录 | ❌ 不需要 |
| `rename_folders.py` | 重命名章节目录 | 目录 | 目录 | ❌ 不需要 |
| `replace_amd_links.py` | AMD 文档链接 → Obsidian `[[#]]` | .md | .md | ❌ 不需要 |
| `batch_upload_and_rewrite.py` | 图片批量上传图床 + 重写链接 | .md + 图片 | 图床 URL | ❌ 不需要（Web 上传） |
| `image.py` / `image2.py` | 图片压缩（cv2/cwebp/webp/1-bit） | 图片 | 压缩图片 | ❌ 不需要（体积优化） |

## 2. 与 Spec 问题清单的对应

Spec §5 要求重点检查以下问题是否已有解决方案：

| 问题 | 已有脚本 | 迁移结论 |
|------|----------|----------|
| heading | `process_md_by_contents.py` / `mark_c.py` | ✅ 改为基于 `content_list.json` 的 `text_level` 恢复 |
| HTML/CSS table | `html_table_to_md.py` / `html_table_to_md2.py` | ✅ 迁移 rowspan/colspan 展开算法到 `markdown/tables.py` |
| 重复 table | 无直接方案 | ⚠️ 新增：基于相邻 block 内容去重 |
| 重复 formula | 无直接方案 | ⚠️ 新增：结合 content_list 判断重复公式占位 |
| 重复 image | `clean_images.py` | ✅ 迁移「未引用图片清理」思路；重复引用需新增 |
| 空白行 | 无直接方案 | ⚠️ 新增：normalize 统一 |
| 列表 | 无直接方案 | ⚠️ 新增：block 解析保证列表完整 |
| 代码块 | `html_table_to_md` 附带 | ⚠️ 新增：parser 保护 code fence |
| 公式 | 无直接方案 | ⚠️ 新增：保护 `$`/`$$`，chunk 不切开 |
| MinerU 特殊 Markdown | 见下 | ✅ 见 §4 |

## 3. 值得保留的核心算法

### 3.1 HTML table → Markdown（`html_table_to_md2.py`）

核心：用 `(r, c)` 坐标矩阵展开 rowspan/colspan，避免信息丢失：

- 遍历 `<tr>` → 遍历 `<td>/<th>`；
- 读取 `rowspan` / `colspan`，把单元格内容填充到矩阵的多个坐标；
- 文本处理：`get_text(separator=" ")` 防粘连、`|` → `\|` 转义、换行 → `<br>`；
- 最后把矩阵转成 Markdown 表格（表头行 + 分隔行 + 内容行）。

PaperFlow 迁移到 `src/paperflow/markdown/tables.py`，并加安全兜底：若某表格无法安全转换（如嵌套表格、不规则结构），**保留原 HTML**，正确性优先（spec §16）。

### 3.2 heading 层级恢复（`process_md_by_contents.py` + `mark_c.py`）

`process_md_by_contents.py` 用 `Contents.txt` 的 tab 缩进作为层级，把 `# title` 重写为 `#`×层级。`mark_c.py` 识别编号标题（`# 1.2 Title`）由点号数量推导层级。

PaperFlow 改为：**以 `content_list.json` 的 `text_level` / `type` 为主要层级依据**（spec §13），`# title` 的 Markdown 仅作为内容与顺序来源。编号标题识别逻辑保留为 fallback（当 content_list 缺失时）。

### 3.3 图片清理（`clean_images.py`）

提取 `![...](images/xxx)` 引用集合，删除未被引用图片，清理指向不存在图片的引用行。

PaperFlow 迁移到 `cleanup.py`：只清理「明显失效/重复的图片占位」，**不因『看起来像重复』直接删正文**（spec §18）。

## 4. 从 `LTC2991手册.md` 观察到的 MinerU 真实输出特征

该文件是 MinerU 处理英文芯片手册的典型产物，暴露了以下需要规范化的问题：

1. **`\mathsf`/`\mathbf` 内联数学**：`$\mathsf { T } _ { \mathsf { A } } = 2 5 ^ { \circ } \mathsf { C }$`，`$\boldsymbol{...}$` —— 必须保护，不能翻译。
2. **被拆散的公式**：`$0 . 0 6 ^ { \circ } C$`（数字/符号间被空格拆散）、`$V _ {B E} = \eta \bullet ...$`。
3. **`$$ ... \tag{1} $$`** 显示公式带编号。
4. **HTML `<table>` 大量出现**，含 `colspan="8"`、`rowspan="2"`，单元格内含 `$...$` 公式。
5. **图片**：`![](https://image.114472.xyz/file/...)` 外链图。
6. **标题后大量尾随空格**：`**TYPICAL APPLICATION   **`、`### FUNCTIONAL DIAGRAM   `。
7. **重复内容**：同一「ELECTRICAL CHARACTERISTICS」说明段 + 表格重复出现（页眉/页脚 OCR 重复）。
8. **错误符号**：`$| ^ { 2 } 0$`（I²C 被识别成 `|^2 0`）、`$\mu \lor / \rho \complement$`（μV/°C 误识别）。

这些直接对应 PaperFlow 的 normalization / cleanup 需要处理的问题。

## 5. 迁移策略

按 spec §5：

```text
旧脚本 → 分析核心逻辑 → 重新整理/重写 → PaperFlow module
```

最终 PaperFlow **不** `import ref.markdownchange.xxx`。将以下算法重写为独立模块：

- `html_table_to_md2.py` → `src/paperflow/markdown/tables.py`
- `process_md_by_contents.py` + `mark_c.py` → `src/paperflow/markdown/structure.py`（改用 content_list.json）
- `clean_images.py` → `src/paperflow/markdown/cleanup.py`

并建立 regression fixture（spec §38）：

```text
tests/fixtures/markdownchange-case-001  (HTML table rowspan/colspan)
tests/fixtures/markdownchange-case-002  (heading 层级恢复)
tests/fixtures/markdownchange-case-003  (image cleanup)
```
