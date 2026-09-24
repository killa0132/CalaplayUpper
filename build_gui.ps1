# CalaPlayerSrcmBuilderGUI - build the two GUI Kits (ASCII only)
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\build_gui.ps1 [-Date 20260923]
#
# Produces:  dist\CalaPlayerSrcmBuilder_gui_minimal_<date>\   (no ffmpeg)
#            dist\CalaPlayerSrcmBuilder_gui_full_<date>\      (bundled ffmpeg)
# Both contain CalaPlayerSrcmBuilderGUI.exe + kit\  (self-contained tool chain).
param([string]$Date = (Get-Date -Format "yyyyMMdd"))

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py   = Join-Path $here "python\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "python venv not found: $py" }
$fe   = Join-Path $here "gui\frontend"
$out  = Join-Path $here "build_out\gui"
$dist = Join-Path $here "dist"

Write-Host "=== 1/6 sync the UI art + the two background images ==="
foreach ($bg in @("bg_light.jpg", "bg_dark.jpg")) {
    $src = Join-Path $here $bg
    if (-not (Test-Path $src)) { throw "missing $bg at the project root ($src)" }
    Copy-Item $src (Join-Path $fe "public\$bg") -Force
    Write-Host ("  {0,-14} {1:N0} B" -f $bg, (Get-Item $src).Length)
}
# The page art is looked up in gui\frontend\public (vite copies it into gui\dist,
# which is wiped on every build).  gui\dist is also accepted as a drop folder so
# dropping a new png/gif there survives the next build.
foreach ($art in @("T_UI.png", "chongci.gif", "success.png", "cry.png",
                   "hello.png", "guide.png", "end.png", "joinus.png",
                   "star.png", "joinQQ.png")) {
    $pub = Join-Path $fe "public\$art"
    $dropped = Join-Path $here "gui\dist\$art"
    if ((Test-Path $dropped) -and -not (Test-Path $pub)) { Copy-Item $dropped $pub -Force }
    if (Test-Path $pub) {
        Write-Host ("  {0,-14} {1:N0} B" -f $art, (Get-Item $pub).Length)
    } else {
        throw "missing UI art: $art (put it in gui\frontend\public or gui\dist)"
    }
}
# the window/exe icon must be a real multi-size .ico (System.Drawing.Icon can
# not read a png), so regenerate it from T_UI.png on every build
& $py -c @"
from PIL import Image, ImageOps
import os
pub = os.path.join(r'$fe', 'public')
src = Image.open(os.path.join(pub, 'T_UI.png')).convert('RGBA')
side = max(src.size)
ImageOps.pad(src, (side, side), color=(0, 0, 0, 0), method=Image.LANCZOS).resize((256, 256), Image.LANCZOS).save(
    os.path.join(pub, 'T_UI.ico'),
    sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print('ico from T_UI.png')
"@
if ($LASTEXITCODE -ne 0) { throw "could not (re)generate T_UI.ico (needs Pillow in $py)" }
$ico = Join-Path $fe "public\T_UI.ico"
Write-Host ("  {0,-14} {1:N0} B" -f "T_UI.ico", (Get-Item $ico).Length)

Write-Host "=== 2/6 vite build -> gui\dist ==="
Push-Location $fe
if (-not (Test-Path "node_modules")) {
    Write-Host "  node_modules missing -> npm install"
    & npm.cmd install --no-audit --no-fund 2>&1 | Select-Object -Last 3
}
& npm.cmd run build 2>&1 | Select-Object -Last 6
Pop-Location
if (-not (Test-Path (Join-Path $here "gui\dist\index.html"))) { throw "vite produced no gui/dist/index.html" }
foreach ($bg in @("bg_light.jpg", "bg_dark.jpg")) {
    if (-not (Test-Path (Join-Path $here "gui\dist\$bg"))) { throw "gui/dist is missing $bg" }
}

Write-Host "=== 3/6 PyInstaller (onefile, windowed) ==="
Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
& $py -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name CalaPlayerSrcmBuilderGUI `
    --icon "$here\gui\frontend\public\T_UI.ico" `
    --paths $here `
    --distpath (Join-Path $out "dist") `
    --workpath (Join-Path $out "work") `
    --specpath $out `
    --add-data "$here\gui\dist;gui/dist" `
    --collect-all webview `
    --collect-submodules uvicorn `
    --hidden-import clr `
    --hidden-import anyio._backends._asyncio `
    --exclude-module tkinter --exclude-module matplotlib --exclude-module PySide6 `
    --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module IPython `
    --exclude-module pytest --exclude-module scipy --exclude-module pandas `
    --exclude-module numpy.f2py --exclude-module numpy.testing `
    --exclude-module PIL.ImageQt --exclude-module PIL.ImageTk --exclude-module PIL.ImageShow `
    --exclude-module setuptools --exclude-module pkg_resources `
    --exclude-module sqlite3 --exclude-module doctest --exclude-module pdb --exclude-module pydoc `
    (Join-Path $here "gui_main.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$exe = Join-Path $out "dist\CalaPlayerSrcmBuilderGUI.exe"
if (-not (Test-Path $exe)) { throw "exe not produced: $exe" }
Write-Host ("  exe = {0:N1} MB" -f ((Get-Item $exe).Length / 1MB))

$readme = @"
CalaPlayerSrcmBuilder  (desktop GUI)
====================================
Build date : $Date
Variant    : __VARIANT__

QUICK START
-----------
1. Double-click  CalaPlayerSrcmBuilderGUI.exe
2. Fill in two paths (the "..." button opens the native folder picker):
       game Paks folder  - e.g. D:\CalabiyanGalgameMaker\CalaPlayer
                            (the game root, the Content dir or the Paks dir all work)
       material root     - a folder containing bg / BGM / Sound / Ambient
3. Tick "DryRun" the first time: it builds the container and runs every check
   WITHOUT touching the game folder.
4. Press 开始打包 / Start.  The right side shows the live log; when it finishes
   you get the A0~A7 gate table, the container size and the row counts.
5. Untick DryRun and press Start again to install.  The previously installed
   patch is moved into out_patch\_prev_container first, so the
   "回滚 (uninstall.ps1)" button restores exactly the pre-install state.

THEME
-----
The little switch at the top-right cross-fades between bg_light.jpg and
bg_dark.jpg (620 ms).  The choice is remembered.

OUTPUT
------
Everything lands next to the material root, in  <material root>\..\out_patch\ :
    CalaPlayer-Windows_P.{pak,ucas,utoc}   install.ps1  uninstall.ps1  README.md
    verify\   _prev_container\   build.log   build_report.json

SAFETY
------
* Only the install step writes the game folder, and only after MOVING the
  existing _P container into out_patch\_prev_container.
* After writing, the container is read back from the real game folder and
  checked; if anything fails the previous container is restored automatically.
* The 5 original containers are never written.
* Close the game before installing - a locked container is refused with a
  clear message instead of a half-applied patch.

AUDIO
-----
Audio is embedded as uncompressed PCM 16-bit / 48 kHz, so it is big:
about 11.5 MB per minute stereo, 5.8 MB per minute mono.

AUTOMATION (optional)
---------------------
The window also takes command line arguments, handy for scripts:
    CalaPlayerSrcmBuilderGUI.exe --selftest --selftest-ui --selftest-shell ^
        --paks "<game>" --srcm "<material>" --log-file selftest.txt
and the page exposes  window.__cala.{setParams,run,cancel,state,toggleTheme}.
"@

function New-GuiKit([string]$name, [bool]$withFfmpeg) {
    $root = Join-Path $dist $name
    Remove-Item $root -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    Copy-Item $exe (Join-Path $root "CalaPlayerSrcmBuilderGUI.exe")
    $kit = Join-Path $root "kit"
    foreach ($sub in @("retoc", "da-patch", "tex-inspect", "mappings", "native")) {
        $s = Join-Path $here "kit\$sub"
        if (Test-Path $s) { Copy-Item $s (Join-Path $kit $sub) -Recurse -Force }
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $kit "tex-inspect\native") | Out-Null
    Copy-Item (Join-Path $here "kit\native\*") (Join-Path $kit "tex-inspect\native") -Force
    if ($withFfmpeg) {
        $ff = "C:\Program Files\ffmpeg\bin\ffmpeg.exe"
        if (-not (Test-Path $ff)) { throw "ffmpeg not found at $ff" }
        New-Item -ItemType Directory -Force -Path (Join-Path $kit "ffmpeg") | Out-Null
        Copy-Item $ff (Join-Path $kit "ffmpeg\ffmpeg.exe")
    }
    # the deliverable must not carry stray run artifacts (a rejected build uses to
    # drop build.log next to the exe; the app now works in %LOCALAPPDATA% instead)
    foreach ($junk in @("build.log", "build_report.json", "deploy.json")) {
        $p = Join-Path $root $junk
        if (Test-Path $p) { Remove-Item $p -Force; Write-Host "  removed stray $junk" }
    }
    $strayExe = Get-ChildItem $root -Recurse -File -Include *.pdb
    if ($strayExe) { $strayExe | Remove-Item -Force; Write-Host "  removed stray .pdb" }
    $variant = if ($withFfmpeg) { "full  (bundles ffmpeg, ~200 MB: MP3 / FLAC / 44.1 kHz material works out of the box)" }
               else { "minimal  (no ffmpeg: only 48 kHz / 16-bit PCM .wav material, unless the machine already has ffmpeg on PATH or you pass -Ffmpeg)" }
    ($readme -replace "__VARIANT__", $variant) | Set-Content -Encoding UTF8 (Join-Path $root "README.txt")
    return $root
}

Write-Host "=== 4/6 gui_minimal variant ==="
$min = New-GuiKit "CalaPlayerSrcmBuilder_gui_minimal_$Date" $false
Write-Host "=== 5/6 gui_full variant ==="
$full = New-GuiKit "CalaPlayerSrcmBuilder_gui_full_$Date" $true

Write-Host "=== 6/6 summary ==="
foreach ($d in @($min, $full)) {
    $sz = (Get-ChildItem $d -Recurse -File | Measure-Object -Property Length -Sum).Sum
    $cnt = (Get-ChildItem $d -Recurse -File).Count
    Write-Host ("{0,-46} {1,8:N1} MB  {2} files" -f (Split-Path $d -Leaf), ($sz / 1MB), $cnt)
}
Write-Host "done.  verify with:  python tests\gui_exe_check.py"
