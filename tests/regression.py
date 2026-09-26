# -*- coding: utf-8 -*-
"""End-to-end regression harness for CalaPlayerSrcmBuilder.

Purpose
-------
Freeze the behaviour that has already been verified, so that later changes
(the Vue/FastAPI/PyWebView GUI in particular) cannot silently break the CLI
gates, the deploy step or the rollback step.

What it does
------------
Generates its own tiny material (no dependency on the old project tree), runs a
series of scenarios through the SHIPPED exe against the sandbox game folder
(`tests/fakegame`), and asserts on `build_report.json`, on the real container
hashes and on the rollback result.  It also snapshots the REAL game folder
before and after, and fails if anything there changed.

    python tests\\regression.py                 # everything
    python tests\\regression.py --only T1 T6    # a subset
    python tests\\regression.py --list
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = "CalaPlayer-Windows" + "_P"
FAKEGAME = os.path.join(HERE, "fakegame")
PAKS = os.path.join(FAKEGAME, "Content", "Paks")
MAT = os.path.join(HERE, "mat")
OUT = os.path.join(MAT, "out_patch")     # <srcm parent>/out_patch, see core/config.py
REAL_GAME_DEFAULT = r"D:\CalabiyanGalgameMaker\CalaPlayer\Content\Paks"

#: optional overrides filled in from the CLI (--exe / --kit)
EXE_OVERRIDE = None
KIT_DIR = None

sys.path.insert(0, ROOT)


# --------------------------------------------------------------------------
def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def patch_snapshot(paks: str) -> dict:
    out = {}
    if not os.path.isdir(paks):
        return out
    for f in sorted(os.listdir(paks)):
        if f.startswith(PKG):
            out[f] = sha256(os.path.join(paks, f))
    return out


def find_exe(override=None) -> list:
    """Command prefix used to launch the builder (prefers the shipped exe)."""
    if override:
        if not os.path.isfile(override):
            raise Fail("--exe not found: %s" % override)
        return [override]
    cands = []
    dist = os.path.join(ROOT, "dist")
    if os.path.isdir(dist):
        for d in sorted(os.listdir(dist), reverse=True):
            p = os.path.join(dist, d, "CalaPlayerSrcmBuilder.exe")
            if os.path.isfile(p):
                cands.append(p)
    cands.append(os.path.join(ROOT, "build_out", "dist", "CalaPlayerSrcmBuilder.exe"))
    for c in cands:
        if os.path.isfile(c):
            return [c]
    py = os.path.join(ROOT, "python", "Scripts", "python.exe")
    if not os.path.isfile(py):
        py = sys.executable
    return [py, os.path.join(ROOT, "cli", "build_srcm.py")]


# --------------------------------------------------------------------------
# material generation
# --------------------------------------------------------------------------
def make_png(path: str, w: int, h: int, seed: int) -> None:
    from PIL import Image
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = ((x * 7 + seed * 31) % 256, (y * 5 + seed * 17) % 256,
                        ((x ^ y) * 3 + seed * 11) % 256)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)


def make_wav(path: str, seconds: float, rate: int = 48000, ch: int = 1) -> None:
    import math
    n = int(seconds * rate)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            v = int(12000 * math.sin(2 * math.pi * (220 + 40 * ch) * i / rate))
            for _c in range(ch):
                frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


def _ffmpeg():
    env = os.environ.get("CALA_FFMPEG")
    if env and os.path.isfile(env):
        return env
    w = shutil.which("ffmpeg")
    if w:
        return w
    for c in (r"C:\Program Files\ffmpeg\bin\ffmpeg.exe", r"C:\ffmpeg\bin\ffmpeg.exe"):
        if os.path.isfile(c):
            return c
    return None


def _make_mp3(ff: str, src: str, dst: str) -> bool:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    r = subprocess.run([ff, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
                        "-i", src, "-vn", "-sn", "-dn", "-c:a", "libmp3lame",
                        "-b:a", "128k", dst], capture_output=True)
    return r.returncode == 0 and os.path.isfile(dst)


def build_material() -> dict:
    """Create (or refresh) every srcm folder the scenarios need."""
    if os.path.isdir(MAT):
        shutil.rmtree(MAT)
    m = {}

    d = os.path.join(MAT, "demo")
    make_png(os.path.join(d, "bg", "sunset.png"), 320, 180, 1)
    make_png(os.path.join(d, "bg", "夜景 测试.png"), 400, 300, 2)   # non-ASCII + non-16:9
    make_wav(os.path.join(d, "BGM", "theme.wav"), 1.0)
    make_wav(os.path.join(d, "Sound", "blip.wav"), 0.5, ch=2)
    make_wav(os.path.join(d, "Ambient", "room.wav"), 0.8)
    with open(os.path.join(d, "names.json"), "w", encoding="utf-8") as f:
        json.dump({"bg/sunset.png": "Sunset 自定义名"}, f, ensure_ascii=False)
    m["demo"] = d

    d = os.path.join(MAT, "bgonly")
    make_png(os.path.join(d, "bg", "a.png"), 160, 90, 3)              # 16:9 landscape
    m["bgonly"] = d

    # aspect-ratio policy fixtures (user ruling 2026-09-25): landscape passes,
    # square / portrait are refused unless -Fit contain was asked for.
    d = os.path.join(MAT, "bgportrait")
    make_png(os.path.join(d, "bg", "b.png"), 90, 160, 4)              # portrait -> contain bars
    m["bgportrait"] = d

    d = os.path.join(MAT, "bgwide")
    make_png(os.path.join(d, "bg", "w.png"), 1233, 725, 5)            # wide, NOT 16:9 -> allowed
    m["bgwide"] = d

    d = os.path.join(MAT, "bgsquare")
    make_png(os.path.join(d, "bg", "s.png"), 1024, 1024, 6)           # square -> refused
    m["bgsquare"] = d

    d = os.path.join(MAT, "audioonly")
    make_wav(os.path.join(d, "Sound", "s1.wav"), 0.4)
    make_wav(os.path.join(d, "BGM", "m1.wav"), 0.6, ch=2)
    m["audioonly"] = d

    d = os.path.join(MAT, "badimg")
    os.makedirs(os.path.join(d, "bg"), exist_ok=True)
    with open(os.path.join(d, "bg", "broken.png"), "w", encoding="utf-8") as f:
        f.write("definitely not a png")
    m["badimg"] = d

    d = os.path.join(MAT, "mp3only")
    make_wav(os.path.join(d, "tmp.wav"), 0.5)
    ff = _ffmpeg()
    if ff and _make_mp3(ff, os.path.join(d, "tmp.wav"),
                        os.path.join(d, "BGM", "needs_ffmpeg.mp3")):
        m["mp3only"] = d

    d = os.path.join(MAT, "threebg")
    for i, name in enumerate(("one.png", "two.png", "three.png")):
        make_png(os.path.join(d, "bg", name), 160, 90, 10 + i)
    m["threebg"] = d

    d = os.path.join(MAT, "extra")
    make_wav(os.path.join(d, "Ambient", "extra.wav"), 0.3)
    m["extra"] = d

    # a folder with nothing usable in it
    d = os.path.join(MAT, "empty")
    os.makedirs(os.path.join(d, "bg"), exist_ok=True)
    m["empty"] = d
    return m


# --------------------------------------------------------------------------
# scenario runner
# --------------------------------------------------------------------------
class Fail(AssertionError):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)


def run_build(cmd_prefix, srcm, extra_args, env_extra, wipe=True, timeout=1800):
    if wipe and os.path.isdir(OUT):
        shutil.rmtree(OUT, ignore_errors=True)
    env = os.environ.copy()
    env.update(env_extra or {})
    argv = cmd_prefix + ["-Paks", FAKEGAME, "-Srcm", srcm]
    if KIT_DIR:
        argv += ["-Kit", KIT_DIR]
    argv += ["-Quiet"] + list(extra_args)
    t0 = time.time()
    p = subprocess.run(argv, capture_output=True, env=env, timeout=timeout)
    secs = time.time() - t0
    rep = None
    rep_path = os.path.join(OUT, "build_report.json")
    if os.path.isfile(rep_path):
        with open(rep_path, encoding="utf-8") as f:
            rep = json.load(f)
    return p.returncode, rep, p, secs


def load_log():
    p = os.path.join(OUT, "build.log")
    return open(p, encoding="utf-8", errors="replace").read() if os.path.isfile(p) else ""


def lock_file(path: str):
    """Open `path` denying write/delete sharing -- exactly what a running game does."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                               wintypes.HANDLE]
    h = k32.CreateFileW(path, 0x80000000, 0x00000001, None, 3, 0, None)
    if h is None or h in (-1, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFF):
        raise Fail("cannot lock %s (GetLastError=%d)" % (path, ctypes.get_last_error()))
    return h


def unlock_file(h) -> None:
    import ctypes
    ctypes.WinDLL("kernel32").CloseHandle(h)


SCENARIOS = [
    dict(id="T1", name="full dry run, all gates", srcm="demo", args=["-DryRun"],
         ok=True, gates=True, deployed=False,
         # independent literal expectations: if the fixture itself gets mangled
         # (that happened once) these fail instead of silently agreeing with it
         expect_keys=["Sunset 自定义名", "夜景 测试"]),
    dict(id="T2", name="deploy + read-back + rollback", srcm="demo", args=[],
         ok=True, gates=True, deployed=True, rollback=True),
    dict(id="T3", name="backgrounds only (audio gates skipped)", srcm="bgonly",
         args=["-DryRun"], ok=True, gates=True, deployed=False, no_audio=True),
    dict(id="T4", name="audio only (no background)", srcm="audioonly", args=["-DryRun"],
         ok=True, gates=True, deployed=False),
    dict(id="T5", name="contain fit letterboxes a portrait picture", srcm="bgportrait",
         args=["-DryRun", "-Fit", "contain"], ok=True, log_has="borders",
         post="letterbox_centred"),
    dict(id="T6", name="broken image fails at L1", srcm="badimg", args=["-DryRun"],
         ok=False, err_has="cannot decode image"),
    dict(id="T7", name="mp3 without ffmpeg gives the hint", srcm="mp3only",
         args=["-DryRun"], env={"CALA_NO_FFMPEG": "1"}, ok=False, err_has="ffmpeg"),
    dict(id="T8", name="background limit stops the build", srcm="threebg", args=["-DryRun"],
         env={"CALA_MAX_BG": "2"}, ok=False, err_has="over the limit"),
    dict(id="T9", name="-Force overrides the background limit", srcm="threebg",
         args=["-DryRun", "-Force"], env={"CALA_MAX_BG": "2"}, ok=True),
    dict(id="T10", name="PSNR gate stops a bad encoder result", srcm="bgonly",
         args=["-DryRun"], env={"CALA_MIN_PSNR": "99"}, ok=False,
         err_has="image quality gate failed"),
    dict(id="T11", name="-Force overrides the PSNR gate", srcm="bgonly",
         args=["-DryRun", "-Force"], env={"CALA_MIN_PSNR": "99"}, ok=True),
    dict(id="T12", name="empty material folder is rejected", srcm="empty",
         args=["-DryRun"], ok=False, err_has="no usable material"),
    dict(id="T13", name="-Combined accumulates the previous build", srcm="extra",
         seed="bgonly", args=["-DryRun", "-Combined"], ok=True, gates=True, combined=True),
    dict(id="T14", name="locked container (game running) is refused", srcm="bgonly",
         args=[], pre="lock_ucas", ok=False, err_has="is locked", sandbox_untouched=True),
    dict(id="T15", name="minimal Kit runs with NO ffmpeg at all", srcm="demo",
         args=["-DryRun"], env={"CALA_NO_FFMPEG": "1"}, ok=True, gates=True),
    dict(id="T16", name="full Kit uses its BUNDLED ffmpeg", srcm="demo",
         args=["-DryRun"], env={"CALA_NO_FFMPEG": "1"}, ok=True, needs_bundled=True),
    dict(id="T17", name="-Kit override is honoured", srcm="bgonly",
         args=["-DryRun"], ok=True, gates=True, needs_kit_flag=True),
    dict(id="T18", name="mp3 IS transcoded when ffmpeg exists", srcm="mp3only",
         args=["-DryRun"], ok=True, gates=True, log_has="transcode"),
    dict(id="T19", name="-Ffmpeg <path> explicit override", srcm="mp3only",
         args=["-DryRun"], ok=True, gates=True, args_ffmpeg=True),
    dict(id="T20", name="-Combined with nothing to carry warns", srcm="bgonly",
         args=["-DryRun", "-Combined"], ok=True, gates=True, log_has="nothing to carry"),
    dict(id="T21", name="state survives a FAILED -Combined run", srcm="extra",
         args=["-DryRun", "-Combined"], pre="combined_after_failure", no_wipe=True,
         ok=True, gates=True, combined=True),
    # ---- aspect-ratio policy (2026-09-25) -------------------------------------
    dict(id="T22", name="1233x725 wide (not 16:9) is accepted", srcm="bgwide",
         args=["-DryRun"], ok=True, gates=True, log_has="非 16:9 图片"),
    dict(id="T23", name="square 1024x1024 is refused with the Chinese hint",
         srcm="bgsquare", args=["-DryRun"], ok=False,
         err_has="请自行裁剪或加黑边转换为 16:9"),
    dict(id="T24", name="portrait 90x160 + cover is refused (contain is the escape)",
         srcm="bgportrait", args=["-DryRun"], ok=False,
         err_has="请自行裁剪或加黑边转换为 16:9"),
    # ---- thumbnail channel: one preview MI per background (CP-34) -------------
    dict(id="T25", name="one preview MI per background, DA row @30 -> it",
         srcm="bgonly", args=["-DryRun"], ok=True, gates=True, post="mi_authored"),
    dict(id="T26", name="-NoThumb keeps the v1 behaviour (no MI, inherited @30)",
         srcm="bgonly", args=["-DryRun", "-NoThumb"], ok=True, gates=True, post="no_thumb"),
    # ---- preview atlas: one cell per background on the game's own grid (CP-37) --------------
    dict(id="T27", name="preview atlas: the background gets cell 165 @ (1260,1430)",
         srcm="bgonly", args=["-DryRun"], ok=True, gates=True,
         gates_extra=("A9", "A9b", "A10"), post="atlas_one_tile"),
    dict(id="T28", name="-NoAtlas keeps the whole-image preview MI (CP-36 shape)",
         srcm="bgonly", args=["-DryRun", "-NoAtlas"], ok=True, gates=True, post="no_atlas"),
    # ---- -Combined on top of an already-appended table (CP-37b: the DA baseline bug) --------
    dict(id="T29", name="-Combined adds backgrounds on top of a previous build",
         srcm="threebg", seed="bgonly", args=["-DryRun", "-Combined"], ok=True, gates=True,
         gates_extra=("A9", "A9b", "A10"), post="combined_adds"),
]


def letterbox_centred(tag: str) -> str:
    """Visual truth for `-Fit contain`: the picture must sit *centred* between
    two equal (18,18,22) bars -- measured on the preview the build itself wrote.

    Geometric assertions, not "the log mentioned borders":
      * the first and last pixel of the middle scanline are the letterbox colour
      * the left bar and the right bar have the same width (+-2 px)
      * there IS a picture between them (the centre is not the letterbox colour)
    BC1 quantises (18,18,22) to (16,16,16), hence the +-14 tolerance.
    """
    from PIL import Image
    p = os.path.join(OUT, "verify", "b_preview.png")
    check(os.path.isfile(p), "%s no preview written at %s" % (tag, p))
    im = Image.open(p).convert("RGB")
    w, h = im.size
    y = h // 2
    px = im.load()

    def is_bar(x: int) -> bool:
        r, g, b = px[x, y]
        return abs(r - 18) <= 14 and abs(g - 18) <= 14 and abs(b - 22) <= 14

    check(is_bar(0), "%s left border is not the letterbox colour: %s" % (tag, px[0, y]))
    check(is_bar(w - 1), "%s right border is not the letterbox colour: %s" % (tag, px[w - 1, y]))
    left = 0
    while left < w and is_bar(left):
        left += 1
    right = w - 1
    while right >= 0 and is_bar(right):
        right -= 1
    check(left > 0 and right < w - 1,
          "%s there is no picture between the bars (left=%d right=%d)" % (tag, left, right))
    lb, rb = left, w - 1 - right
    check(abs(lb - rb) <= 2, "%s the picture is not centred: %d px left bar vs %d px right bar"
          % (tag, lb, rb))
    r, g, b = px[(left + right) // 2, y]
    check(max(abs(r - 18), abs(g - 18), abs(b - 22)) > 30,
          "%s the centre is still the letterbox colour %s -- nothing was pasted"
          % (tag, (r, g, b)))
    return " | letterbox centred (%d|%d px bars, picture %d px wide)" % (lb, rb, right - left + 1)


def _report() -> dict:
    p = os.path.join(OUT, "build_report.json")
    check(os.path.isfile(p), "no build_report.json at %s" % p)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def mi_authored(tag: str) -> str:
    """Thumbnail channel truth: every new background row points its `@30` at an MI
    of its own, that MI is packed, and its report entry says so.

    The authoritative resolution (`@30` -> MaterialInstanceConstant named MI_x, and
    that MI's SourceTexture -> our texture) is gate A8; this hook additionally
    proves the *report/manifest* carries the MI identity, which is what
    `-Combined` later re-uses.
    """
    rep = _report()
    bgs = [m for m in rep["materials"] if m["kind"] == "bg"]
    check(bgs, "%s the report has no background material" % tag)
    for m in bgs:
        check(m.get("mi_obj") == "MI_" + m["name"],
              "%s mi_obj is %r, expected 'MI_%s'" % (tag, m.get("mi_obj"), m["name"]))
        check((m.get("mi_pkg") or "").endswith("/" + m["mi_obj"]),
              "%s mi_pkg is %r" % (tag, m.get("mi_pkg")))
        check(int(m.get("mi_ref") or 0) < 0,
              "%s mi_ref is %r (must be a negative FPackageIndex)" % (tag, m.get("mi_ref")))
        check(int(m.get("mi_tex_ref") or 0) < 0,
              "%s mi_tex_ref is %r (the MI must reference our texture)" % (tag, m.get("mi_tex_ref")))
        for k in ("SpriteWidth", "SpriteHeight", "TextureWidth", "TextureHeight"):
            check(k in (m.get("mi_scalars") or ""),
                  "%s mi_scalars is %r, %s is missing" % (tag, m.get("mi_scalars"), k))
        check((m.get("mi_legacy_rel") or "").endswith("/" + m["mi_obj"] + ".uasset"),
              "%s mi_legacy_rel is %r" % (tag, m.get("mi_legacy_rel")))
    check(rep["gates"]["A8"]["ok"], "%s gate A8 is not ok" % tag)
    return " | %d preview MI (%s)" % (len(bgs), ", ".join(m["mi_obj"] for m in bgs))


def no_thumb(tag: str) -> str:
    """`-NoThumb` must reproduce exactly the v1 behaviour: no MI is authored, A8 is
    skipped, and the ImportMap stays at its native size."""
    rep = _report()
    bgs = [m for m in rep["materials"] if m["kind"] == "bg"]
    check(bgs, "%s the report has no background material" % tag)
    for m in bgs:
        check(not m.get("mi_obj"), "%s -NoThumb still authored %r" % (tag, m.get("mi_obj")))
        check(not m.get("mi_ref"), "%s -NoThumb wrote mi_ref=%r" % (tag, m.get("mi_ref")))
    check(rep["gates"]["A8"]["detail"].startswith("skipped"),
          "%s A8 should be skipped with -NoThumb, it says %r" % (tag, rep["gates"]["A8"]["detail"]))
    check("-NoThumb" in load_log(), "%s the log never mentions -NoThumb" % tag)
    return " | %d bg row(s) inherited @30 (v1 behaviour)" % len(bgs)


def atlas_one_tile(tag: str) -> str:
    """CP-37: the background got its own cell on the game's preview grid.

    Asserts the *numbers* (cell index, coordinates, block count, cell PSNR) and that A9/A9b/A10 all
    passed - including the "mip0 changed = 0 native pixels" claim, which is what makes the atlas
    append safe for the 165 native thumbnails.
    """
    rep = _report()
    bgs = [m for m in rep["materials"] if m["kind"] == "bg"]
    check(bgs, "%s the report has no background material" % tag)
    check(len(bgs) == 1, "%s expected exactly 1 background, got %d" % (tag, len(bgs)))
    m = bgs[0]
    check(m.get("cell_index") == 165,
          "%s cell_index is %r, expected 165 (the first free cell)" % (tag, m.get("cell_index")))
    check(m.get("mi_tex_obj") == "T_BackgroundPreviews",
          "%s mi_tex_obj is %r, expected the game's atlas" % (tag, m.get("mi_tex_obj")))
    sc = m.get("mi_scalars") or ""
    for k in ("SpriteX", "SpriteY", "SpriteWidth", "SpriteHeight", "TextureWidth", "TextureHeight"):
        check(k in sc, "%s mi_scalars is %r, %s is missing" % (tag, sc, k))
    at = rep.get("atlas") or {}
    check(at, "%s the report has no atlas section" % tag)
    cell = (at.get("cells") or [{}])[0]
    check((cell.get("index"), cell.get("x"), cell.get("y")) == (165, 1260, 1430),
          "%s atlas cell is %r, expected index 165 @ (1260,1430)" % (tag, cell))
    check((at.get("blocks_changed") or 0) > 2000,
          "%s only %r BC1 blocks changed" % (tag, at.get("blocks_changed")))
    q = (at.get("quality") or [{}])[0]
    check(float(q.get("psnr") or 0) >= 25.0,
          "%s atlas cell PSNR is %r (the 25 dB gate)" % (tag, q.get("psnr")))
    for g in ("A9", "A9b", "A10"):
        gv = rep["gates"].get(g) or {}
        check(gv.get("ok"), "%s gate %s not ok: %s" % (tag, g, gv.get("detail")))
    check("changed=0" in (rep["gates"]["A9b"]["detail"] or ""),
          "%s A9b does not report the mip0 zero: %s" % (tag, rep["gates"]["A9b"]["detail"]))
    over = len((rep.get("ledger") or {}).get("override") or [])
    check(over == len(rep.get("da_counts") or {}) + 1,
          "%s ledger override count %d != %d DA tables + the atlas"
          % (tag, over, len(rep.get("da_counts") or {})))
    check(rep["params"].get("max_bg") == 59,
          "%s the reported background cap is %r, expected the atlas' 59 free cells"
          % (tag, rep["params"].get("max_bg")))
    return " | cell 165 (1260,1430), %s blocks, cell PSNR %s dB, A9/A9b/A10 PASS" % (
        at.get("blocks_changed"), q.get("psnr_db") or q.get("psnr"))


def no_atlas(tag: str) -> str:
    """`-NoAtlas` must reproduce the CP-36 shape: whole-image preview MI, no atlas override."""
    rep = _report()
    bgs = [m for m in rep["materials"] if m["kind"] == "bg"]
    check(bgs, "%s the report has no background material" % tag)
    for m in bgs:
        check(int(m.get("cell_index") or -1) < 0,
              "%s -NoAtlas still assigned cell %r" % (tag, m.get("cell_index")))
        check(m.get("mi_tex_obj") not in ("", "T_BackgroundPreviews"),
              "%s -NoAtlas mi_tex_obj is %r (it must stay on our own texture)"
              % (tag, m.get("mi_tex_obj")))
    check(rep.get("atlas") is None, "%s -NoAtlas still produced an atlas section" % tag)
    for g in ("A9", "A9b", "A10"):
        gv = rep["gates"].get(g) or {}
        check(gv.get("ok"), "%s gate %s not ok: %s" % (tag, g, gv.get("detail")))
        check((gv.get("detail") or "").startswith("skipped"),
              "%s gate %s should be skipped with -NoAtlas, it says %r" % (tag, g, gv.get("detail")))
    over = len((rep.get("ledger") or {}).get("override") or [])
    check(over == len(rep.get("da_counts") or {}),
          "%s ledger override count %d != %d DA tables (no atlas expected)"
          % (tag, over, len(rep.get("da_counts") or {})))
    check("-NoAtlas" in load_log(), "%s the log never mentions -NoAtlas" % tag)
    return " | %d bg row(s), whole-image MI, no atlas override" % len(bgs)

def combined_adds(tag: str) -> str:
    """CP-37b: a `-Combined` run that ADDS backgrounds must append them onto the **native** table.

    This is the case the old code got wrong (`bgref` re-serializing an already-appended DA grew its
    uexp by one row while the row count stayed, so the L3 trailer gate refused).  Asserts that every
    carried + new row is present, that the atlas grew, and that the three atlas gates passed.
    """
    rep = _report()
    bgs = [m for m in rep["materials"] if m["kind"] == "bg"]
    check(len(bgs) >= 2, "%s expected >= 2 backgrounds in this run, got %d" % (tag, len(bgs)))
    counts = rep.get("da_counts") or {}
    check(counts.get("DA_Backgrounds", 0) >= 165 + len(bgs),
          "%s DA_Backgrounds has %r rows, expected >= 165 + %d (carried rows are re-appended too)"
          % (tag, counts.get("DA_Backgrounds"), len(bgs)))
    for m in bgs:
        check(m.get("cell_index", -1) >= 165,
              "%s %s got cell %r" % (tag, m["name"], m.get("cell_index")))
    at = rep.get("atlas") or {}
    check(at.get("cells"), "%s the report has no atlas cells" % tag)
    for g in ("A9", "A9b", "A10"):
        gv = rep["gates"].get(g) or {}
        check(gv.get("ok"), "%s gate %s not ok: %s" % (tag, g, gv.get("detail")))
    check("changed=0" in (rep["gates"]["A9b"]["detail"] or ""),
          "%s A9b does not report the mip0 zero: %s" % (tag, rep["gates"]["A9b"]["detail"]))
    over = len((rep.get("ledger") or {}).get("override") or [])
    check(over == len(counts) + 1,
          "%s ledger override count %d != %d DA tables + the atlas" % (tag, over, len(counts)))
    return " | %d bg row(s) on top of the carried one, DA=%s, A9/A9b/A10 PASS" % (
        len(bgs), counts.get("DA_Backgrounds"))


def do_scenario(sc, cmd_prefix, state):
    h = None
    if sc.get("pre") == "lock_ucas":
        h = lock_file(os.path.join(PAKS, "%s.ucas" % PKG))
    try:
        return _do_scenario(sc, cmd_prefix, state)
    finally:
        if h is not None:
            unlock_file(h)


def _do_scenario(sc, cmd_prefix, state):
    if sc.get("needs_bundled"):
        bundled = os.path.join(os.path.dirname(cmd_prefix[0]), "kit", "ffmpeg", "ffmpeg.exe")
        if not os.path.isfile(bundled):
            return "SKIP [%s] %s (this Kit does not bundle ffmpeg)" % (sc["id"], sc["name"])
    if sc.get("needs_kit_flag") and not KIT_DIR:
        return "SKIP [%s] %s (pass --kit to test the override)" % (sc["id"], sc["name"])
    if sc.get("pre") == "combined_after_failure":
        # 1) a good build that creates the accumulated state
        _rc, rep0, _p0, _s0 = run_build(cmd_prefix, state["mat"]["bgonly"], ["-DryRun"], None)
        check(rep0 is not None and rep0.get("ok"),
              "%s seed run failed: %s" % (sc["id"], (rep0 or {}).get("error")))
        # 2) a -Combined run that dies in the middle -- it must NOT eat the state
        _rc, rep1, _p1, _s1 = run_build(cmd_prefix, state["mat"]["badimg"],
                                        ["-DryRun", "-Combined"], None, wipe=False)
        check(rep1 is not None and not rep1.get("ok"),
              "%s the deliberately failing -Combined run unexpectedly succeeded" % sc["id"])
    extra_args = list(sc["args"])
    if sc.get("args_ffmpeg"):
        ff = _ffmpeg()
        if not ff:
            return "SKIP [%s] %s (no ffmpeg on this machine)" % (sc["id"], sc["name"])
        extra_args += ["-Ffmpeg", ff]
    srcm = state["mat"].get(sc["srcm"])
    if srcm is None:
        return "SKIP [%s] %s (material not available on this machine)" % (sc["id"], sc["name"])
    tag = "[%s] %-46s" % (sc["id"], sc["name"])
    if sc.get("seed"):
        rc0, rep0, _p0, _s0 = run_build(cmd_prefix, state["mat"][sc["seed"]], ["-DryRun"], None)
        check(rep0 is not None and rep0.get("ok"),
              "%s seed run (%s) failed: %s" % (tag, sc["seed"], (rep0 or {}).get("error")))
    rc, rep, proc, secs = run_build(cmd_prefix, srcm, extra_args, sc.get("env"),
                                    wipe=not sc.get("seed") and not sc.get("no_wipe"))
    if rep is None:
        raise Fail("%s no build_report.json produced (rc=%d)\n%s"
                   % (tag, rc, (proc.stderr or b"").decode("utf-8", "replace")[-800:]))
    err = rep.get("error") or ""
    check(rep["ok"] == sc["ok"],
          "%s expected ok=%s got ok=%s error=%s" % (tag, sc["ok"], rep["ok"], err))
    if sc["ok"]:
        check(rc == 0, "%s exit code %d" % (tag, rc))
        if sc.get("gates"):
            for g in ("A0", "A1", "A2", "A3", "A4", "A5", "A6", "A8") \
                    + tuple(sc.get("gates_extra") or ()):
                check(g in rep["gates"], "%s gate %s missing" % (tag, g))
                check(rep["gates"][g]["ok"], "%s gate %s FAILED: %s"
                      % (tag, g, rep["gates"][g]["detail"]))
        if sc.get("deployed") is not None:
            check(rep["deployed"] == sc["deployed"],
                  "%s deployed=%s expected %s" % (tag, rep["deployed"], sc["deployed"]))
        if sc.get("no_audio"):
            check(rep["gates"]["A1"]["detail"].startswith("skipped"),
                  "%s expected the audio gates to be skipped" % tag)
        if sc.get("combined"):
            check(len(rep.get("carried_materials") or []) > 0,
                  "%s expected carried materials from the previous build" % tag)
    else:
        check(rc != 0, "%s expected a non-zero exit code" % tag)
        check(sc["err_has"].lower() in err.lower(),
              "%s error does not mention %r: %s" % (tag, sc["err_has"], err[:400]))
    if sc.get("expect_keys"):
        got = [m["key"] for m in rep.get("materials", [])]
        for k in sc["expect_keys"]:
            check(k in got,
                  "%s expected the display name %r, the report only has %r"
                  % (tag, k, got))
    if sc.get("log_has"):
        log = load_log()
        check(sc["log_has"] in log, "%s log does not contain %r" % (tag, sc["log_has"]))
    if sc.get("needs_bundled"):
        log = load_log()
        want = os.path.join(os.path.dirname(cmd_prefix[0]), "kit", "ffmpeg", "ffmpeg.exe")
        line = [x for x in log.splitlines() if "ffmpeg        :" in x]
        check(want in log, "%s the bundled ffmpeg (%s) was not used; log says %s"
              % (tag, want, line[-1] if line else "<nothing>"))
    if sc.get("needs_kit_flag"):
        check(KIT_DIR in load_log(), "%s the -Kit override path never appeared in the log" % tag)

    extra = ""
    if sc.get("post") == "letterbox_centred":
        extra += letterbox_centred(tag)
    elif sc.get("post") == "mi_authored":
        extra += mi_authored(tag)
    elif sc.get("post") == "no_thumb":
        extra += no_thumb(tag)
    elif sc.get("post") == "atlas_one_tile":
        extra += atlas_one_tile(tag)
    elif sc.get("post") == "no_atlas":
        extra += no_atlas(tag)
    elif sc.get("post") == "combined_adds":
        extra += combined_adds(tag)
    if sc.get("rollback"):
        snap_before = state["patch_before"]
        for ext in ("pak", "ucas", "utoc"):
            live = os.path.join(PAKS, "%s.%s" % (PKG, ext))
            check(os.path.isfile(live), "%s %s not deployed" % (tag, ext))
            want = rep["container"]["files"][ext]["sha256"]
            got = sha256(live)
            check(got == want, "%s deployed %s %s != built %s" % (tag, ext, got[:16], want[:16]))
        ps = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                             "-File", os.path.join(OUT, "uninstall.ps1"), "-Paks", PAKS],
                            capture_output=True)
        check(ps.returncode == 0, "%s uninstall.ps1 rc=%d" % (tag, ps.returncode))
        after = patch_snapshot(PAKS)
        check(after == snap_before,
              "%s rollback did not restore the previous container\n  before=%s\n  after =%s"
              % (tag, {k: v[:12] for k, v in snap_before.items()},
                 {k: v[:12] for k, v in after.items()}))
        extra = " | rollback restored %d file(s)" % len(snap_before)

    check(rep["native_containers_untouched"] is not False,
          "%s native containers changed" % tag)
    if sc.get("sandbox_untouched"):
        after = patch_snapshot(PAKS)
        check(after == state["patch_before"],
              "%s the sandbox patch files were left modified: %s"
              % (tag, {k: v[:12] for k, v in after.items()}))
        extra += " | sandbox untouched"
    return "%s OK (%.1fs, %s)" % (tag, secs, rep["container"].get("base", "-")) + extra


def make_wav_quick(path: str, seconds: int, rate: int = 48000, ch: int = 2) -> None:
    """1 s of sine repeated N times -- instant, and the size/scale is what matters."""
    import math
    one = bytearray()
    for i in range(rate):
        v = int(12000 * math.sin(2 * math.pi * 220 * i / rate))
        for _c in range(ch):
            one += struct.pack("<h", v)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(one) * int(seconds))


def build_stress_material() -> str:
    """The stated acceptance limits: 50 backgrounds + 10 minutes of audio."""
    d = os.path.join(MAT, "stress")
    if os.path.isdir(d):
        shutil.rmtree(d)
    for i in range(1, 51):
        make_png(os.path.join(d, "bg", "bg_%03d.png" % i), 160, 90, i)
    make_wav_quick(os.path.join(d, "BGM", "song_a.wav"), 150)
    make_wav_quick(os.path.join(d, "BGM", "song_b.wav"), 150)
    make_wav_quick(os.path.join(d, "Sound", "sfx.wav"), 150, ch=1)
    make_wav_quick(os.path.join(d, "Ambient", "room.wav"), 150)
    return d


def _free_bytes(drive: str) -> int:
    import ctypes
    free = ctypes.c_ulonglong(0)
    ctypes.WinDLL("kernel32", use_last_error=True).GetDiskFreeSpaceExW(
        ctypes.c_wchar_p(drive), None, None, ctypes.byref(free))
    return free.value


def run_stress(cmd_prefix) -> int:
    d = build_stress_material()
    srcm_mb = sum(os.path.getsize(os.path.join(r, f))
                  for r, _dd, fs in os.walk(d) for f in fs) / 1e6
    drive = os.path.splitdrive(os.path.abspath(d))[0] + "\\"
    shutil.rmtree(OUT, ignore_errors=True)      # measure the build, not the leftovers
    free_before = _free_bytes(drive)
    print("stress material: 50 backgrounds + 600 s audio (%.1f MB on disk)" % srcm_mb)
    print("-" * 78)
    rc, rep, proc, secs = run_build(cmd_prefix, d, ["-DryRun"], None)
    if rep is None:
        print("FAIL no build_report.json (rc=%d)\n%s"
              % (rc, (proc.stderr or b"").decode("utf-8", "replace")[-1500:]))
        return 1
    bad = 0
    if not rep["ok"]:
        print("FAIL build failed: %s" % rep.get("error"))
        bad = 1
    for g in sorted(rep.get("gates", {})):
        v = rep["gates"][g]
        print("  gate %-3s %s  %s" % (g, "PASS" if v["ok"] else "FAIL", v["detail"][:110]))
        if not v["ok"]:
            bad = 1
    c = rep.get("container", {}) or {}
    files = c.get("files", {})
    total = sum(v["bytes"] for v in files.values())
    used_mb = (free_before - _free_bytes(drive)) / 1e6
    print("-" * 78)
    print("container   : chunks=%s packages=%s" % (c.get("chunks"), c.get("packages")))
    for e in ("pak", "ucas", "utoc"):
        if e in files:
            print("  .%-5s %12s  %s" % (e, "%.1f MB" % (files[e]["bytes"] / 1e6),
                                        files[e]["sha256"][:16].upper()))
    print("container total : %.1f MB" % (total / 1e6))
    print("PEAK DISK USED  : %.1f MB  (free-space delta; the work tree is the rest --" % used_mb)
    print("                  hardlinked native containers cost nothing)")
    print("elapsed         : %.1f s" % secs)
    print("da rows         : %s" % rep.get("da_counts"))
    print("materials       : %d" % len(rep.get("materials", [])))
    qual = [m["quality"].get("psnr_db") for m in rep.get("materials", [])
            if m["kind"] == "bg"]
    if qual:
        print("bg PSNR         : min=%s max=%s" % (min(qual, key=float), max(qual, key=float)))
    if bad:
        print("RESULT: FAILED")
        return 1
    print("RESULT: OK -- the stated limits pack successfully (peak disk %.1f MB)"
          % used_mb)
    return 0


def container_hashes(paks: str) -> dict:
    out = {}
    if not os.path.isdir(paks):
        return out
    for f in sorted(os.listdir(paks)):
        if f.endswith(('.utoc', '.ucas', '.pak')):
            out[f] = sha256(os.path.join(paks, f))
    return out


def replica_report(real_paks: str) -> str:
    """Is the sandbox a faithful copy of the real install?  Informational only:
    the sandbox exists precisely so we never have to write the real folder."""
    real = container_hashes(real_paks)
    sand = container_hashes(PAKS)
    miss = sorted(set(real) - set(sand))
    extra = sorted(set(sand) - set(real))
    diff = sorted(k for k in set(real) & set(sand) if real[k] != sand[k])
    if not (miss or extra or diff):
        return 'identical to the real game folder (%d container file(s))' % len(real)
    bits = []
    if miss:
        bits.append('missing ' + ', '.join(miss))
    if extra:
        bits.append('extra ' + ', '.join(extra))
    if diff:
        bits.append('differs ' + ', '.join(diff))
    return 'DRIFTED -- results may not represent the real install: ' + '; '.join(bits)


def main(argv=None) -> int:
    global EXE_OVERRIDE, KIT_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None, help="scenario ids, e.g. --only T1 T6")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--exe", default=None,
                    help="test a specific builder exe instead of the newest in dist/")
    ap.add_argument("--kit", default=None,
                    help="pass -Kit <dir> to every run (e.g. an experimental trimmed tool set)")
    ap.add_argument("--real-game", default=REAL_GAME_DEFAULT,
                    help="a real Paks folder to protect; skipped when it does not exist")
    ap.add_argument("--stress", action="store_true",
                    help="only run the limit-scale test (50 backgrounds + 10 min audio)")
    a = ap.parse_args(argv)
    EXE_OVERRIDE = a.exe
    KIT_DIR = os.path.abspath(a.kit) if a.kit else None

    if a.stress:
        cmd_prefix = find_exe(EXE_OVERRIDE)
        print("builder : %s" % " ".join(cmd_prefix))
        if KIT_DIR:
            print("kit     : %s" % KIT_DIR)
        print("sandbox : %s" % PAKS)
        real_before = patch_snapshot(a.real_game) if os.path.isdir(a.real_game) else None
        rc = run_stress(cmd_prefix)
        if real_before is not None and patch_snapshot(a.real_game) != real_before:
            print("FAIL THE REAL GAME FOLDER WAS MODIFIED")
            return 1
        return rc

    if a.list:
        for s in SCENARIOS:
            print("%-4s %s" % (s["id"], s["name"]))
        return 0

    cmd_prefix = find_exe(EXE_OVERRIDE)
    print("builder : %s" % " ".join(cmd_prefix))
    if KIT_DIR:
        print("kit     : %s" % KIT_DIR)
    if not os.path.isdir(PAKS):
        print("FATAL: sandbox game folder missing: %s" % PAKS)
        print("       build it with hardlinks to the native containers + a copy of the _P trio")
        return 2

    real_before = patch_snapshot(a.real_game) if os.path.isdir(a.real_game) else None
    if real_before is not None:
        print("real game folder guarded: %s (%d patch file(s))" % (a.real_game, len(real_before)))
        print('sandbox  : %s' % replica_report(a.real_game))

    state = {"mat": build_material(), "patch_before": patch_snapshot(PAKS)}
    print("material: %s" % MAT)
    print("sandbox : %s (%d patch file(s) before)" % (PAKS, len(state["patch_before"])))
    print("-" * 78)

    order = SCENARIOS
    if a.only:
        ids = {x.upper() for x in a.only}
        order = [s for s in SCENARIOS if s["id"] in ids]

    failed = 0
    t0 = time.time()
    for sc in order:
        try:
            print("PASS " + do_scenario(sc, cmd_prefix, state))
        except Fail as e:
            failed += 1
            print("FAIL " + str(e))
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("ERROR [%s] %s: %s" % (sc["id"], type(e).__name__, e))

    print("-" * 78)
    if patch_snapshot(PAKS) != state["patch_before"]:
        print("FAIL sandbox patch files were left modified")
        failed += 1
    if real_before is not None:
        if patch_snapshot(a.real_game) != real_before:
            print("FAIL THE REAL GAME FOLDER WAS MODIFIED")
            failed += 1
        else:
            print("PASS real game folder untouched")
    print("%d scenario(s), %d failure(s), %.1fs total" % (len(order), failed, time.time() - t0))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
