# CalaPlayerSrcmBuilder - wrapper (ASCII only)
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\build_srcm.ps1 `
#       -Paks "D:\Games\CalaPlayer\Content\Paks" -Srcm "D:\srcm"
#       [-Fit cover|contain] [-Force] [-DryRun] [-Combined] [-Ffmpeg <exe>] [-Kit <dir>]
param(
    [Parameter(Mandatory=$true)][string]$Paks,
    [Parameter(Mandatory=$true)][string]$Srcm,
    [ValidateSet("cover","contain")][string]$Fit = "cover",
    [switch]$Force,
    [switch]$DryRun,
    [switch]$NoDeploy,
    [switch]$Combined,
    [string]$Ffmpeg = "",
    [string]$Kit = "",
    [switch]$KeepWork,
    [switch]$NoThumb,
    [switch]$NoAtlas,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
try { chcp 65001 | Out-Null } catch { }
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe  = Join-Path $here "CalaPlayerSrcmBuilder.exe"

$argv = @()
if (Test-Path $exe) {
    $cmd = $exe
} else {
    # development layout: run the Python entry point from this folder
    $py = Join-Path $here "python\python.exe"
    if (-not (Test-Path $py)) { $py = "python" }
    $cmd = $py
    $argv += (Join-Path $here "cli\build_srcm.py")
}

$argv += @("-Paks", $Paks, "-Srcm", $Srcm, "-Fit", $Fit)
if ($Force)    { $argv += "-Force" }
if ($DryRun)   { $argv += "-DryRun" }
if ($NoDeploy) { $argv += "-NoDeploy" }
if ($Combined) { $argv += "-Combined" }
if ($Ffmpeg)   { $argv += @("-Ffmpeg", $Ffmpeg) }
if ($Kit)      { $argv += @("-Kit", $Kit) }
if ($KeepWork) { $argv += "-KeepWork" }
if ($NoThumb)  { $argv += "-NoThumb" }
if ($NoAtlas)  { $argv += "-NoAtlas" }
if ($Quiet)    { $argv += "-Quiet" }

& $cmd @argv
exit $LASTEXITCODE
