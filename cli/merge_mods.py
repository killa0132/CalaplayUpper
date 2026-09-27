# -*- coding: utf-8 -*-
"""CLI: merge several independent mods into ONE `_P` patch (PoC).

    python cli\\merge_mods.py -Mods <mods dir> -Base <clean game Paks> -Out <out dir>
    python cli\\merge_mods.py -Mods mods -Base "%GAME%\\CalaPlayer\\Content\\Paks" -Out out_merged
    python cli\\merge_mods.py -Mods mods -Base "<paks>" -Out out_merged -Select CalaplayUpper

Exit codes: 0 = merged, 2 = bad arguments, 3 = merge failed (conflicts / a gate failed).

The heavy lifting lives in `core/merger.py` (the GUI reuses `merge_mods()` directly).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.common import Log, reconfigure_stdio          # noqa: E402
from core.kit import load_kit                           # noqa: E402
from core.merger import merge_mods, tool_version        # noqa: E402

BANNER = r"""
  __  __           _        __  __           _
 |  \/  | ___   __| |      |  \/  | ___   __| |___
 | |\/| |/ _ \ / _` |      | |\/| |/ _ \ / _` / __|
 | |  | | (_) | (_| |      | |  | | (_) | (_| \__ \
 |_|  |_|\___/ \__,_|      |_|  |_|\___/ \__,_|___/
   CalaPlayer mod merger -- merge several mods into one _P patch
"""


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="merge_mods",
        description="Merge independent CalaPlayer mods (DA row edits + legacy asset files) "
                    "into one _P patch container.")
    p.add_argument("-Mods", "--mods", required=False,
                   help="folder holding the index manifest (manifest.json)")
    p.add_argument("-Base", "--base", required=False,
                   help="the CLEAN game Paks folder (read only; an installed _P is ignored)")
    p.add_argument("-Out", "--out", required=False,
                   help="output folder: the merged _P.{pak,ucas,utoc} + merge_report.json")
    p.add_argument("-Select", "--select", nargs="*", default=None,
                   help="only merge these mod names (default: every mod in the index)")
    p.add_argument("-Kit", "--kit", default=None, help="folder with retoc / da-patch / mappings")
    p.add_argument("-KeepWork", "--keep-work", action="store_true",
                   help="keep the merge scratch tree for debugging")
    p.add_argument("-Log", "--log", default=None, help="log file (default <out>/merge.log)")
    p.add_argument("-Quiet", "--quiet", action="store_true", help="do not echo log lines")
    p.add_argument("-Version", "--version", action="store_true", help="print the tool version")
    return p.parse_args(argv)


def main(argv=None) -> int:
    reconfigure_stdio()
    print(BANNER)
    a = parse_args(argv)
    if a.version:
        print("CalaPlayerModMerger %s" % tool_version())
        return 0
    for req in ("mods", "base", "out"):
        if not getattr(a, req):
            print("ERROR: -%s is required (see --help)" % req.capitalize())
            return 2

    out_dir = os.path.abspath(a.out)
    os.makedirs(out_dir, exist_ok=True)
    log_path = a.log or os.path.join(out_dir, "merge.log")
    log = Log(path=log_path, echo=not a.quiet)
    print("CalaPlayerModMerger %s" % tool_version())
    print("  mods : %s" % os.path.abspath(a.mods))
    print("  base : %s" % os.path.abspath(a.base))
    print("  out  : %s" % out_dir)
    rep = None
    try:
        kit = load_kit(a.kit, None, log, "M0")
        rep = merge_mods(a.mods, a.base, out_dir, a.select, log=log, kit=kit,
                         keep_work=a.keep_work)
    except Exception as e:  # noqa: BLE001 - always leave a report behind
        log("ERR", "unexpected %s: %s" % (type(e).__name__, e))
        log.raw(traceback.format_exc())
        from core.merger import MergeReport
        rep = MergeReport(ok=False, error="%s: %s" % (type(e).__name__, e),
                          version=tool_version(), out_dir=out_dir)
    finally:
        log.close()

    rep_path = os.path.join(out_dir, "merge_report.json")
    try:
        with open(rep_path, "w", encoding="utf-8") as f:
            json.dump(rep.to_dict(), f, indent=2, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        print("WARN: could not write %s (%s)" % (rep_path, e))

    print("")
    print("=" * 78)
    if rep.ok:
        print("  RESULT: OK")
        print("  container : %s" % rep.container.get("base"))
        for ext in ("pak", "ucas", "utoc"):
            f = (rep.container.get("files") or {}).get(ext)
            if f:
                print("    .%-5s %12d B  %s" % (ext, f["bytes"], f["sha16"]))
        print("  output    : %s" % out_dir)
        print("  mods      : %s" % ", ".join(m["name"] for m in rep.mods))
        for t in sorted(rep.tables):
            v = rep.tables[t]
            print("  table %-14s %d -> %d rows (+%d/-%d/~%d)"
                  % (t, v["native"], v["final"], v["appended"], v["deleted"], v["modified"]))
        print("  files     : %d" % len(rep.files))
        for g, v in sorted(rep.gates.items()):
            print("  gate %-3s : %s" % (g, "PASS" if v["ok"] else "FAIL"))
    else:
        print("  RESULT: FAILED")
        print("  reason    : %s" % rep.error)
        if rep.conflicts:
            print("  conflicts :")
            for c in rep.conflicts:
                print("            - %s" % c)
        print("  no container was produced; the game folder was not touched")
    print("  report    : %s" % rep_path)
    print("  log       : %s" % log_path)
    print("=" * 78)
    return 0 if rep.ok else 3


if __name__ == "__main__":
    sys.exit(main())
