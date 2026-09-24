# PaperFlow Windows build script (PyInstaller)
#
# Steps: clean -> build -> smoke test
# Output: dist/PaperFlow.exe
#
# Does NOT bundle MinerU / LLM model / API credentials.

param(
    [switch]$OneFile   # onefile mode (default)
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Entry = Join-Path $Root "src\cli.py"
$SrcDir = Join-Path $Root "src"
$Dist = Join-Path $Root "dist"
$Build = Join-Path $Root "build"

Write-Host "==> 1/3 clean"
if (Test-Path $Dist) { Remove-Item $Dist -Recurse -Force }
if (Test-Path $Build) { Remove-Item $Build -Recurse -Force }

Write-Host "==> 2/3 build"
$pyArgs = @(
    "--clean",
    "--noconfirm",
    "--name", "PaperFlow",
    "--distpath", $Dist,
    "--workpath", $Build,
    "--paths", $SrcDir
)
if (-not $OneFile) {
    $pyArgs += "--onedir"
} else {
    $pyArgs += "--onefile"
}
$pyArgs += $Entry

python -m PyInstaller @pyArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

Write-Host "==> 3/3 smoke test"
$Exe = Join-Path $Dist "PaperFlow.exe"
if (-not (Test-Path $Exe)) { throw "PaperFlow.exe not generated" }
& $Exe --help
if ($LASTEXITCODE -ne 0) { throw "smoke test failed" }
& $Exe config check
if ($LASTEXITCODE -ne 0) { throw "config check failed" }

Write-Host "==> Done: $Exe"
