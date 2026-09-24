# PaperTranFlow 架构分析

> 阶段：Phase 1 / Phase 2
> 目标：在开始实现 Core 之前，明确 PaperTranFlow 的总体架构、模块边界、运行时依赖与关键决策。

## 1. 目标与定位

PaperTranFlow 是一个**本地 CLI 优先**的文档解析 + Markdown 标准化 + 文档翻译工具。
对外提供两个等价入口，二者共用同一套 Core：

```text
PaperTranFlow CLI          (Python entry point: PaperTranFlow)
PaperTranFlow Windows EXE  (PyInstaller onefile: PaperTranFlow.exe)
```

核心数据流：

```text
PDF → MinerU API → Markdown + content_list.json
     → 结构恢复 → Markdown 标准化/清理 → Smart Chunking
     → GLM-4.7-Flash API → 串行翻译 → Retry → Checkpoint → 中文 Markdown
```

最终产物：

```text
input.md      (MinerU 原始 Markdown，用于复跑 normalization)
input.zh.md   (翻译后的简体中文 Markdown)
```

## 2. Core 与 CLI 的边界

严格 `core != cli`：

| 层 | 职责 |
|----|------|
| `src/PaperTranFlow/core` | 业务逻辑：MinerU、Markdown、结构、chunking、翻译、retry、checkpoint、output |
| `src/PaperTranFlow/cli.py` | 参数解析、配置加载、启动 Job、显示进度/日志、返回退出码 |

CLI **不得**包含 pipeline 业务逻辑，只把 Core 发出的事件翻译成终端输出。这样未来增加其它前端时无需改业务逻辑。

## 3. 模块划分（最终结构）

```text
PaperTranFlow/
├── pyproject.toml
├── README.md
├── LICENSE
├── LICENSES/
├── THIRD-PARTY-NOTICES.md
├── config/example/user.example.toml
├── docs/            # 分析文档（本目录）
├── ref/             # 参考区（docutranslate / markdownchange），不删不改
├── src/PaperTranFlow/
│   ├── __init__.py
│   ├── cli.py
│   ├── core/        # pipeline.py / models.py / events.py
│   ├── config/      # loader.py / models.py / credentials.py
│   ├── mineru/      # client.py / models.py / content_list.py
│   ├── markdown/    # parser.py / models.py / structure.py / normalize.py
│   │                # tables.py / cleanup.py / serializer.py
│   ├── translation/ # backend.py / glm.py / chunker.py / retry.py / checkpoint.py
│   └── output/      # writer.py
├── tests/
└── scripts/         # build_windows.ps1 / build_windows_onefile.ps1
```

## 4. 各模块职责

### 4.1 config
- `ConfigLoader`：统一加载 MinerU / GLM / PaperTranFlow runtime 配置。
- `UserConfigLocator`：定位用户配置目录（`PaperTranFlow_CONFIG_DIR` 优先，其次 Windows 用户目录，开发环境兼容 `/config/user/`）。
- `CredentialLoader`：读取 token/secret，并负责脱敏（`config check` 只显示 `configured`，不显示明文）。
- 兼容现有 `/config/user/` 的**纯 token 文件**格式（见 `config-analysis.md`）。

### 4.2 mineru
- `MinerUClient`：`submit` → `poll` → `download` → `extract result`。
- API 地址、认证全部来自 `ConfigLoader`，不硬编码进业务逻辑。
- `content_list.py`：解析 `content_list.json`，提取 `type / text_level / page_idx / bbox` 等结构信息。

### 4.3 markdown
- `models.py`：`MarkdownDocument` / `MarkdownBlock`（`block_id / type / source_text / normalized_text / metadata`）。
- `parser.py`：把 Markdown 文本解析成 block 列表（heading / paragraph / list / table / blockquote / code / math / image / thematic_break / raw）。
- `structure.py`：结合 `content_list.json` 恢复 heading 层级。
- `normalize.py`：`MarkdownNormalizer`，产出稳定可预测的 Markdown。
- `tables.py`：HTML/CSS 表格 → 原生 Markdown 表格（含 rowspan/colspan 展开）。
- `cleanup.py`：重复公式/图片占位、空白行、异常字符清理。
- `serializer.py`：把 block 列表序列化回 Markdown。

### 4.4 translation
- `backend.py`：`TranslationBackend` 抽象。
- `glm.py`：`GLMBackend`（OpenAI 兼容 `/chat/completions`，model `glm-4.7-flash`）。
- `chunker.py`：Smart Chunker（soft target + hard limit，边界优先级）。
- `retry.py`：`RetryPolicy`（exponential backoff，区分可重试/不可重试）。
- `checkpoint.py`：每个 chunk 成功后立即落盘 `state.json` + `chunks/*.json`。

### 4.5 core
- `pipeline.py`：编排整个流程，发出事件。
- `models.py`：Job / Chunk / Block 等核心数据结构。
- `events.py`：统一事件枚举（`JOB_STARTED` … `JOB_FAILED`）。

### 4.6 output
- `writer.py`：写 `input.zh.md`，保证与 `input.md` 的 block 数量/顺序/结构严格对应。

## 5. 运行时依赖（最终目标）

保持最小化，与 DocuTranslate 解耦：

| 依赖 | 用途 |
|------|------|
| `httpx` | MinerU + GLM 的 HTTP 客户端 |
| `beautifulsoup4` | HTML 表格解析（rowspan/colspan） |
| `charset-normalizer` | 编码探测（MinerU ZIP 内 markdown） |
| `tomli`（`tomllib` 回退） | 读取可选 TOML 配置 |

**明确不依赖**：FastAPI / uvicorn / MCP / WebSocket / pydantic / aiohttp / 大量 provider / 异步 Web 架构。

`ref/` 仅为参考，**不作为 runtime dependency**：

```python
# 禁止
import docutranslate
import ref.markdownchange.xxx
```

## 6. 关键决策汇总

1. **Config 格式**：兼容 `/config/user/` 纯 token 文件；同时支持 `PaperTranFlow_CONFIG_DIR` 覆盖与可选 TOML。
2. **MinerU**：官方云 API `https://mineru.net/api/v4`，`model_version=vlm`，`enable_formula=True`。
3. **GLM**：OpenAI 兼容 `https://open.bigmodel.cn/api/paas/v4`，`glm-4.7-flash`，`concurrency=1`（严格串行）。
4. **翻译方式**：block 级提取可翻译文本 → GLM → 放回原 block → serializer 重组；不让 LLM 重新生成整份 Markdown。
5. **Chunking**：`target=5000` / `hard_limit=6500`（可配置），边界优先级 `block > paragraph > sentence > newline > word > hard cut`。
6. **Checkpoint**：`source hash` 变化即拒绝 resume；已成功 chunk 绝不重调 GLM。
7. **Windows EXE**：PyInstaller onefile；不打包 MinerU/模型/密钥。
8. **Secret 安全**：token 不进 git/源码/测试/README/日志/checkpoint/输出/EXE；`.gitignore` 继续保护 `/config/user/`。

## 7. 复用 vs 独立重写

- **从 DocuTranslate 借鉴（重新实现，不 import）**：
  - MinerU 云 API 调用流程（submit/poll/download/extract）。
  - 图片占位符 masking（`<ph-xxx>`）避免图片 base64 进入 LLM。
  - `<think>` 响应清理、`finish_reason=length` 处理。
- **从 markdownchange 迁移（重写为 PaperTranFlow module）**：
  - HTML table → Markdown（rowspan/colspan 展开，`html_table_to_md2.py` 算法）。
  - heading 层级恢复（`process_md_by_contents.py` / `mark_c.py` 思路，改为基于 `content_list.json`）。
  - 图片引用清理（`clean_images.py` 思路）。
- **完全舍弃**：Web UI / FastAPI / MCP / REST / WebSocket / 多用户 / 任务后台 / 多 provider / 异步 gather / 图片压缩(cv2/cwebp) / Obsidian 上传。
