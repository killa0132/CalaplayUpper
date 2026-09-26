# -*- coding: utf-8 -*-
"""CalaPlayerSrcmBuilder -- command line entry point.

    build_srcm.ps1 -Paks <game Paks dir> -Srcm <material root>
                   [-Fit cover|contain] [-Force] [-DryRun] [-Combined]
                   [-Ffmpeg <ffmpeg.exe>] [-Kit <dir>] [-NoDeploy] [-KeepWork]
                   [-NoThumb] [-NoAtlas]

Exit codes: 0 = ok, 2 = bad arguments, 3 = build failed (see build.log).
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import common  # noqa: E402
from core.builder import TOOL_VERSION, Ctx, Builder  # noqa: E402
from core.common import BuildError, Log, reconfigure_stdio  # noqa: E402

BANNER = r"""
  ____      _        ____  _                    _   _   _
 / ___|__ _| | __ _ |  _ \| | __ _ _   _  ___  | | | | | |_ __   ___ _ __
| |   / _` | |/ _` || |_) | |/ _` | | | |/ _ \ | | | | | | '_ \ / _ \ '__|
| |__| (_| | | (_| ||  __/| | (_| | |_| |  __/ | |_| |_| | |_) |  __/ |
 \____\__,_|_|\__,_||_|   |_|\__,_|\__, |\___|  \___/(_)\___/| .__/ \___|_|
                                   |___/                     |_|
   CalaPlayerSrcmBuilder %s   static _P patch generator
""" % TOOL_VERSION


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="build_srcm", add_help=True,
        description="Build a static CalaPlayer _P patch from a srcm material folder.")
    p.add_argument("-Paks", "--paks", required=True, metavar="DIR",
                   help="game root, UE project root, Content dir or the Paks dir itself")
    p.add_argument("-Srcm", "--srcm", required=True, metavar="DIR",
                   help="material root containing bg/ BGM/ Sound/ Ambient/")
    p.add_argument("-Fit", "--fit", default="cover", choices=("cover", "contain"),
                   help="background fit: cover (fill + centre crop) or contain (letterbox)")
    p.add_argument("-Force", "--force", action="store_true",
                   help="override the material count / duration / quality limits")
    p.add_argument("-DryRun", "--dry-run", action="store_true",
                   help="run L0..L4 only and never touch the game folder")
    p.add_argument("-NoDeploy", "--no-deploy", action="store_true",
                   help="same effect as -DryRun (kept for compatibility)")
    p.add_argument("-Combined", "--combined", action="store_true",
                   help="accumulate on top of the previous out_patch build instead of "
                        "rebuilding from the native tables only")
    p.add_argument("-Ffmpeg", "--ffmpeg", default=None, metavar="EXE",
                   help="explicit path to ffmpeg.exe")
    p.add_argument("-Kit", "--kit", default=None, metavar="DIR",
                   help="folder holding retoc / da-patch / tex-inspect / mappings")
    p.add_argument("-KeepWork", "--keep-work", action="store_true",
                   help="keep the previous build tree for debugging")
    p.add_argument("-NoThumb", "--no-thumb", action="store_true",
                   help="do NOT author the preview material instances (each new background "
                        "row then keeps the clone source's @30, i.e. the in-game thumbnail "
                        "stays the native tile, exactly like v1). Diagnostic switch: the "
                        "default authors one MI per background so the thumbnail is correct.")
    p.add_argument("-NoAtlas", "--no-atlas", action="store_true",
                   help="do NOT append the preview atlas: keep the CP-36 whole-image preview MI "
                        "(SourceTexture = our 2K texture, sprite = the whole frame). The dropdown "
                        "chip stays 2K, but the timeline cell and the side preview show native "
                        "atlas tile 0,0 again. Diagnostic switch: the default gives every "
                        "background its own cell on the game's own preview grid.")
    p.add_argument("-Log", "--log", default=None, metavar="FILE",
                   help="log file path (default: <srcm parent>\\build.log)")
    p.add_argument("-Quiet", "--quiet", action="store_true", help="do not echo the log")
    p.add_argument("-Version", "--version", action="version", version=TOOL_VERSION)
    return p.parse_args(argv)


def main(argv=None) -> int:
    reconfigure_stdio()
    print(BANNER)
    a = parse_args(argv)

    srcm = os.path.abspath(a.srcm)
    log_path = a.log or os.path.join(os.path.dirname(srcm), "build.log")
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)

    ctx = Ctx(paks_arg=a.paks, srcm_arg=srcm, fit=a.fit, force=a.force,
              dry_run=bool(a.dry_run or a.no_deploy), combined=a.combined,
              ffmpeg=a.ffmpeg, kit_dir=a.kit, keep_work=a.keep_work,
              no_thumb=bool(a.no_thumb), no_atlas=bool(a.no_atlas))
    log = Log(path=log_path, echo=not a.quiet)
    b = Builder(ctx, log)
    ok = False
    try:
        rep = b.run()
        ok = True
    except BuildError as e:
        rep = b.report(False, str(e))
    except Exception as e:  # noqa: BLE001
        log("ERR", "unexpected %s: %s" % (type(e).__name__, e))
        log.raw(traceback.format_exc())
        rep = b.report(False, "%s: %s" % (type(e).__name__, e))
    finally:
        log.close()

    # machine readable report, next to build.log and inside out_patch
    import json
    for path in {os.path.splitext(log_path)[0] + ".report.json",
                 os.path.join(ctx.out_patch, "build_report.json")} if ctx.out_patch else set():
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rep, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    print("")
    print("=" * 78)
    if ok:
        print("  RESULT: OK")
        print("  container : %s" % rep["container"].get("base"))
        print("  output    : %s" % ctx.out_patch)
        print("  deployed  : %s" % ("YES (game folder updated)" if rep["deployed"]
                                    else "NO (dry run)"))
        for g, v in sorted(rep["gates"].items()):
            print("  gate %-3s : %s" % (g, "PASS" if v["ok"] else "FAIL"))
    else:
        print("  RESULT: FAILED")
        print("  reason    : %s" % rep.get("error"))
        print("  the game folder was NOT left in a modified state:")
        print("            %s" % rep.get("rollback", {}).get("result", "nothing was written"))
        print("  log       : %s" % log_path)
    print("=" * 78)
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
