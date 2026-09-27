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
--work-dir DIR     中间过程目录（默认 .papertranflow/<name>）
--out-dir DIR      结果目录（默认 outfile/<name>）
--upload-images    上传图片到图床并重写 markdown 引用（默认关闭）
```

## 输出

```text
outfile/<论文名>/
├── <论文名>.md        # MinerU 解析的 Markdown（英文原文）
├── <论文名>.zh.md     # 翻译后的简体中文 Markdown
└── images/            # 被引用的图片

.papertranflow/<论文名>/   # 中间过程（可删）
├── mineru/            # MinerU 原始产物
├── normalized.md
├── chunks.json
├── state.json         # checkpoint
└── chunks/            # 每个 chunk 的译文
```

**结构保证**：`input.md` 与 `input.zh.md` 的 block 数量/顺序/层级严格一一对应；
代码、公式（`$...$`）、图片引用原样保留不翻译；
标题层级由 PaperTranFlow 依据 `content_list.json` + 编号推断决定，不交给 LLM。

### 图床上传（可选）

开启 `--upload-images` 后，图片会**一次批量上传**到 cf 图床并归入以论文标题命名的文件夹
（GUI 目录树清晰、同名图不冲突），markdown 中的 `images/xxx.jpg` 会被重写为远程 URL。

## 开发

```bash
python -m pytest tests -q          # 运行测试
.\scripts\build_windows.ps1        # 构建 Windows EXE
```

## License

MPL-2.0。参考项目与第三方声明见 `THIRD-PARTY-NOTICES.md`。
