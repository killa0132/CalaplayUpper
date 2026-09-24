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
    make_png(os.path.join(d, "bg", "a.png"), 160, 90, 3)
    make_png(os.path.join(d, "bg", "b.png"), 90, 160, 4)            # portrait -> contain bars
    m["bgonly"] = d

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
    dict(id="T5", name="contain fit letterboxes", srcm="bgonly",
         args=["-DryRun", "-Fit", "contain"], ok=True, log_has="borders"),
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
]


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
            for g in ("A0", "A1", "A2", "A3", "A4", "A5", "A6"):
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
