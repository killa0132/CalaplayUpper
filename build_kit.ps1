# CalaPlayerSrcmBuilder - build the two self-contained Kits (ASCII only)
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\build_kit.ps1 [-Date 20260923]
param([string]$Date = (Get-Date -Format "yyyyMMdd"))

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py   = Join-Path $here "python\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "python venv not found: $py" }
$out  = Join-Path $here "build_out"
$dist = Join-Path $here "dist"
Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "=== 1/5 PyInstaller onefile build ==="
& $py -m PyInstaller --noconfirm --clean --onefile --console `
    --name CalaPlayerSrcmBuilder `
    --paths $here `
    --distpath (Join-Path $out "dist") `
    --workpath (Join-Path $out "work") `
    --specpath $out `
    --exclude-module tkinter --exclude-module matplotlib --exclude-module PySide6 `
    --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module IPython `
    --exclude-module pytest --exclude-module scipy --exclude-module pandas `
    --exclude-module numpy.f2py --exclude-module numpy.testing `
    --exclude-module numpy.distutils --exclude-module numpy.random.tests `
    --exclude-module PIL.ImageQt --exclude-module PIL.ImageTk --exclude-module PIL.ImageShow `
    --exclude-module setuptools --exclude-module pkg_resources --exclude-module distutils `
    --exclude-module sqlite3 --exclude-module doctest --exclude-module pdb --exclude-module pydoc `
    (Join-Path $here "main.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$exe = Join-Path $out "dist\CalaPlayerSrcmBuilder.exe"
if (-not (Test-Path $exe)) { throw "exe not produced: $exe" }
Write-Host ("exe = {0:N1} MB" -f ((Get-Item $exe).Length / 1MB))

function New-Kit([string]$name, [bool]$withFfmpeg) {
    $root = Join-Path $dist $name
    Remove-Item $root -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    Copy-Item $exe (Join-Path $root "CalaPlayerSrcmBuilder.exe")
    Copy-Item (Join-Path $here "build_srcm.ps1") $root
    $kit = Join-Path $root "kit"
    New-Item -ItemType Directory -Force -Path $kit | Out-Null
    foreach ($sub in @("retoc","da-patch","tex-inspect","mappings","native")) {
        $src = Join-Path $here "kit\$sub"
        if (Test-Path $src) { Copy-Item $src (Join-Path $kit $sub) -Recurse -Force }
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $kit "tex-inspect\native") | Out-Null
    Copy-Item (Join-Path $here "kit\native\*") (Join-Path $kit "tex-inspect\native") -Force
    if ($withFfmpeg) {
        $ff = "C:\Program Files\ffmpeg\bin\ffmpeg.exe"
        if (-not (Test-Path $ff)) { throw "ffmpeg not found at $ff" }
        New-Item -ItemType Directory -Force -Path (Join-Path $kit "ffmpeg") | Out-Null
        Copy-Item $ff (Join-Path $kit "ffmpeg\ffmpeg.exe")
    }
    return $root
}

Write-Host "=== 2/5 minimal Kit (WAV only, no ffmpeg) ==="
$min = New-Kit "CalaPlayerSrcmBuilder_minimal_$Date" $false
Write-Host "=== 3/5 full Kit (bundled ffmpeg) ==="
$full = New-Kit "CalaPlayerSrcmBuilder_full_$Date" $true

Write-Host "=== 4/5 READMEs ==="
$common = @"
CalaPlayerSrcmBuilder - one stop srcm packer for CalaPlayer
===========================================================
Build date : $Date

QUICK START
-----------
1. Make a material folder (anywhere), e.g. D:\srcm, with four sub folders:
       srcm\bg         images  (png/jpg/bmp/webp/tga/tif/gif)
       srcm\BGM        music
       srcm\Sound      sound effects
       srcm\Ambient    ambience
   Missing folders are simply skipped.  Optional srcm\names.json:
       { "bg/city.jpg": "City Night", "BGM/wind.mp3": "Night Wind" }

2. Run:
       powershell -NoProfile -ExecutionPolicy Bypass -File .\build_srcm.ps1 ``
           -Paks "D:\CalabiyanGalgameMaker\CalaPlayer\Content\Paks" ``
           -Srcm "D:\srcm"

   Better: give only the game root, the tool finds Content\Paks itself:
           -Paks "D:\CalabiyanGalgameMaker\CalaPlayer"

3. The result lands in <parent of srcm>\out_patch\ :
       CalaPlayer-Windows_P.pak / .ucas / .utoc   <- the patch container
       install.ps1  uninstall.ps1  README.md
       verify\        decoded WAVs + background previews
       _prev_container\   the container that was installed before
       build.log  build_report.json

   install.ps1 is run automatically unless you pass -DryRun.
   To install or roll back by hand:
       powershell -NoProfile -ExecutionPolicy Bypass -File .\out_patch\install.ps1
       powershell -NoProfile -ExecutionPolicy Bypass -File .\out_patch\uninstall.ps1

SWITCHES
--------
  -Paks <dir>       game root / Content dir / Paks dir      (required)
  -Srcm <dir>       material root                            (required)
  -Fit cover|contain  background fit, default cover (fill + centre crop);
                      contain letterboxes with (18,18,22) bars
  -DryRun           run L0..L4 only, never touch the game folder
  -Combined         accumulate on top of the previous out_patch build instead of
                    rebuilding from the native tables only
  -Force            override the limits (bg <= 50, audio <= 10 min, PSNR >= 25 dB)
  -Ffmpeg <exe>     explicit ffmpeg path
  -Kit <dir>        explicit kit folder
  -KeepWork         keep the previous build tree for debugging

SAFETY
------
* L0..L4 write only inside <srcm parent>\out_patch\.
* Only the deploy step writes the game folder, and only after MOVING the
  existing _P container into out_patch\_prev_container\.
* If the post-deploy read-back check fails the tool restores the previous
  container automatically and exits non-zero.
* The 5 native containers are never written.

AUDIO FORMAT
------------
Audio ends up as uncompressed PCM 16-bit / 48000 Hz inside a streaming
SoundWave, so it is big: about 11.5 MB per minute stereo, 5.8 MB per minute
mono.  MP3/FLAC/OGG/44.1 kHz WAV etc. must be transcoded with ffmpeg first.
"@
$common | Set-Content -Encoding UTF8 (Join-Path $min "README.txt")
$common | Set-Content -Encoding UTF8 (Join-Path $full "README.txt")
@"
This is the FULL Kit: it bundles ffmpeg (about 200 MB) so MP3 and other
non-PCM material works out of the box, on a machine with nothing installed.
"@ | Set-Content -Encoding UTF8 (Join-Path $full "KIT_VARIANT.txt")
@"
This is the MINIMAL Kit: no ffmpeg is bundled, it is about 200 MB smaller.
Only 48 kHz / 16-bit / PCM .wav material can be packed - unless the target
machine happens to have ffmpeg on PATH (or you pass -Ffmpeg <exe>).
"@ | Set-Content -Encoding UTF8 (Join-Path $min "KIT_VARIANT.txt")

Write-Host "=== 5/5 summary ==="
foreach ($d in @($min, $full)) {
    $sz = (Get-ChildItem $d -Recurse -File | Measure-Object -Property Length -Sum).Sum
    $cnt = (Get-ChildItem $d -Recurse -File).Count
    Write-Host ("{0,-46} {1,8:N1} MB  {2} files" -f (Split-Path $d -Leaf), ($sz / 1MB), $cnt)
}
Write-Host "done."
