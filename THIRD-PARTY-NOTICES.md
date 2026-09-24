# PaperFlow 第三方声明

PaperFlow 是独立重新实现的项目，以下记录其参考或依赖的第三方软件。

## DocuTranslate

- **Repository**: https://github.com/xunbu/docutranslate
- **License**: Mozilla Public License 2.0 (MPL-2.0)
- **Reference commit**: `ce0ae3ff08ec0d12b27cc4f1bd9389c4f0cbdbd8`
- **使用方式**: 仅作为架构/算法参考（MinerU 云 API 调用流程、图片占位符 masking、layout-aware 分块、翻译 prompt 与重试/退避思路）。PaperFlow 独立重新实现，不 `import docutranslate`，不复制其源码文件。
- **版权声明**: 原项目 `SPDX-FileCopyrightText: 2025 QinHan`，其 `LICENSE` 保留于 `ref/docutranslate/LICENSE`。

## markdownchange（历史脚本）

- **位置**: `ref/markdownchange/`（本仓库历史脚本）
- **License**: 无独立许可证声明（内部历史代码）
- **使用方式**: HTML table → Markdown（rowspan/colspan 展开）、heading 层级恢复、图片引用清理等算法的参考，重写为 `src/paperflow/markdown/` 下的独立模块。不 `import ref.markdownchange.*`。

## 运行时第三方依赖

| 包 | License | 用途 |
|----|---------|------|
| httpx | BSD-3-Clause | MinerU / GLM HTTP 客户端 |
| beautifulsoup4 | MIT | HTML 表格解析 |
| charset-normalizer | MIT | MinerU ZIP 内 Markdown 编码探测 |

## MinerU / GLM

MinerU 与 GLM（智谱）为外部云 API，不作为 PaperFlow 运行时打包或内置，其服务条款与授权以官方为准。
