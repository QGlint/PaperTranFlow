# PaperFlow Windows 构建脚本（PyInstaller onefile）
#
# 职责：clean -> build -> smoke test
# 产物：dist/PaperFlow.exe
#
# 不打包 MinerU 本体 / LLM 模型 / API credential。

param(
    [switch]$OneFile   # 单文件模式（默认）
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Entry = Join-Path $Root "src\cli.py"
$Dist = Join-Path $Root "dist"
$Build = Join-Path $Root "build"

Write-Host "==> 1/3 clean"
if (Test-Path $Dist) { Remove-Item $Dist -Recurse -Force }
if (Test-Path $Build) { Remove-Item $Build -Recurse -Force }

Write-Host "==> 2/3 build"
$args = @(
    "--clean",
    "--noconfirm",
    "--name", "PaperFlow",
    "--distpath", $Dist,
    "--workpath", $Build
)
if (-not $OneFile) {
    $args += "--onedir"
} else {
    $args += "--onefile"
}
# 不打包密钥：仅入口脚本
$args += $Entry

python -m PyInstaller @args
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

Write-Host "==> 3/3 smoke test"
$Exe = Join-Path $Dist "PaperFlow.exe"
if (-not (Test-Path $Exe)) { throw "PaperFlow.exe 未生成" }
& $Exe --help
if ($LASTEXITCODE -ne 0) { throw "smoke test failed" }
& $Exe config check

Write-Host "==> 完成: $Exe"
