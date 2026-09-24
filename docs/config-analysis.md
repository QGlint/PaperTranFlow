# /config/user/ 配置分析

> 阶段：Phase 1
> 目标：确认现有 API 配置的真实文件格式、字段与组织方式，不猜测、不另起炉灶。

## 1. 实际文件结构（已核实）

```text
config/
├── api                     # 文件，内容 "mireu="
└── user/
    ├── MirerU              # 文件，内容为 MinerU API token（单行纯 token）
    └── GLM                 # 文件，内容为 GLM API key（单行纯 token）
```

### 1.1 `config/user/MirerU`

单行纯文本，值为 MinerU API token（`sk-...` 形式）。无 `key=value`、无 JSON、无 TOML。

### 1.2 `config/user/GLM`

单行纯文本，值为 GLM API key（`{id}.{secret}` 形式，智谱开放平台格式）。无 `key=value`。

### 1.3 `config/api`

内容 `mireu=`（key=value 形式，值为空）。推测为早期/占位配置，当前不被真正使用。

## 2. 关键结论

1. **现有配置是「一个 key 一个纯文本文件」的极简形式**：`<config_dir>/user/<Name>` 的文件内容即 credential。
2. 没有统一的配置文件（无 JSON/TOML/YAML）。字段名即文件名：`MirerU`、`GLM`。
3. `config/user/` 已在 `.gitignore` 中（当前仓库 `.gitignore` 含 `/config/user/`），**不能被 git 追踪**。

## 3. PaperTranFlow 兼容策略

PaperTranFlow 的 `ConfigLoader` / `UserConfigLocator` / `CredentialLoader` 必须：

1. **优先兼容现有 `/config/user/` 纯 token 文件**：
   - MinerU token ← `<config_dir>/user/MirerU`（文件名大小写不敏感，兼容 `MinerU`）。
   - GLM key   ← `<config_dir>/user/GLM`。
2. **`PaperTranFlow_CONFIG_DIR` 环境变量覆盖**配置目录。
3. **Windows 默认用户配置路径**（实现确定，不硬编码 Linux `/config/user/`）：
   - `%APPDATA%\PaperTranFlow\config\`（即 `%APPDATA%\PaperTranFlow\config\user\MirerU`、`...\GLM`）。
4. **可选 TOML 增强**：`user.toml` 可提供 `model` / `base_url` / `chunking` 等非 secret 项；secret 仍优先从纯 token 文件读，避免把 token 写进可能被分享的 TOML。

### 3.1 解析顺序（CredentialLoader）

```text
1. 显式环境变量 PaperTranFlow_MINERU_TOKEN / PaperTranFlow_GLM_KEY（若有）
2. PaperTranFlow_CONFIG_DIR/user/MirerU 与 .../user/GLM
3. Windows: %APPDATA%/PaperTranFlow/config/user/...
4. 开发环境：仓库根 /config/user/...
```

### 3.2 字段映射

| PaperTranFlow 字段 | 来源文件 | 说明 |
|----------------|----------|------|
| `mineru.token` | `user/MirerU` | MinerU API token |
| `glm.api_key` | `user/GLM` | GLM API key |
| `mineru.base_url` | 内置默认 `https://mineru.net/api/v4` | 可被 TOML 覆盖 |
| `glm.base_url` | 内置默认 `https://open.bigmodel.cn/api/paas/v4` | 可被 TOML 覆盖 |
| `glm.model` | 内置默认 `glm-4.7-flash` | 可被 TOML 覆盖 |

## 4. Secret 安全

- `.gitignore` 继续保护 `/config/user/`（已存在，保持）。
- 提供 `config/example/user.example.toml`（**不含真实密钥**，用占位符）。
- `config check` 输出：

```text
MinerU: configured   (或 not configured)
GLM:    configured   (或 not configured)
```

  绝不打印完整 secret（spec §8）。

## 5. 结论

现有 `/config/user/` 是「纯 token 文件」格式，字段名 = 文件名。PaperTranFlow 的 `CredentialLoader` 直接读取这些文件即可完全兼容，**无需要求用户重建配置系统**。额外 TOML 仅作为可选增强（承载 base_url/model/chunking 等非 secret 配置）。
