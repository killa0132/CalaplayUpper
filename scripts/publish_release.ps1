# Upload the zips in dist\release\ to a GitHub Release.  ASCII only.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\publish_release.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\publish_release.ps1 `
#       -Tag v20260924 -Proxy http://127.0.0.1:7897
#
# Why this exists: the machine this project was built on cannot reach
# uploads.github.com (the release-asset endpoint) -- the TLS connection to that
# SNI is reset, while api.github.com and github.com work.  So the Release itself
# can be created from here but the assets have to be pushed from a machine (or a
# local tunnel/proxy) that can reach it.  This script does exactly that.
#
# The token is read from the Git credential manager and never printed.
param(
    [string]$Repo  = "killa0132/CalaplayUpper",
    [string]$Tag   = "v20260924",
    [string]$Dir   = "dist\release",
    [string]$Proxy = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$src  = Join-Path $root $Dir
if (-not (Test-Path $src)) { throw "no such folder: $src" }

$env:GIT_TERMINAL_PROMPT = "0"
$cred = "protocol=https`nhost=github.com`n`n" | git credential fill 2>$null
$tok  = (($cred -split "`n") | Where-Object { $_ -like 'password=*' }) -replace '^password=',''
if (-not $tok) { throw "no GitHub credential found (run 'git push' once so the manager stores one)" }

$hdr = @{ Authorization = "Bearer $tok"; Accept = "application/vnd.github+json" }
$rel = Invoke-RestMethod -Headers $hdr -TimeoutSec 60 `
       "https://api.github.com/repos/$Repo/releases/tags/$Tag"
Write-Host ("release : " + $rel.html_url)
Write-Host ("existing: " + $rel.assets.Count + " asset(s)")

$base = $rel.upload_url -replace '\{.*\}', ''
$zips = Get-ChildItem $src -Filter *.zip
if (-not $zips) { throw "no .zip in $src -- build them first (see README section 6)" }

foreach ($z in $zips) {
    Write-Host ("uploading {0}  ({1:N1} MB)" -f $z.Name, ($z.Length / 1MB))
    $cargs = @("-sS", "-X", "POST",
               "-H", "Authorization: Bearer $tok",
               "-H", "Content-Type: application/zip",
               "--data-binary", "@$($z.FullName)",
               ($base + "?name=" + $z.Name))
    if ($Proxy) { $cargs = @("-x", $Proxy) + $cargs }
    curl.exe @cargs
    if ($LASTEXITCODE -ne 0) { Write-Host ("  FAILED (curl rc=" + $LASTEXITCODE + ")"); continue }
    Write-Host "  ok"
}

Write-Host ("done. check: " + $rel.html_url)
