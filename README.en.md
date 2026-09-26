# CalaplayUpper

[中文](README.md) | **English**

A fool-proof material packing and injection tool for CalaPlayer.

Drop the images, music and sound effects you like into one folder, click a button, and you get a
patch package that works in the game right away. It never overwrites the game's original files,
and you can uninstall everything with one click at any time.

This project is a helper tool built on top of the community's open-source CalaPlayer editor, for
personal study and entertainment only.

---

## ✨ Features

* **One-click packing**: organise your material, press the button, get a game patch
* **Safe, no pollution**: every change is loaded as a patch — the game's original files are never overwritten
* **Roll back any time**: not happy? One-click uninstall puts the game back the way it was
* **Your own thumbnails** (new in v1.1.0): the little preview next to each background entry is generated
  per background, so it shows *your* picture instead of the game's original tile
* **No more stretching** (new in v1.1.0): portrait / square pictures are refused with a clear message,
  every landscape picture is accepted
* **Bilingual UI**: switch between 中文 and English on the fly
* **First-run guide**: nine guided steps the first time you open it
* **Desktop GUI**: no command line — just double-click the exe
* **Automatic checks**: every step of the build is verified; when something is wrong it tells you where it stopped

## 📥 Download

Grab the latest version from the **[Releases](https://github.com/killa0132/CalaplayUpper/releases)** page.

| Variant | Notes |
|---|---|
| **Full** | **Recommended.** Bundles FFmpeg, transcodes MP3 automatically, works out of the box |
| **Minimal** | Smaller, without FFmpeg. Your machine needs FFmpeg already installed to handle MP3 — otherwise WAV only |

Both zips contain `CalaPlayerSrcmBuilderGUI.exe` — double-click it.
**No Python or .NET installation required.**

## 🚀 Quick start

### Step 1 — prepare your material

Create a folder (say `my-material`) with four sub-folders inside:

```text
my-material/
├── bg/        <- background images (.png / .jpg / .jpeg)
├── BGM/       <- background music (.wav / .mp3)
├── Sound/     <- sound effects (item sounds, voices, ...)
└── Ambient/   <- ambience (scene atmosphere)
```

* Images: **2560×1440 (ideal - nothing gets resampled)** or larger; PNG, JPG and JPEG are supported.
* Audio: **WAV is the safest**; MP3 needs the Full build or a local FFmpeg.

(The four folder names are **case-insensitive**, and a missing one is simply skipped.)

### Step 2 — open the tool

Double-click `CalaPlayerSrcmBuilderGUI.exe`. The first launch shows the nine-step guide — just
follow it once.

### Step 3 — pick the paths

* **Game Paks folder**: your CalaPlayer game root (e.g. `D:\CalabiyanGalgameMaker\CalaPlayer`)
* **Material root**: the folder you created above

### Step 4 — build

Press **“Start packing”** and wait for the progress bar to finish. A new `out_patch` folder appears
next to your material folder — that is your patch.

### Step 5 — install into the game

> ⚠️ **Close the game first!**

Open `out_patch`, right-click `install.ps1` and pick “Run in Terminal”. If Windows blocks the
script, follow the [developer guide](docs/DEVELOPER_GUIDE.en.md) to relax the execution policy — or
just run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

Start the game and your new material shows up in the in-game Create editor.

## 🖼️ Screenshots

| Main window | First-run guide |
|---|---|
| [<img src="docs/images/ui-layout.jpg" width="430">](docs/images/ui-layout.jpg) | [<img src="docs/images/guide.jpg" width="430">](docs/images/guide.jpg) |

| Success dialog | Failure dialog |
|---|---|
| [<img src="docs/images/modal-ok.jpg" width="430">](docs/images/modal-ok.jpg) | [<img src="docs/images/modal-fail.jpg" width="430">](docs/images/modal-fail.jpg) |

The progress bar runs like this (`chongci.gif` is its head):

<img src="docs/images/chongci.gif" width="430">

More screenshots (the community dialog, the dropdown and sidebar animations, the text-decode
ripple, the English UI, the minimum window size, and a few cats) are at the end of the
[developer guide](docs/DEVELOPER_GUIDE.en.md).

## ⚙️ Advanced options

The UI has a few options; beginners can ignore them.

| Option | What it does |
|---|---|
| Background fit | `cover` fills and crops (recommended); `contain` keeps the whole image with a border |
| DryRun | Dry run only — builds and checks everything without installing |
| Combined | Append to the previous build instead of starting over |
| Force | Force the build when the material exceeds the default limits |

Default limits: ≤ 59 backgrounds, ≤ 10 minutes of audio, image quality ≥ 25 dB.

## 🧭 Known limitations

* The **timeline cell** and the editor's right-hand **“Background” preview block** now **do show a
  background you added** (since v1.1.0).
  * How (static, no resident injection): each new background's 250×141 thumbnail is **appended to the
    game's own preview atlas `T_BackgroundPreviews`** (in the free cells at the end, index 165+), and
    that background's preview material is pointed at that cell. The game itself hands the cell's
    coordinates to both widgets.
  * Because the atlas only has 59 free cells, the **background limit is 59** (`-Force` goes beyond it,
    and the extra backgrounds' thumbnails will not show).
* The **dropdown thumbnail gets slightly softer (about 30 %)**: due to the game's native rendering
  path (that thumbnail samples only the single atlas cell, and the GPU's mip selection lands on a
  blend of two levels) the little list thumbnail is a bit softer than before — **but not perceptible
  to the eye**, and it is the reasonable trade for the timeline and the preview block finally showing
  the right picture (`-NoAtlas` restores the old behaviour).
* **Unaffected**: the dropdown list itself, the chapter cover on the main menu, and the
  **background inside the game scene** — all of these show your own images.
* The runtime workaround (R2 / `--refresh-backgrounds`) is **deprecated**: it needs Frida running
  beside the game (heavy stutter), its effect is runtime-only, and the game's author confirmed the
  engine entry point it uses is not the intended path. The current approach is the static atlas route
  above (assessment: `docs/CP35_ATLAS_APPEND_ASSESSMENT.md`, design:
  `docs/CP36_ATLAS_APPEND_DESIGN.md` and `docs/CP37_ATLAS_MI_STRATEGY_ASSESSMENT.md`).

## ⚠️ Things to know

* **Always close the game before installing.** While it runs, the `.ucas` file is locked and the
  install can fail — or crash the game.
* Windows may warn about an “unknown publisher”. The exe is simply not code-signed: click “More
  info” → “Run anyway”.
* Prefer **ASCII-only paths**. Avoid Chinese characters and special symbols in both the game
  folder and the material folder.
* You need to own **CalaPlayer itself**. This tool only packs your material; it does not include the game.

## 🆕 Changelog

**v1.1.0 (2026-09-25)** — backward-compatible feature additions:

* **Quality: backgrounds stay at 2560×1440** (route B). Background textures are no longer squashed to
  1920×1080: the cooked texture is rebuilt wholesale, so a 2560×1440 source is **not resampled at all**
  (measured PSNR 35.5 → 36.8 / 41.1 → 41.7 dB).
* **Background thumbnails fixed**: the small preview next to each dropdown entry now renders *your*
  picture (every new background gets its own preview material `MI_<name>`, wired to that row's preview
  reference; append-only — native entries are never replaced). The `-NoThumb` switch restores the old
  behaviour for diagnosis.
* **Aspect-ratio policy (no stretching)**: anything wider than tall is accepted (non-16:9 gets a
  warning); portrait and square pictures are **refused** with a clear message; pass `-Fit contain` to
  have them centred on a 2560×1440 canvas with (18,18,22) bars.
* The regression suite grew to 29 scenarios and a new gate A8 (thumbnail channel); A6 now reads the
  rebuilt texture back **with a real UE parser** (size/format/12 mips/per-mip hashes).

Full history: **[`CHANGELOG.md`](CHANGELOG.md)**.

## 📁 Project structure (developers)

<details>
<summary>Click to expand the folder list</summary>

```text
core/            packing engine (do not change)
cli/             command-line entry (do not change)
gui/             UI layer (free to change)
  frontend/      Vue 3 sources
  dist/          build output
kit/             self-contained tool chain
tools-src/       C# tool sources
tests/           regression tests
docs/            documentation and images
dist/            deliverables (shipped as Release assets)
```

The detailed “which file to edit” table, the CLI switches, the A0~A7 gates, the internals and the
dev/debug guide live in the **[developer guide `docs/DEVELOPER_GUIDE.en.md`](docs/DEVELOPER_GUIDE.en.md)**
(Chinese original: [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md)).

</details>

## 💬 Community & support

* **GitHub Issues**: [report a problem or a suggestion](https://github.com/killa0132/CalaplayUpper/issues)
* **Discord**: [join the channel](https://discord.com/invite/BGeYfMBwaw/login)
* **QQ group**: 1054243070

If this tool helped you, a ⭐ Star on GitHub is the biggest encouragement for the developer, nya~

## 📜 License

Released under the [MIT License](LICENSE).

CalaplayUpper is a community project and is not affiliated with the CalaPlayer team. All game
assets belong to their original authors.
