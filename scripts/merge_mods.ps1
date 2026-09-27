# CalaPlayer mod merger - CLI wrapper (ASCII only)
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\merge_mods.ps1 `
#       -Mods <mods dir> -Base <clean game Paks> -Out <out dir> [-Select A B] [-KeepWork]
#
# The merger only READS -Base and only WRITES inside -Out.  It never installs
# anything into the game folder; use the generated container with install.ps1.
param(
    [Parameter(Mandatory = $true)][string]$Mods,
    [Parameter(Mandatory = $true)][string]$Base,
    [Parameter(Mandatory = $true)][string]$Out,
    [string[]]$Select = @(),
    [string]$Kit = "",
    [switch]$KeepWork
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$py = Join-Path $root "python\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$argv = @((Join-Path $root "cli\merge_mods.py"), "-Mods", $Mods, "-Base", $Base, "-Out", $Out)
if ($Select.Count -gt 0) { $argv += @("-Select") + $Select }
if ($Kit -ne "") { $argv += @("-Kit", $Kit) }
if ($KeepWork) { $argv += @("-KeepWork") }

& $py @argv
exit $LASTEXITCODE
