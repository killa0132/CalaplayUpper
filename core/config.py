# -*- coding: utf-8 -*-
"""Project constants + path discovery.

Hard rule from the user: NEVER hardcode a game/srcm path.  Every location is
either derived from the two CLI arguments or discovered from the filesystem.
The only 'fixed' strings here are UE asset identities inside the *game*, which
are content names (not paths) and are each verified at L0.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .common import BuildError, ensure_dir

# --------------------------------------------------------------------------
# asset identities inside CalaPlayer (verified at L0 before use)
# --------------------------------------------------------------------------
#?  1920x1080 PF_DXT1 11-mip texture used as the cooked shell for backgrounds.
TEX_SHELL = "/Game/CalaPlayer/Backgrounds/T_Evni_Background_01_O"
TEX_SHELL_EXPECTED_UEXP = 1383410          # measured; 11 mips of BC1
TEX_SHELL_EXPECTED_SIZE = (1920, 1080)
TEX_SHELL_MIPS = 11

#?  smallest BINKA SoundWave; converted into a streaming PCM single-chunk wave.
SND_SHELL = "/Game/CalaPlayer/SFX/Ambient/LS_BP3_Rain__SFX_"
SND_SHELL_EXPECTED_UEXP = 150
SND_SHELL_FORMAT_NAME = "BINKA"

DA_BACKGROUNDS = "/Game/CalaPlayer/Backgrounds/DA_Backgrounds"
DA_BGM = "/Game/CalaPlayer/BGM/DA_BGM"
DA_AMBIENT = "/Game/CalaPlayer/SFX/Ambient/DA_Ambient"
DA_SOUNDS = "/Game/CalaPlayer/SFX/Sounds/DA_Sounds"

MOUNT_POINT = "../../../"
PATCH_SUFFIX = "_P"

# --------------------------------------------------------------------------
# srcm layout
# --------------------------------------------------------------------------
KIND_BG = "bg"
KIND_BGM = "BGM"
KIND_SOUND = "Sound"
KIND_AMBIENT = "Ambient"
KINDS = (KIND_BG, KIND_BGM, KIND_SOUND, KIND_AMBIENT)

#: folder aliases accepted inside srcm (case-insensitive)
SRCM_ALIASES: Dict[str, str] = {
    "bg": KIND_BG, "background": KIND_BG, "backgrounds": KIND_BG,
    "bgm": KIND_BGM, "music": KIND_BGM,
    "sound": KIND_SOUND, "sounds": KIND_SOUND, "sfx": KIND_SOUND, "audio": KIND_SOUND,
    "ambient": KIND_AMBIENT, "ambients": KIND_AMBIENT, "environment": KIND_AMBIENT,
}

#: package folder + DA table per kind
KIND_PKG_FOLDER: Dict[str, str] = {
    KIND_BG: "/Game/CalaPlayer/Backgrounds",
    KIND_BGM: "/Game/CalaPlayer/BGM",
    KIND_SOUND: "/Game/CalaPlayer/SFX/Sounds",
    KIND_AMBIENT: "/Game/CalaPlayer/SFX/Ambient",
}
KIND_DA: Dict[str, str] = {
    KIND_BG: DA_BACKGROUNDS,
    KIND_BGM: DA_BGM,
    KIND_SOUND: DA_SOUNDS,
    KIND_AMBIENT: DA_AMBIENT,
}

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tga", ".webp", ".tif", ".tiff", ".gif")
AUDIO_EXTS = (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus", ".aiff", ".aif")

TARGET_W, TARGET_H = 1920, 1080
LETTERBOX_RGB = (18, 18, 22)

# --------------------------------------------------------------------------
# limits (user ruling 2026-09-23): bg <= 50, audio total <= 10 min, -Force overrides
#
# The three accessors below are the ONLY place the limits are read from.
# They honour optional environment overrides so the regression harness can
# exercise the limit / -Force code paths with tiny material instead of
# generating 51 full-size backgrounds (see tests/regression.py).
# --------------------------------------------------------------------------
MAX_BG = 50
MAX_AUDIO_SECONDS = 600.0
MAX_CONTAINER_MB = 2048.0        # sanity stop before we produce a monster container
MIN_PSNR_DB = 25.0               # image quality gate (never silently pass a broken encoder)


def _num(env: str, default: float) -> float:
    raw = os.environ.get(env)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def limit_max_bg() -> int:
    return int(_num("CALA_MAX_BG", MAX_BG))


def limit_max_audio_seconds() -> float:
    return _num("CALA_MAX_AUDIO_SECONDS", MAX_AUDIO_SECONDS)


def limit_min_psnr() -> float:
    return _num("CALA_MIN_PSNR", MIN_PSNR_DB)


#: audio target: PCM s16le / 48000 Hz / <= 2 channels
AUDIO_RATE = 48000
AUDIO_BITS = 16
AUDIO_MAX_CH = 2

OUT_PATCH_DIRNAME = "out_patch"

NAME_JSON = "names.json"


def safe_token(text: str, fallback: str = "Item", maxlen: int = 48) -> str:
    """ASCII, filesystem- and FName-safe token (used for *object/package* names)."""
    s = text.strip()
    s = re.sub(r"[^0-9A-Za-z_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        return fallback
    if s[0].isdigit():
        s = "U" + s
    return s[:maxlen]


def display_name(text: str, maxlen: int = 48) -> str:
    """What the in-game dropdown shows: keep it human (non-ASCII allowed)."""
    s = text.strip()
    s = re.sub(r"[\r\n\t]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:maxlen]


@dataclass
class GamePaths:
    """Everything we discovered about the game install at L0."""
    paks_dir: str
    container_base: str                 # e.g. "CalaPlayer-Windows"
    native_containers: List[str] = field(default_factory=list)   # full paths (utoc)
    patch_files: Dict[str, str] = field(default_factory=dict)    # ext -> path

    @property
    def patch_stem(self) -> str:
        return os.path.join(self.paks_dir, self.container_base + PATCH_SUFFIX)

    @property
    def has_existing_patch(self) -> bool:
        return bool(self.patch_files)


def looks_like_patch(name: str, container_base: str) -> bool:
    stem = os.path.splitext(name)[0]
    return stem == container_base + PATCH_SUFFIX


def discover_game(paks_arg: str) -> GamePaths:
    """Accept the game root, the UE project root, the Content dir, or the Paks dir."""
    p = os.path.abspath(paks_arg)
    if not os.path.exists(p):
        raise BuildError("L0", "game path does not exist: %s" % p)
    if os.path.isfile(p):
        p = os.path.dirname(p)

    candidates: List[str] = [p]
    for rel in ("Content/Paks", "Content/paks", "CalaPlayer/Content/Paks",
                "../CalaPlayer/Content/Paks", "../Content/Paks", "*"):
        candidates.append(os.path.normpath(os.path.join(p, rel)))

    found: Optional[str] = None
    for c in candidates:
        if c == "*":
            try:
                for sub in os.listdir(p):
                    sp = os.path.join(p, sub)
                    for rel in ("Content/Paks", "CalaPlayer/Content/Paks"):
                        q = os.path.join(sp, rel)
                        if os.path.isdir(q):
                            found = q
                            break
                    if found:
                        break
            except OSError:
                pass
            continue
        if os.path.isdir(c):
            utocs = [f for f in os.listdir(c) if f.lower().endswith(".utoc")]
            if utocs:
                found = c
                break
    if not found:
        raise BuildError("L0", "cannot find the Paks directory under %s" % p,
                         "expected a folder containing *-Windows.utoc + global.utoc")
    found = os.path.abspath(found)

    utocs = sorted(f for f in os.listdir(found) if f.lower().endswith(".utoc"))
    bases = [f[:-5] for f in utocs if not f[:-5].endswith(PATCH_SUFFIX)]
    # the game container is the one with a matching .ucas, name ends with -Windows
    win = [b for b in bases if b.endswith("-Windows")]
    if not win:
        raise BuildError("L0", "no <Game>-Windows.utoc found in %s" % found,
                         "paks dir contains: %s" % ", ".join(utocs))
    base = win[0]

    gp = GamePaths(paks_dir=found, container_base=base)
    for f in sorted(os.listdir(found)):
        if not looks_like_patch(f, base):
            continue
        ext = os.path.splitext(f)[1].lower().lstrip(".")
        gp.patch_files[ext] = os.path.join(found, f)
    for b in bases:
        gp.native_containers.append(os.path.join(found, b + ".utoc"))
    # global.utoc must be present for script objects / global data
    if not os.path.exists(os.path.join(found, "global.utoc")):
        raise BuildError("L0", "global.utoc missing in %s" % found,
                         "CUE4Parse/retoc cannot resolve script objects without it")
    return gp


def discover_srcm(srcm_arg: str) -> Dict[str, str]:
    """Map kind -> folder for the 4 known sub folders (case-insensitive)."""
    p = os.path.abspath(srcm_arg)
    if not os.path.isdir(p):
        raise BuildError("L0", "srcm folder does not exist: %s" % p)
    got: Dict[str, str] = {}
    for name in sorted(os.listdir(p)):
        full = os.path.join(p, name)
        if not os.path.isdir(full):
            continue
        kind = SRCM_ALIASES.get(name.strip().lower())
        if kind and kind not in got:
            got[kind] = full
    return got


def out_patch_dir(srcm_arg: str) -> str:
    """<parent of srcm>/out_patch  -- build.log lives here AND beside srcm."""
    return os.path.join(os.path.dirname(os.path.abspath(srcm_arg)), OUT_PATCH_DIRNAME)


#: the UE project folder name as it appears at the root of a retoc legacy tree.
#: It is DISCOVERED at L0 from what `retoc to-legacy` actually emitted (never guessed).
TOP_FOLDER = "CalaPlayer"


def legacy_rel_from_pkg(pkg_path: str) -> str:
    """/Game/CalaPlayer/BGM/X  ->  CalaPlayer/Content/CalaPlayer/BGM/X"""
    if not pkg_path.startswith("/Game/"):
        raise BuildError("L2", "package path is not under /Game/: %s" % pkg_path)
    return os.path.join(TOP_FOLDER, "Content", *pkg_path[len("/Game/"):].split("/"))


def legacy_suffix_from_pkg(pkg_path: str) -> str:
    """Path below the project folder: /Game/CalaPlayer/BGM/X -> CalaPlayer/BGM/X"""
    return pkg_path[len("/Game/"):]


def pkg_from_legacy_rel(rel: str) -> str:
    parts = rel.replace("\\", "/").split("/")
    try:
        i = parts.index("Content")
    except ValueError:
        raise BuildError("L0", "legacy path has no Content segment: %s" % rel)
    return "/Game/" + "/".join(parts[i + 1:])
