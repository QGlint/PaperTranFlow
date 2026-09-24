# DocuTranslate 分析

> 阶段：Phase 1
> 参考 commit：`ce0ae3ff08ec0d12b27cc4f1bd9389c4f0cbdbd8`（`fix: decode gzip LLM streaming responses`，2026-09-04）
> 上游：https://github.com/xunbu/docutranslate.git
> License：MPL-2.0

## 1. 项目概况

DocuTranslate 是一个功能完整的本地文档翻译工具，具备：

- 多格式转换（PDF/docx/xlsx/md/txt/json/epub/srt/ass/html/pptx）
- 多 LLM provider（openai / deepseek / bigmodel / gemini / ollama / siliconflow / volcengine / minimax / mimo / openrouter / litellm / dashscope）
- 异步高并发、术语表、Web UI、FastAPI、REST API、WebSocket、MCP、多用户、任务后台、Windows/Mac 打包

## 2. 与 PaperTranFlow 需求对照

| DocuTranslate 能力 | PaperTranFlow 需求 | 结论 |
|--------------------|----------------|------|
| PDF → MinerU 云 API | ✅ 直接对应 | **值得重新实现** |
| MinerU → Markdown + content_list.json | ✅ 直接对应 | **值得重新实现** |
| Markdown 图片 base64 内联 / 占位符 masking | ✅ 需要（图片不进 LLM） | **值得重新实现（masking 思路）** |
| Markdown 分块（layout-aware splitter） | ✅ Smart Chunking | **借鉴思路，重新实现** |
| 翻译 agent（system prompt / retry / `<think>` 清理） | ✅ 翻译后端 | **借鉴 prompt 与重试思路** |
| 多格式 exporter（docx/xlsx/epub/srt/...） | ❌ 不需要 | 舍弃 |
| Web UI / FastAPI / REST / WebSocket | ❌ 不需要 | 舍弃 |
| MCP / 多用户 / 任务后台 | ❌ 不需要 | 舍弃 |
| 大量 provider | ❌ 第一版仅 GLM | 舍弃 |
| 异步 gather 高并发 | ❌ 第一版 concurrency=1 | 舍弃 |

## 3. 关键实现细节（值得参考）

### 3.1 MinerU 云 API 调用流程

`converter/x2md/converter_mineru.py` 提供了完整的 MinerU v4 调用链，这是 PaperTranFlow `MinerUClient` 的直接参考：

1. **申请上传 URL**：`POST https://mineru.net/api/v4/file-urls/batch`
   - Header：`Authorization: Bearer <token>`
   - Body：`{"enable_formula": true, "language": "en", "enable_table": true, "model_version": "vlm", "files": [{"name": "...", "is_ocr": true}]}`
   - 返回 `data.batch_id` 和 `data.file_urls[0]`。
2. **上传文件**：`PUT <file_url>`，body 为 PDF bytes。
3. **轮询结果**：`GET https://mineru.net/api/v4/extract-results/batch/{batch_id}`
   - `data.extract_result[0].state`：`done` / `failed` / 其它（轮询）。
   - `done` 时取 `data.extract_result[0].full_zip_url`。
4. **下载 ZIP**：`GET <full_zip_url>`，内含 `full.md`、`content_list.json`、图片等。
5. **提取 Markdown**：从 ZIP 读 `full.md`。

> 注意：PaperTranFlow **必须保留** `content_list.json`，而不是只提取 `full.md`（spec §13）。

### 3.2 图片 masking（`utils/markdown_utils.py`）

`uris2placeholder` / `placeholder2uris` 把 `![alt](url)` 整体替换为 `<ph-xxxxxx>` 占位符，翻译后再还原。这保证图片不进入 LLM、不改变结构。PaperTranFlow 采用同一思路，但改为 block 级处理：`image` 类型的 block 直接标记为「不翻译」，序列化时原样输出。

### 3.3 Layout-aware 分块（`utils/markdown_splitter.py`）

`MarkdownBlockSplitter` 用正则 `(```...```|~~~...~~~|$$...$$|<ph-xxx>)` 切分特殊块，保证代码/公式/图片不被切开；超大代码块做「拆头去尾 + MERGE_CODE_TOKEN 无缝合并」。PaperTranFlow 的 Smart Chunker 借鉴其「保护不可切结构」思想，但实现为**基于 MarkdownBlock 列表**的 chunker（更符合 spec 的 block 边界优先级）。

### 3.4 翻译 prompt（`agents/markdown_agent.py`）

系统 prompt 要求：只输出译文、保留代码/品牌名/术语、公式用合法 LaTeX、修正异常字符、引用原文不译。PaperTranFlow 的 `GLMBackend` 参考此约束，但按 spec §26 收紧为「准确译为简体中文、不总结/不扩写/不删信息、保持术语一致、不译公式、不改代码、不改结构」。

### 3.5 重试与响应处理（`agents/agent.py`）

- exponential backoff：`0.5 * 2 ** retry_count`。
- 区分可重试（429/5xx/timeout/网络错误）与不可重试（401/403/参数错误）。
- `_sanitize_result` 清理 `<think>...</think>`（GLM 强思考模型的响应前缀）。
- `finish_reason=length` 时继续获取（PaperTranFlow 第一版简化：chunk 已保证不超限，遇到 length 直接失败重试）。
- `mask_secrets` 确保日志不含 key。

## 4. 明确舍弃

```text
Web UI / FastAPI / REST API / WebSocket / MCP
多用户 / 任务管理后台 / LAN 共享
大量 provider / 术语表自动生成 / 异步 gather 高并发
多格式 exporter（docx/xlsx/epub/srt/ass/html/pptx/json）
pydantic schema 层（PaperTranFlow 用 dataclass）
dotenv 环境变量体系（PaperTranFlow 用 ConfigLoader + /config/user/）
```

## 5. 结论

DocuTranslate 中**最值得参考**的是 `converter_mineru.py`（MinerU 云调用链）、`markdown_splitter.py`（不可切结构保护）、`markdown_utils.py`（图片 masking）、`markdown_agent.py`（翻译 prompt）与 `agent.py`（重试/退避/`<think>` 清理）。

PaperTranFlow 采用**独立重新实现**策略：不 `import docutranslate`，重新整理算法后落入 `src/PaperTranFlow/` 对应模块。若个别函数（如 HTML 表格展开）确实复用了 DocuTranslate 表达方式，将按 MPL-2.0 要求保留来源标注（详见 `THIRD-PARTY-NOTICES.md`）。
