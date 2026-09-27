# CalaPlayer merged _P container installer (ASCII only)
#
#   DRY RUN (prints the plan, touches nothing):
#     powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_merged.ps1 `
#         -Src <folder holding the merged _P trio> -Paks <game Content\Paks>
#
#   REAL INSTALL (backup -> copy -> read back -> auto rollback on any mismatch):
#     powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_merged.ps1 `
#         -Src <folder> -Paks <paks> -Apply
#
#   ROLL BACK to what was installed before:
#     powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_merged.ps1 `
#         -Src <folder> -Paks <paks> -Backup <the backup folder> -Rollback
#
# Rules honored: the game folder is only ever touched through the single
# same-named patch container; the previous container is MOVED aside (never
# deleted), every write is read back by hash, and any mismatch restores the
# previous state automatically.  Native containers and the save file are
# snapshotted before/after and must not change.
param(
    [Parameter(Mandatory = $true)][string]$Src,
    [Parameter(Mandatory = $true)][string]$Paks,
    [string]$Backup = "",
    [switch]$Apply,
    [switch]$Rollback
)
$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$PKG = "CalaPlayer-Windows_P"
$NATIVE = "CalaPlayer-Windows"
$EXTS = @("pak", "ucas", "utoc")

function Say($m) { Write-Host $m }
function Step($m) { Write-Host ("    " + $m) }
function Die($m) { Write-Host ("[X] " + $m) -ForegroundColor Red; exit 1 }
function Ok($m) { Write-Host ("[OK] " + $m) -ForegroundColor Green }
function Sha16($p) { return (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.Substring(0, 16) }

function Trio([string]$dir, [string]$prefix) {
    $t = @{}
    foreach ($e in $EXTS) { $t[$e] = Join-Path $dir ($prefix + "." + $e) }
    return $t
}
function TrioExists($t) {
    foreach ($e in $EXTS) { if (-not (Test-Path -LiteralPath $t[$e])) { return $false } }
    return $true
}
function Snapshot([string]$dir, [string]$skipPrefix) {
    $s = @{}
    if (-not (Test-Path -LiteralPath $dir)) { return $s }
    foreach ($f in Get-ChildItem -LiteralPath $dir -File) {
        if ($skipPrefix -ne "" -and $f.Name.StartsWith($skipPrefix)) { continue }
        $s[$f.Name] = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.Substring(0, 16)
    }
    return $s
}

if (-not (Test-Path -LiteralPath $Src)) { Die "source folder not found: $Src" }
if (-not (Test-Path -LiteralPath $Paks)) { Die "Paks folder not found: $Paks" }
$Src = (Resolve-Path -LiteralPath $Src).Path
$Paks = (Resolve-Path -LiteralPath $Paks).Path
if (-not (Test-Path -LiteralPath (Join-Path $Paks ($NATIVE + ".utoc")))) {
    Die "that does not look like the game Paks folder (no $NATIVE.utoc): $Paks"
}
if ($Backup -eq "") {
    $Backup = Join-Path (Split-Path -Parent $Src) ("install_backup_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
}
$backupRealP = Join-Path $Backup "real_P"
$backupTxt = Join-Path $Backup "BACKUP.txt"
$sav = Join-Path (Split-Path -Parent (Split-Path -Parent $Paks)) "Saved\SaveGames\Scenarios.sav"

Say "CalaPlayer merged-container installer"
Say ("  src     : " + $Src)
Say ("  paks    : " + $Paks)
Say ("  backup  : " + $Backup)

# ---------------------------------------------------------------- rollback mode
if ($Rollback) {
    $bakTrio = Trio $backupRealP $PKG
    if (-not (TrioExists $bakTrio)) { Die ("no backed-up container trio in " + $backupRealP) }
    Say "ROLLBACK: restoring the container that was installed before"
    foreach ($e in $EXTS) {
        $dst = Join-Path $Paks ($PKG + "." + $e)
        if (Test-Path -LiteralPath $dst) { Remove-Item -LiteralPath $dst -Force }
        Copy-Item -LiteralPath $bakTrio[$e] -Destination $dst -Force
    }
    foreach ($e in $EXTS) {
        $dst = Join-Path $Paks ($PKG + "." + $e)
        if ((Sha16 $dst) -ne (Sha16 $bakTrio[$e])) { Die ("rollback read-back mismatch on ." + $e) }
    }
    Ok "rollback done: the previous container is back in place"
    exit 0
}

# ---------------------------------------------------------------- pre-flight
$new = Trio $Src $PKG
if (-not (TrioExists $new)) { Die ("the source folder has no " + $PKG + ".{pak,ucas,utoc}: " + $Src) }
$live = Trio $Paks $PKG
$haveLive = TrioExists $live

if (Get-Process -Name CalaPlayer -ErrorAction SilentlyContinue) {
    Die "CalaPlayer is running -- close the game first (the container is locked while it runs)"
}
if ($haveLive) {
    try {
        $fs = [System.IO.File]::Open($live["ucas"], 'Open', 'ReadWrite', 'None')
        $fs.Close()
    } catch {
        Die ("the installed container is locked (game still holding it?): " + $live["ucas"])
    }
}

Say ""
Say "plan:"
if ($haveLive) {
    foreach ($e in $EXTS) { Step ("move aside  " + $PKG + "." + $e + "  " + (Sha16 $live[$e])) }
    Step ("(they go to " + $backupRealP + ")")
} else {
    Step "no container is installed right now -- nothing to move aside"
}
foreach ($e in $EXTS) { Step ("install     " + $PKG + "." + $e + "  " + (Sha16 $new[$e]) + "  " + (Get-Item -LiteralPath $new[$e]).Length + " B") }
Step "then read every installed file back by sha256 and refuse on any mismatch"
Step ("guard: native containers + " + (Split-Path -Leaf $sav) + " must stay byte-identical")

if (-not $Apply) {
    Say ""
    Ok "DRY RUN -- nothing was touched.  Add -Apply to install."
    exit 0
}

# ---------------------------------------------------------------- install
$nativesBefore = Snapshot $Paks ($PKG + ".")
$savBefore = if (Test-Path -LiteralPath $sav) { Sha16 $sav } else { "n/a" }
New-Item -ItemType Directory -Force -Path $backupRealP | Out-Null

$moved = $false
try {
    if ($haveLive) {
        foreach ($e in $EXTS) {
            Move-Item -LiteralPath $live[$e] -Destination (Join-Path $backupRealP ($PKG + "." + $e)) -Force
        }
        $moved = $true
    }
    foreach ($e in $EXTS) { Copy-Item -LiteralPath $new[$e] -Destination $live[$e] -Force }

    # read-back
    foreach ($e in $EXTS) {
        $got = Sha16 $live[$e]
        $want = Sha16 $new[$e]
        if ($got -ne $want) { throw ("read-back mismatch on ." + $e + ": installed " + $got + " != built " + $want) }
        if ((Get-Item -LiteralPath $live[$e]).Length -ne (Get-Item -LiteralPath $new[$e]).Length) {
            throw ("size mismatch on ." + $e)
        }
    }
    $nativesAfter = Snapshot $Paks ($PKG + ".")
    if ($nativesAfter.Count -ne $nativesBefore.Count) { throw "the set of native container files changed" }
    foreach ($k in $nativesBefore.Keys) {
        if (-not $nativesAfter.ContainsKey($k)) { throw ("native container disappeared: " + $k) }
        if ($nativesAfter[$k] -ne $nativesBefore[$k]) { throw ("native container changed: " + $k) }
    }
    if ($savBefore -ne "n/a") {
        if (-not (Test-Path -LiteralPath $sav)) { throw "the save file disappeared" }
        if ((Sha16 $sav) -ne $savBefore) { throw "Scenarios.sav changed" }
    }
} catch {
    Write-Host ("[!] " + $_.Exception.Message) -ForegroundColor Yellow
    Say "AUTO ROLLBACK: restoring the previous state"
    foreach ($e in $EXTS) { if (Test-Path -LiteralPath $live[$e]) { Remove-Item -LiteralPath $live[$e] -Force } }
    if ($moved) {
        foreach ($e in $EXTS) {
            Move-Item -LiteralPath (Join-Path $backupRealP ($PKG + "." + $e)) -Destination $live[$e] -Force
        }
    }
    Die "install failed, the game folder was restored"
}

# ---------------------------------------------------------------- record
$lines = @()
$lines += "CalaPlayer merged-container install"
$lines += "time        : " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
$lines += "source      : " + $Src
$lines += "paks        : " + $Paks
$lines += ""
$lines += "installed now:"
foreach ($e in $EXTS) { $lines += ("  " + $PKG + "." + $e + "  " + (Sha16 $live[$e]) + "  " + (Get-Item -LiteralPath $live[$e]).Length + " B") }
$lines += ""
$lines += "previous container (in real_P\, restore with -Rollback):"
foreach ($e in $EXTS) {
    $p = Join-Path $backupRealP ($PKG + "." + $e)
    if (Test-Path -LiteralPath $p) { $lines += ("  " + $PKG + "." + $e + "  " + (Sha16 $p) + "  " + (Get-Item -LiteralPath $p).Length + " B") }
}
$lines += ""
$lines += "ultra-safe fallback (an older patch, if you ever need it):"
$lines += "  D:\dsharnessProject\CalaplayUpper\work_cp35\atlas_verify\out_patch\uninstall.ps1"
$lines += ""
$lines += "native containers (unchanged):"
foreach ($k in ($nativesBefore.Keys | Sort-Object)) { $lines += ("  " + $k + "  " + $nativesBefore[$k]) }
$lines += ""
$lines += "Scenarios.sav: " + $savBefore + " (unchanged)"
$lines += ""
$lines += "rollback:"
$lines += "  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_merged.ps1 -Src `"$Src`" -Paks `"$Paks`" -Backup `"$Backup`" -Rollback"
Set-Content -LiteralPath $backupTxt -Value $lines -Encoding UTF8

Say ""
Ok "installed and read back successfully"
foreach ($e in $EXTS) { Step ($PKG + "." + $e + "  " + (Sha16 $live[$e])) }
Say ("  previous container + hashes: " + $backupTxt)
Say ("  rollback: -Backup `"" + $Backup + "`" -Rollback")
exit 0
