# Package the four release zips from dist\<variant>_<date>\ into dist\release\ (ASCII only).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\pack_release.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\pack_release.ps1 -Date 20260926 -Version v1.1.0
#
# The previous zips of the same name are MOVED to dist\release\_stale_<date>\ first, so nothing is
# destroyed.  Each zip keeps the layout the earlier releases used: a top-level folder named after the
# dist directory (exe + kit\ + build_srcm.ps1 + README.txt + KIT_VARIANT.txt), zipped with
# Compress-Archive (which is what produced the published v1.1.0 assets).
param(
    [string]$Date    = (Get-Date -Format yyyyMMdd),
    [string]$Version = "v1.1.0",
    [switch]$KeepStale
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$rel = Join-Path $root "dist\release"
if (-not (Test-Path $rel)) { New-Item -ItemType Directory -Force $rel | Out-Null }

$map = @(
    @{ zip = "CalaPlayerSrcmBuilder_GUI_minimal_$Version.zip"; dir = "CalaPlayerSrcmBuilder_gui_minimal_$Date" },
    @{ zip = "CalaPlayerSrcmBuilder_GUI_full_$Version.zip";    dir = "CalaPlayerSrcmBuilder_gui_full_$Date" },
    @{ zip = "CalaPlayerSrcmBuilder_CLI_minimal_$Version.zip"; dir = "CalaPlayerSrcmBuilder_minimal_$Date" },
    @{ zip = "CalaPlayerSrcmBuilder_CLI_full_$Version.zip";    dir = "CalaPlayerSrcmBuilder_full_$Date" }
)

if (-not $KeepStale) {
    $stale = Join-Path $rel "_stale_$Date"
    foreach ($m in $map) {
        $old = Join-Path $rel $m.zip
        if (Test-Path $old) {
            if (-not (Test-Path $stale)) { New-Item -ItemType Directory -Force $stale | Out-Null }
            Move-Item -Force $old (Join-Path $stale $m.zip)
            Write-Host "moved aside $($m.zip) -> _stale_$Date"
        }
    }
}

$rows = @()
foreach ($m in $map) {
    $src = Join-Path $root ("dist\" + $m.dir)
    if (-not (Test-Path $src)) { throw "missing dist folder: $src" }
    $out = Join-Path $rel $m.zip
    Compress-Archive -Path $src -DestinationPath $out -CompressionLevel Optimal -Force
    $h = (Get-FileHash -LiteralPath $out -Algorithm SHA256).Hash
    $mb = [math]::Round((Get-Item $out).Length / 1MB, 1)
    $rows += [pscustomobject]@{ File = $m.zip; MB = $mb; SHA256 = $h }
    Write-Host ("{0,-52} {1,7} MB  {2}" -f $m.zip, $mb, $h)
}

$md = Join-Path $rel ("PACK_MANIFEST_$Date.md")
$lines = @("# release zips ($Date, $Version)", "", "| file | size | sha256 |", "|---|---|---|")
foreach ($r in $rows) { $lines += ("| ``{0}`` | {1} MB | ``{2}`` |" -f $r.File, $r.MB, $r.SHA256) }
Set-Content -LiteralPath $md -Value $lines -Encoding utf8
Write-Host "wrote $md"
