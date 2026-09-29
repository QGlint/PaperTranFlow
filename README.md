# PaperTranFlow

本地 CLI 优先的文档解析、Markdown 标准化与文档翻译工具。

```text
PDF → MinerU API → Markdown + content_list.json
     → 结构恢复（标题层级）→ Markdown 标准化/清理 → Smart Chunking
     → GLM-4.7-Flash API → 串行翻译 → Retry → Checkpoint → 中文 Markdown
```

## 两个等价入口（同一套 Core）

```text
PaperTranFlow CLI          papertranflow run input.pdf
PaperTranFlow Windows EXE  PaperTranFlow.exe run input.pdf
```

## 安装

```bash
pip install -e .
```

## 配置

默认读取开发环境 `config/user/` 下的纯 token 文件：

```text
config/user/MirerU        # MinerU API token
config/user/GLM           # GLM API key
config/user/CfImage.json  # 图床（可选，默认关闭）
```

图床配置文件格式：

```json
{
  "base_url": "https://your-image-host.example.com",
  "token": "your-image-host-token"
}
```

也可用环境变量覆盖配置目录：

```powershell
$env:PAPERTRANFLOW_CONFIG_DIR = "C:\path\to\config"
```

示例配置见 `config/example/`（不含真实密钥）。

## 用法

```bash
papertranflow --help

papertranflow parse input.pdf          # PDF → MinerU → Markdown (+ content_list.json + images)
papertranflow translate input.md       # Markdown → 中文 Markdown
papertranflow run input.pdf            # 完整 pipeline（parse + translate）
papertranflow resume input.md          # 从 checkpoint 续跑
papertranflow config check             # 检查配置状态

# 可选参数
--work-dir DIR      中间过程目录（默认 .papertranflow/<标题>）
--out-dir DIR       结果目录（默认 outfile/）
--category NAME     一级目录 paper/Manual（默认自动判断）
--sub-category NAME 二级目录（类别；省略则不建这一级）
--upload-images     上传图片到图床并重写 markdown 引用（默认关闭）
```

## 输出

默认（不加 `--category`/`--sub-category`）**直接输出到 `outfile/` 下**，不建子文件夹：

```text
outfile/
├── <标题>.md          # MinerU 解析的 Markdown（英文原文，标题已去掉作者/年份）
├── <标题>.zh.md       # 翻译后的简体中文 Markdown
└── images/            # 被引用的图片

.papertranflow/<标题>/   # 中间过程（可删）
├── mineru/            # MinerU 原始产物 + images 缓存
├── normalized.md
├── chunks.json
├── state.json         # checkpoint
└── chunks/            # 每个 chunk 的译文
```

加了 `--category`/`--sub-category` 时，按三级目录组织：

```text
outfile/paper/Sensor/<标题>/
├── <标题>.md
├── <标题>.zh.md
└── images/
```

**标题提取**：输入文件名形如 `作者 - 年份 - 标题.pdf` 时，只保留标题
（如 `Riedijk和Huijsing - 1991 - An integrated....pdf` → `An integrated....`），
方便直接移动到 Obsidian。

**结构保证**：`<标题>.md` 与 `<标题>.zh.md` 的 block 数量/顺序/层级严格一一对应；
代码、公式（`$...$`）、图片引用原样保留不翻译；
标题层级由 PaperTranFlow 依据 `content_list.json` + 编号推断决定，不交给 LLM。

### 图床上传（可选）

开启 `--upload-images` 后，图片会**一次批量上传**到 cf 图床，并按
`<category>/[<sub-category>/]<标题>` 归入文件夹（GUI 目录树清晰、同名图不冲突），
markdown 中的 `images/xxx.jpg` 会被重写为远程 URL。

### 限流避让

翻译严格**单线程串行**（`concurrency = 1`，无并发），并在两次请求之间保持
`request_interval` 秒的间隔主动避让；遇到 GLM 限流（1302/1305）时按
`rate_limit_base` 起步指数退避（上限 `max_delay`）。配置见 `[translation]`。

## 开发

```bash
python -m pytest tests -q          # 运行测试
.\scripts\build_windows.ps1        # 构建 Windows EXE
```

## License

MPL-2.0。参考项目与第三方声明见 `THIRD-PARTY-NOTICES.md`。
