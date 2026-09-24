# =============================================================================
#  CalaplayUpper file tidying -- see docs\cleanup_plan_20260924.md (Chinese).
#
#    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\clean.ps1
#        -> DRY RUN: prints exactly what would go away, touches nothing
#    ... -Apply
#        -> really delete
#    ... -Apply -IncludeLogs
#        -> also archive the old logs\ evidence
#
#  Rule: only ever delete things that are regenerable or provably unreferenced.
#  Every target is spelled out below, so this script never "guesses".
#
#  NOTE: ASCII only on purpose.  Windows PowerShell 5.1 reads a .ps1 without a
#  BOM as the ANSI code page (GBK here) and non-ASCII comments break the parser.
# =============================================================================
param(
    [switch]$Apply,
    [switch]$IncludeLogs
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Write-Host "root  : $root"
Write-Host "mode  : $(if ($Apply) { 'APPLY (will delete)' } else { 'DRY-RUN (nothing is touched)' })"
Write-Host ""

# ---------------------------------------------------------------- helpers ---
function Sz($p) {
    if (-not (Test-Path $p)) { return 0 }
    $item = Get-Item $p -Force
    if (-not $item.PSIsContainer) { return $item.Length }
    return (Get-ChildItem $p -Recurse -File -Force -ErrorAction SilentlyContinue |
            Measure-Object Length -Sum).Sum
}

$script:freed = 0
# NB: do NOT call this `Kill` -- the built-in alias `kill` (Stop-Process) wins
# over a function of the same name in PowerShell's command resolution order.
function Drop($rel, $why) {
    $p = Join-Path $root $rel
    if (-not (Test-Path $p)) {
        Write-Host ("  [skip]     {0,-56} (not present)" -f $rel)
        return
    }
    $b = Sz $p
    $script:freed += $b
    $tag = if ($Apply) { "DELETED" } else { "would del" }
    Write-Host ("  [{0}] {1,-56} {2,9:N1} MB  {3}" -f $tag, $rel, ($b / 1MB), $why)
    if ($Apply) { Remove-Item $p -Recurse -Force }
}

function Archive($rel, $why) {
    $src = Join-Path $root $rel
    $items = Get-ChildItem $src -File -ErrorAction SilentlyContinue
    if (-not $items) {
        Write-Host ("  [skip]     {0,-56} (nothing matches)" -f $rel)
        return
    }
    $tag = if ($Apply) { "ARCHIVED" } else { "would mv" }
    Write-Host ("  [{0}] {1,-56} {2,8} file(s)  {3}" -f $tag, $rel, $items.Count, $why)
    if ($Apply) {
        $dest = Join-Path $root "logs\archive"
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        $items | Move-Item -Destination $dest -Force
    }
}

# ------------------------------------------------------------ 1) build junk --
Write-Host "== 1. build junk / one-off artefacts =="
Drop "_probe"                    "CP-32/33 one-off RE probes (incl. a 900 MB native copy); no script reads it"
Drop "build_out"                 "PyInstaller work/dist scratch; both build scripts recreate it"
Drop "tests\mat"                 "regression-generated material (run and forget); rebuilt by regression.py -- do this LAST"
Drop "tools-src\da-patch\bin"    "dotnet publish output; the copy in kit\ is what actually ships"
Drop "tools-src\tex-inspect\bin" "same"

Write-Host ""
Write-Host "== 2. run leftovers / bytecode caches =="
Drop "tests\build.log"             "fallback log written when the exe was run by hand inside tests\"
Drop "tests\build.report.json"     "same"
Drop "tests\mat\build.log"         "same"
Drop "tests\mat\build.report.json" "same"
Drop "tests\_real_before.txt"      "leftover of a manual probe; regression.py only uses a local variable of that name"
foreach ($d in @("cli", "core", "gui", "tests")) {
    Drop "$d\__pycache__" "Python bytecode cache"
}

Write-Host ""
Write-Host "== 3. superseded deliverables =="
Drop "dist\CalaPlayerSrcmBuilder_gui_minimal_20260923" "superseded by gui_minimal_20260924"
Drop "dist\CalaPlayerSrcmBuilder_gui_full_20260923"    "superseded by gui_full_20260924"

# ----------------------------------------------------------------- 4) logs ---
if ($IncludeLogs) {
    Write-Host ""
    Write-Host "== 4. logs\ (archive history, drop one-off debug scripts) =="
    foreach ($f in @("logs\a7_gui_probe.py", "logs\dump_dialog.py", "logs\enc_probe.py",
                     "logs\run_frozen_probe.py", "logs\g4_probe.txt", "logs\g4_probe_err.txt",
                     "logs\g4_probe_log.txt", "logs\g4_probe_out.txt", "logs\nowin_probe.txt",
                     "logs\enc_console.txt", "logs\enc_console2.txt", "logs\enc_noconsole.txt",
                     "logs\enc_noconsole2.txt", "logs\publish_tools.txt", "logs\rebuild_gui.txt",
                     "logs\rebuild_kit.txt", "logs\a7_frozen_gui.txt", "logs\a7_source_gui.txt",
                     "logs\a7_frozen_headless.txt", "logs\a7_source_headless.txt",
                     "logs\a7_frozen_err.txt", "logs\a7_frozen_out.txt", "logs\a7_source_err.txt",
                     "logs\a7_source_out.txt", "logs\g4_all.txt", "logs\g4_doubleclick.txt",
                     "logs\g4_frozen_full.txt", "logs\g4_headless.txt", "logs\g4_noconsole.txt",
                     "logs\g4_selftest.txt", "logs\g4_source_full.txt", "logs\g4_source_stdout.txt")) {
        Drop $f "one-off debug script / intermediate output (conclusions already in README)"
    }
    foreach ($pat in @("g4_*.txt", "g4_*.json", "g5_*.txt", "g6_*.txt", "g6_*.log")) {
        Archive "logs\$pat" "expired evidence of an earlier round -- archive, do not delete"
    }
} else {
    Write-Host ""
    Write-Host "== 4. logs\ =="
    Write-Host "  [skipped]  pass -IncludeLogs to archive the old evidence into logs\archive\"
}

# ------------------------------------------------------------------ summary --
Write-Host ""
if ($Apply) {
    Write-Host ("done.  about {0:N1} MB  ({1:N2} GB) released" -f ($freed / 1MB), ($freed / 1GB))
    Write-Host "next  :  .\tests\run_regression.ps1     (rebuilds tests\mat)"
} else {
    $msg = "dry-run.  about {0:N1} MB  ({1:N2} GB) would be released -- add -Apply to do it"
    Write-Host ($msg -f ($freed / 1MB), ($freed / 1GB))
}
