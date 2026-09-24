# -*- coding: utf-8 -*-
"""Kit (external tool) discovery + typed wrappers.

The Kit is self contained: no .NET runtime, no Python on the target machine is
required.  Layout (relative to the app root / PyInstaller _MEIPASS):

    kit/retoc/retoc.exe                     (+ oo2core_9_win64.dll next to it)
    kit/da-patch/da-patch.exe
    kit/tex-inspect/tex-inspect.exe         (+ native/oo2core_9_win64.dll ...)
    kit/mappings/CalaPlayer-UE5.7.usmap
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

from .common import BuildError, Log, run, run_ok

FFMPEG_COMMON = (
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
    os.path.expanduser(r"~\scoop\shims\ffmpeg.exe"),
    os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"),
)


def app_root() -> str:
    """Folder that contains core/, kit/, gui/ ..."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def kit_root(override: Optional[str] = None) -> str:
    cands: List[str] = []
    if override:
        cands.append(override)
    env = os.environ.get("CALA_KIT")
    if env:
        cands.append(env)
    cands.append(os.path.join(app_root(), "kit"))
    cands.append(os.path.join(os.path.dirname(sys.executable), "kit"))
    for c in cands:
        if c and os.path.isdir(c):
            return os.path.abspath(c)
    raise BuildError("L0", "kit folder not found",
                     "looked in: %s (pass --kit <dir> or set CALA_KIT)" % ", ".join(cands))


@dataclass
class Kit:
    root: str
    retoc: str
    da_patch: str
    tex_inspect: str
    usmap: str
    ffmpeg: Optional[str] = None

    # ---------------- retoc ----------------
    def _retoc(self, args: List[str], log: Log, stage: str, echo: bool = False,
               timeout: int = 900):
        # retoc loads oo2core_9_win64.dll from its own folder -> run with that cwd
        return run([self.retoc] + args, cwd=os.path.dirname(self.retoc),
                   log=log, stage=stage, echo_stdout=echo, timeout=timeout)

    def to_legacy(self, inp: str, out_dir: str, asset_filter: Optional[str],
                  log: Log, stage: str = "L0", timeout: int = 900):
        args = ["to-legacy", inp, out_dir, "--no-script-objects",
                "--no-shaders", "--version", "UE5_7"]
        if asset_filter:
            args += ["-f", asset_filter]
        os.makedirs(out_dir, exist_ok=True)
        r = self._retoc(args, log, stage, timeout=timeout)
        if not r.ok:
            raise BuildError(stage, "retoc to-legacy failed for %s" % inp, r.tail())
        return r

    def to_zen(self, legacy_root: str, out_utoc: str, log: Log,
               stage: str = "L4", timeout: int = 1200):
        os.makedirs(os.path.dirname(out_utoc), exist_ok=True)
        r = self._retoc(["to-zen", legacy_root, out_utoc, "--version", "UE5_7"],
                        log, stage, timeout=timeout)
        if not r.ok:
            raise BuildError(stage, "retoc to-zen failed (%s -> %s)" % (legacy_root, out_utoc),
                             r.tail())
        return r

    def info(self, utoc: str, log: Log, stage: str = "L4") -> str:
        r = self._retoc(["info", utoc], log, stage)
        return r.out + r.err

    def list_chunks(self, utoc: str, log: Log, stage: str = "L4"):
        r = self._retoc(["list", utoc], log, stage)
        return parse_chunk_list(r.out)

    # ---------------- da-patch ----------------
    def da(self, args: List[str], log: Log, stage: str, timeout: int = 600,
           echo: bool = False):
        return run([self.da_patch] + args, log=log, stage=stage,
                   echo_stdout=echo, timeout=timeout)

    # ---------------- tex-inspect ----------------
    def tex_dump(self, paks: str, pkg_path: str, out_dir: str, log: Log,
                 stage: str = "L0", timeout: int = 900) -> str:
        os.makedirs(out_dir, exist_ok=True)
        r = run([self.tex_inspect, paks, pkg_path, out_dir, self.usmap],
                cwd=os.path.dirname(self.tex_inspect), log=log, stage=stage,
                timeout=timeout)
        if not r.ok:
            raise BuildError(stage, "tex-inspect failed for %s" % pkg_path, r.tail())
        return r.out

    def tex_list(self, paks: str, out_dir: str, log: Log, stage: str = "L0",
                 timeout: int = 900) -> List[str]:
        os.makedirs(out_dir, exist_ok=True)
        r = run([self.tex_inspect, paks, "--list", out_dir],
                cwd=os.path.dirname(self.tex_inspect), log=log, stage=stage,
                timeout=timeout)
        if not r.ok:
            raise BuildError(stage, "tex-inspect --list failed", r.tail())
        return [ln.strip() for ln in r.out.splitlines()
                if ln.strip().endswith((".uasset", ".umap"))]

    def tex_audio_out(self, paks: str, pkg_path: str, out_wav: str, log: Log,
                      stage: str = "L4", timeout: int = 900) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
        r = run([self.tex_inspect, paks, "--audio-out", pkg_path, out_wav, self.usmap],
                cwd=os.path.dirname(self.tex_inspect), log=log, stage=stage,
                timeout=timeout)
        if not r.ok:
            raise BuildError(stage, "tex-inspect --audio-out failed for %s" % pkg_path, r.tail())
        return r.out


def parse_chunk_list(text: str):
    """retoc list -> [(package_id_16hex, type)]"""
    out = []
    for line in text.splitlines():
        f = line.split()
        if len(f) >= 3 and len(f[1]) == 24 and all(c in "0123456789abcdef" for c in f[1]):
            out.append((f[1][:16], f[2]))
    return out


def load_kit(kit_override: Optional[str], ffmpeg_override: Optional[str],
             log: Log, stage: str = "L0") -> Kit:
    root = kit_root(kit_override)
    retoc = _need(root, "retoc", "retoc.exe")
    da = _need(root, "da-patch", "da-patch.exe")
    tex = _need(root, "tex-inspect", "tex-inspect.exe")
    usmap = os.path.join(root, "mappings", "CalaPlayer-UE5.7.usmap")
    if not os.path.isfile(usmap):
        raise BuildError(stage, "usmap missing", usmap)
    if not os.path.isfile(os.path.join(root, "retoc", "oo2core_9_win64.dll")):
        raise BuildError(stage, "kit/retoc/oo2core_9_win64.dll missing",
                         "retoc cannot decompress Oodle blocks without it")
    ff = find_ffmpeg(ffmpeg_override)
    bundled = os.path.join(root, "ffmpeg", "ffmpeg.exe")
    if os.path.isfile(bundled):
        # the "full" Kit ships its own ffmpeg so it works out of the box; an
        # explicit -Ffmpeg still wins.
        if not ffmpeg_override:
            ff = bundled
    kit = Kit(root=root, retoc=retoc, da_patch=da, tex_inspect=tex, usmap=usmap, ffmpeg=ff)
    log(stage, "kit root      : %s" % root)
    log(stage, "retoc         : %s" % retoc)
    log(stage, "da-patch      : %s" % da)
    log(stage, "tex-inspect   : %s" % tex)
    log(stage, "usmap         : %s" % usmap)
    log(stage, "ffmpeg        : %s" % (ff or "<not found>"))
    return kit


def _need(root: str, folder: str, exe: str) -> str:
    p = os.path.join(root, folder, exe)
    if not os.path.isfile(p):
        raise BuildError("L0", "kit tool missing: %s" % p, "kit root = %s" % root)
    return p


def find_ffmpeg(override: Optional[str] = None) -> Optional[str]:
    if override:
        if os.path.isfile(override):
            return os.path.abspath(override)
        w = shutil.which(override)
        if w:
            return w
        raise BuildError("L1", "-Ffmpeg path is not a file: %s" % override)
    if os.environ.get("CALA_NO_FFMPEG"):
        # test hook: pretend this machine has no ffmpeg at all
        return None
    env = os.environ.get("CALA_FFMPEG")
    if env and os.path.isfile(env):
        return os.path.abspath(env)
    w = shutil.which("ffmpeg")
    if w:
        return w
    for c in FFMPEG_COMMON:
        if c and os.path.isfile(c):
            return c
    return None


FFMPEG_HELP = (
    "未找到 ffmpeg，但素材里有需要转码的音频（例如 MP3）。\n"
    "      ffmpeg not found but transcoding is required (e.g. MP3 material).\n"
    "      请任选其一 / pick one:\n"
    "        1) 安装 ffmpeg 并确保它在 PATH 中（winget install Gyan.FFmpeg）\n"
    "           install ffmpeg and put it on PATH\n"
    "        2) 用 -Ffmpeg \"<ffmpeg.exe 的绝对路径>\" 手动指定\n"
    "           pass -Ffmpeg \"<full path to ffmpeg.exe>\"\n"
    "        3) 把素材改成 48kHz / 16-bit / PCM 的 .wav 文件（脚本不需要 ffmpeg）\n"
    "           convert your material to 48kHz 16-bit PCM .wav yourself\n"
)
