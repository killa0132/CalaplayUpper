# =============================================================================
#  Deliverable hygiene check: every Kit under dist\ may only contain the files
#  it is supposed to contain.
#
#    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_dist.ps1
#
#  Why: a deliverable folder gets dirty by being *run* -- the builder's fallback
#  log, a stray .pdb from a dotnet publish, PyInstaller leftovers.  This check
#  makes that sort of thing surface by itself (tests\gui_exe_check.py has the
#  same assertion: "a self-test must not leave files behind in the shipped kit").
#
#  NOTE: ASCII only on purpose (Windows PowerShell 5.1 reads a BOM-less .ps1 as
#  the ANSI code page and non-ASCII characters break the parser).
# =============================================================================
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dist = Join-Path $root "dist"

if (-not (Test-Path $dist)) { Write-Host "no dist\ -- nothing to check"; exit 0 }

$banned = @("build.log", "build.report.json", "deploy.json", "*.pdb", "*.spec",
            "*.pyc", "*.pyo", "Thumbs.db", ".DS_Store")

# The two Kit families legitimately ship different top-level files:
#   CLI (build_kit.ps1): CalaPlayerSrcmBuilder.exe + README.txt
#                        + build_srcm.ps1 (the PowerShell wrapper) + KIT_VARIANT.txt
#   GUI (build_gui.ps1): CalaPlayerSrcmBuilderGUI.exe + README.txt
$allowedCli = @("CalaPlayerSrcmBuilder.exe", "README.txt", "build_srcm.ps1", "KIT_VARIANT.txt")
$allowedGui = @("CalaPlayerSrcmBuilderGUI.exe", "README.txt")
$requiredCli = @("CalaPlayerSrcmBuilder.exe", "README.txt", "build_srcm.ps1", "KIT_VARIANT.txt")
$requiredGui = @("CalaPlayerSrcmBuilderGUI.exe", "README.txt")

$bad = 0
# `dist\release\` is NOT a Kit: it holds the zip attachments that go on the GitHub
# Release (scripts\publish_release.ps1 uploads them).  Checking it as a Kit made
# this script fail by design; skip it explicitly instead of carrying a red check.
$kits = @(Get-ChildItem $dist -Directory | Where-Object { $_.Name -ne "release" } | Sort-Object Name)
if (-not $kits) { Write-Host "dist\ has no Kit directories"; exit 0 }

foreach ($k in $kits) {
    Write-Host ("--- {0}" -f $k.Name)
    $files = @(Get-ChildItem $k.FullName -Recurse -File)
    $mb = ($files | Measure-Object Length -Sum).Sum / 1MB
    $problems = @()

    $isGui = ($k.Name -like "*gui*")
    $allowed = if ($isGui) { $allowedGui } else { $allowedCli }
    $required = if ($isGui) { $requiredGui } else { $requiredCli }

    # 1) the top level must be exactly the allowed set (+ kit\)
    $top = @(Get-ChildItem $k.FullName -Force | Where-Object { $_.Name -ne "kit" })
    $exes = @($top | Where-Object { $_.Name -like "*.exe" })
    if ($exes.Count -ne 1) {
        $problems += "expected exactly 1 exe at the top, found $($exes.Count)"
    } elseif ($isGui -and $exes[0].Name -ne "CalaPlayerSrcmBuilderGUI.exe") {
        $problems += "gui Kit must ship CalaPlayerSrcmBuilderGUI.exe, found $($exes[0].Name)"
    } elseif (-not $isGui -and $exes[0].Name -ne "CalaPlayerSrcmBuilder.exe") {
        $problems += "cli Kit must ship CalaPlayerSrcmBuilder.exe, found $($exes[0].Name)"
    }
    foreach ($f in $top) {
        if ($allowed -contains $f.Name) { continue }
        $problems += "unexpected file at the top: $($f.Name)"
    }
    foreach ($need in $required) {
        if (-not (Test-Path (Join-Path $k.FullName $need))) { $problems += "$need is missing" }
    }

    # 2) kit\ must be complete, and must not carry a .pdb
    $kit = Join-Path $k.FullName "kit"
    if (-not (Test-Path $kit)) {
        $problems += "kit\ is missing"
    } else {
        foreach ($need in @("retoc", "da-patch", "tex-inspect", "mappings", "native")) {
            if (-not (Test-Path (Join-Path $kit $need))) { $problems += "kit\$need is missing" }
        }
        $isFull = $k.Name -like "*full*"
        $ff = Join-Path $kit "ffmpeg\ffmpeg.exe"
        if ($isFull -and -not (Test-Path $ff)) { $problems += "full Kit has no kit\ffmpeg\ffmpeg.exe" }
        if (-not $isFull -and (Test-Path $ff)) { $problems += "minimal Kit unexpectedly bundles ffmpeg" }
    }

    # 3) banned artefacts anywhere inside
    foreach ($pat in $banned) {
        foreach ($h in @(Get-ChildItem $k.FullName -Recurse -File -Filter $pat -ErrorAction SilentlyContinue)) {
            $problems += "banned artifact: $($h.FullName.Substring($k.FullName.Length + 1))"
        }
    }

    if ($problems.Count -eq 0) {
        Write-Host ("    OK   {0} file(s), {1:N1} MB" -f $files.Count, $mb)
    } else {
        $bad += $problems.Count
        Write-Host ("    FAIL {0} file(s), {1:N1} MB" -f $files.Count, $mb)
        foreach ($p in $problems) { Write-Host ("         - " + $p) }
    }
}

Write-Host ""
if ($bad) { Write-Host ("dist check: FAILED ({0} problem(s))" -f $bad); exit 1 }
Write-Host ("dist check: OK -- {0} Kit(s), every file accounted for" -f $kits.Count)
exit 0
