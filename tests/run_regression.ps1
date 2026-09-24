# CalaPlayerSrcmBuilder - regression harness wrapper (ASCII only)
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\run_regression.ps1 [-Only T1 T6]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$py = Join-Path $root "python\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
& $py (Join-Path $here "regression.py") @Rest
exit $LASTEXITCODE
