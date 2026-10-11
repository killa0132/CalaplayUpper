# -*- coding: utf-8 -*-
"""添加角色模型 —— 命令行入口。

    import_character.py -Paks <game Paks dir> -Skin <exported skin folder>
                        [-Character <name>] [-SkinId S052] [-Source S001]
                        [-Out <output dir>] [-Kit <dir>]
                        [-DryRun] [-NoDeploy] [-KeepWork] [-Log <file>] [-Quiet]

`-Skin` 指向一套导出的皮肤素材（如
`E:\\Calabiyau\\Export\\PaperMan\\SkinAssets\\Characters\\Aika\\S051`，
会优先用里面的 `Mesh3D/` 子目录），工具会：

    C1 提取该角色的基线资产 + DA_Characters
    C2 把素材 PNG 匹配到源皮肤贴图，选出需要重建的材质
    C3 构建新皮肤资产（纯同长字节替换 + ubulk 重编码）
    C4 往 DA_Characters 注册新皮肤条目
    C5 打包 `_P2`（新皮肤）与 `_P`（替换 DA chunk）
    C6 安装进游戏（备份 / 读回 / 失败还原）

Exit codes: 0 = ok, 2 = bad arguments, 3 = build failed (see the log).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.character import CharCtx, CharacterBuilder  # noqa: E402
from core.common import BuildError, Log, reconfigure_stdio  # noqa: E402

TOOL_VERSION = "1.0.0"


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="import_character", add_help=True,
        description="Import an exported character skin (materials/textures) into "
                    "CalaPlayer as a brand-new skin.")
    p.add_argument("-Paks", "--paks", required=True, metavar="DIR",
                   help="game root, UE project root, Content dir or the Paks dir itself")
    p.add_argument("-Skin", "--skin", required=True, metavar="DIR",
                   help="the exported skin folder (e.g. ...\\Characters\\Aika\\S051); "
                        "its Mesh3D/ subfolder is used when present")
    p.add_argument("-Character", "--character", default="", metavar="NAME",
                   help="character name (default: inferred from the skin folder path)")
    p.add_argument("-SkinId", "--skin-id", default="", metavar="S###",
                   help="the new skin id, S + 3 digits (default: the lowest free one)")
    p.add_argument("-Source", "--source-skin", default="S001", metavar="S###",
                   help="the source skin the new one is cloned from (default S001)")
    p.add_argument("-Out", "--out", default="", metavar="DIR",
                   help="output folder (default: <skin folder>\\out_character)")
    p.add_argument("-Kit", "--kit", default=None, metavar="DIR",
                   help="folder holding retoc / da-patch / tex-inspect / mappings")
    p.add_argument("-DryRun", "--dry-run", action="store_true",
                   help="build everything but never touch the game folder")
    p.add_argument("-NoDeploy", "--no-deploy", action="store_true",
                   help="same effect as -DryRun (kept for compatibility)")
    p.add_argument("-KeepWork", "--keep-work", action="store_true",
                   help="keep the work tree after a successful deploy")
    p.add_argument("-Log", "--log", default=None, metavar="FILE",
                   help="log file path (default: <out>\\import_character.log)")
    p.add_argument("-Quiet", "--quiet", action="store_true", help="do not echo the log")
    p.add_argument("-Version", "--version", action="version", version=TOOL_VERSION)
    return p.parse_args(argv)


def main(argv=None) -> int:
    reconfigure_stdio()
    a = parse_args(argv)

    skin = os.path.abspath(a.skin)
    out_dir = os.path.abspath(a.out or os.path.join(os.path.dirname(skin), "out_character"))
    log_path = a.log or os.path.join(out_dir, "import_character.log")
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)

    ctx = CharCtx(paks_arg=a.paks, src_dir=skin, out_dir=out_dir,
                  character=a.character, skin_id=a.skin_id, source_skin=a.source_skin,
                  kit_arg=a.kit or "", dry_run=bool(a.dry_run or a.no_deploy),
                  no_deploy=bool(a.dry_run or a.no_deploy), keep_work=a.keep_work)
    log = Log(path=log_path, echo=not a.quiet)
    b = CharacterBuilder(ctx, log)
    rep, ok = {}, False
    try:
        rep = b.run()
        ok = True
    except BuildError as e:
        rep = {"ok": False, "error": str(e), "gates": b.gates}
    except Exception as e:  # noqa: BLE001
        log("ERR", "unexpected %s: %s" % (type(e).__name__, e))
        log.raw(traceback.format_exc())
        rep = {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "gates": b.gates}
    finally:
        log.close()

    with open(os.path.splitext(log_path)[0] + ".report.json", "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)

    print("")
    print("=" * 78)
    if ok:
        print("  RESULT: OK")
        print("  character : %s" % rep.get("character"))
        print("  skin      : %s (from %s)" % (rep.get("skin"), rep.get("source_skin")))
        print("  mesh      : %s" % rep.get("mesh"))
        print("  _P  dir   : %s" % rep.get("p_out"))
        print("  _P2 dir   : %s" % rep.get("p2_out"))
        print("  deployed  : %s" % ("YES (game folder updated)"
                                    if rep.get("installed") else "NO (dry run / no-deploy)"))
        for g in rep.get("gates", []):
            print("  gate %-4s : %s  %s" % (g["id"], "PASS" if g["ok"] else "FAIL",
                                            g.get("detail", "")))
        if rep.get("installed"):
            print("  rollback  : %s" % rep["installed"]["p"].get("backup_txt"))
    else:
        print("  RESULT: FAILED")
        print("  reason    : %s" % rep.get("error"))
        print("  log       : %s" % log_path)
    print("=" * 78)
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
