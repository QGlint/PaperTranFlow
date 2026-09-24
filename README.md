# PaperFlow

本地 CLI 优先的文档解析、Markdown 标准化与文档翻译工具。

```text
PDF → MinerU API → Markdown + content_list.json
     → 结构恢复 → Markdown 标准化/清理 → Smart Chunking
     → GLM-4.7-Flash API → 串行翻译 → Retry → Checkpoint → 中文 Markdown
```

## 两个等价入口（同一套 Core）

```text
PaperFlow CLI          paperflow run input.pdf
PaperFlow Windows EXE  PaperFlow.exe run input.pdf
```

## 安装

```bash
pip install -e .
```

## 配置

默认读取开发环境 `/config/user/` 下的纯 token 文件：

```text
config/user/MirerU   # MinerU API token
config/user/GLM      # GLM API key
```

也可用环境变量覆盖配置目录：

```powershell
$env:PAPERFLOW_CONFIG_DIR = "C:\path\to\config"
```

示例配置见 `config/example/user.example.toml`（不含真实密钥）。

## 用法

```bash
paperflow --help

paperflow parse input.pdf          # PDF → MinerU → Markdown (+ content_list.json)
paperflow translate input.md       # Markdown → 中文 Markdown (input.zh.md)
paperflow run input.pdf            # 完整 pipeline（parse + translate）
paperflow resume input.md          # 从 checkpoint 续跑
paperflow config check             # 检查 MinerU/GLM 配置
```

## 输出

```text
input.md       # MinerU 原始 Markdown（可复用）
input.zh.md    # 翻译后的简体中文 Markdown
```

工作目录（含 checkpoint）在 `.paperflow/jobs/<job>/` 下。

## License

MPL-2.0。参考项目与第三方声明见 `THIRD-PARTY-NOTICES.md`。
