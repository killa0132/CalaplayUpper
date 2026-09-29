# -*- coding: utf-8 -*-
"""合并产物的真机安装（`scripts/install_merged.ps1` 的 Python 孪生实现）。

为什么要有这个文件
------------------
合并模式现在是一条**完整流水线**：产出容器 → 备份现有 `_P` → 写入游戏
`Content\\Paks\\` → 逐文件读回 sha256 → 任一步不符就自动还原。GUI 的 Kit 里
**不带 `scripts/`**（只有一个 exe + `kit/`），所以那条 PowerShell 路子在打包后的
GUI 里叫不动；这个模块把同一套步骤用纯 Python 复刻出来，供 `gui/tasks.py` 在
合并成功后直接调用。

安全约定（和 `install_merged.ps1`、以及单包 L5 完全一致，一条都不能少）
----------------------------------------------------------------------
1. **只碰同名补丁容器** `CalaPlayer-Windows_P.{pak,ucas,utoc}`，原生容器与存档永远只读；
2. **写前备份**：把当前已装的 `_P` 三件套**移动**（不是删除）到
   `<输出目录>\\install_backup_<时间戳>\\real_P\\`，并写 `BACKUP.txt`（含新旧哈希、
   原生容器与 `Scenarios.sav` 的快照、照抄即可的回滚命令）；
3. **写后读回**：每个写入的文件都重新算 sha256 与源文件比对，长度也要一致；
4. **失败自动还原**：上面任何一步抛错，就先删掉我们刚写进去的三个文件、把备份移回来，
   再把错误抛给调用者 —— 游戏目录要么是"装好"，要么是"装之前"，没有中间态；
5. **占用防护**：容器被独占（游戏还在跑）时在**碰任何文件之前**就拒绝，并给中文提示。

注意：`core/merger.py` 依旧**从不安装**（协议里写着"只读 -Base、只写 -Out"），
安装这一步属于 GUI/CLI 的**调用方**，本模块只是被调用的原语。
"""
from __future__ import annotations

import os
import shutil
import time
from typing import Dict, List, Optional

from .common import BuildError, Log, ensure_dir, human, sha256_file

#: 补丁容器的基名与扩展名（`.pak` 只是个索引，三件套必须同进同出）
DEFAULT_BASE = "CalaPlayer-Windows_P"
EXTS = ("pak", "ucas", "utoc")
#: 原生容器的基名（快照用；从补丁基名去掉 `_P` 得到）
NATIVE_BASE = "CalaPlayer-Windows"


def sha16(path: str) -> str:
    """短哈希（前 16 位十六进制）——备份记录与日志里用它，够用且好读。"""
    return sha256_file(path)[:16]


def trios(directory: str, base: str = DEFAULT_BASE) -> Dict[str, str]:
    """`{ext: 绝对路径}`；文件可能不存在，由 `trio_exists()` 判断。"""
    return {e: os.path.join(directory, "%s.%s" % (base, e)) for e in EXTS}


def trio_exists(t: Dict[str, str]) -> bool:
    return all(os.path.isfile(p) for p in t.values())


def _looks_like_game_paks(paks: str) -> bool:
    """这个目录像不像游戏的 `Content\\Paks`？

    判据 = 至少有一个原生容器（`CalaPlayer-Windows.utoc`）。这条防的是"用户把
    输出目录填成合并基底"之类的低级错误：写进去会污染一个不相干的文件夹。
    """
    return os.path.isfile(os.path.join(paks, "%s.utoc" % NATIVE_BASE))


def _locked(path: str) -> bool:
    """文件被别的进程独占（= 游戏在跑）时为 True。只读探测，不写任何字节。"""
    if not os.path.isfile(path):
        return False
    try:
        fh = open(path, "r+b")
    except OSError:
        return True
    try:
        fh.close()
    except OSError:
        pass
    return False


def _snapshot(directory: str, skip_prefix: str) -> Dict[str, str]:
    """目录内（跳过 `skip_prefix` 开头的文件）的 `{文件名: sha16}` 快照。"""
    out: Dict[str, str] = {}
    if not os.path.isdir(directory):
        return out
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        if not os.path.isfile(full):
            continue
        if skip_prefix and name.startswith(skip_prefix):
            continue
        out[name] = sha16(full)
    return out


def _save_file(paks: str) -> str:
    """存档路径：`<游戏根>/Saved/SaveGames/Scenarios.sav`（不存在就当没有）。"""
    game_root = os.path.dirname(os.path.dirname(paks))       # .../CalaPlayer
    return os.path.join(game_root, "Saved", "SaveGames", "Scenarios.sav")


def _backup_dir(out_dir: str) -> str:
    """备份目录名：`<输出目录>\\install_backup_<yyyyMMdd_HHmmss>`（同秒重复就加后缀）。"""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    d = os.path.join(out_dir, "install_backup_%s" % stamp)
    n = 1
    while os.path.exists(d):
        n += 1
        d = os.path.join(out_dir, "install_backup_%s_%d" % (stamp, n))
    return d


def install(src_dir: str, paks_dir: str, base: str = DEFAULT_BASE,
            log: Optional[Log] = None, stage: str = "M7") -> Dict:
    """把 `src_dir` 里的补丁三件套装进 `paks_dir`（写前备份、写后读回、失败还原）。

    返回一份可以直接放进报告/界面显示的字典：装了什么（每个文件的哈希与体积）、
    备份在哪、原生容器与存档是否原样、以及照抄就能回滚的命令。
    """
    say = (log or (lambda *a, **k: None))

    src_dir = os.path.abspath(src_dir)
    paks_dir = os.path.abspath(paks_dir)
    new = trios(src_dir, base)
    live = trios(paks_dir, base)

    # ---------------- 写前自检（这一步失败时游戏目录一个字节都没动）----------------
    if not trio_exists(new):
        raise BuildError(stage, "输出目录里没有 %s.{pak,ucas,utoc}" % base, src_dir)
    if not os.path.isdir(paks_dir):
        raise BuildError(stage, "游戏 Paks 目录不存在", paks_dir)
    if not _looks_like_game_paks(paks_dir):
        raise BuildError(stage, "这个目录不像是游戏的 Paks 目录（没有 %s.utoc）" % NATIVE_BASE,
                         paks_dir)

    have_live = trio_exists(live)
    # 游戏占用防护：已装的 _P 或原生容器被独占 ⇒ 先拒绝，别去写
    for probe in ([live["ucas"]] if have_live else []) + \
                 [os.path.join(paks_dir, "%s.ucas" % NATIVE_BASE)]:
        if _locked(probe):
            raise BuildError(stage, "容器被占用（游戏还在跑？）—— 先关掉游戏再安装",
                             probe)

    # 备份跟着**输出目录**走（用户要求：`<输出目录>\install_backup_<时间戳>\`）
    backup = _backup_dir(src_dir)
    real_p = ensure_dir(os.path.join(backup, "real_P"))
    sav = _save_file(paks_dir)

    new_h = {e: {"path": new[e], "sha16": sha16(new[e]),
                 "sha256": sha256_file(new[e]), "bytes": os.path.getsize(new[e])}
             for e in EXTS}
    say(stage, "部署：把补丁容器装进 %s" % paks_dir)
    say(stage, "  备份目录 : %s" % backup)
    if have_live:
        for e in EXTS:
            say(stage, "  移开现有 %s.%s  %s" % (base, e, sha16(live[e])))
    else:
        say(stage, "  当前没有已装的补丁容器，无需移开")
    for e in EXTS:
        say(stage, "  写入     %s.%s  %s  %s" % (base, e, new_h[e]["sha16"],
                                                human(new_h[e]["bytes"])))

    natives_before = _snapshot(paks_dir, base + ".")
    sav_before = sha16(sav) if os.path.isfile(sav) else "n/a"

    moved = False
    try:
        if have_live:
            for e in EXTS:
                shutil.move(live[e], os.path.join(real_p, "%s.%s" % (base, e)))
            moved = True
        for e in EXTS:
            shutil.copy2(new[e], live[e])
        # 写后读回：哈希与体积都要对上
        for e in EXTS:
            got, want = sha16(live[e]), new_h[e]["sha16"]
            if got != want:
                raise BuildError(stage, "读回不一致 .%s：装进去的是 %s，构建产物是 %s"
                                 % (e, got, want))
            if os.path.getsize(live[e]) != new_h[e]["bytes"]:
                raise BuildError(stage, "读回体积不一致 .%s" % e)
        # 原生容器与存档必须原样（只追加、零污染的红线）
        natives_after = _snapshot(paks_dir, base + ".")
        if natives_after != natives_before:
            raise BuildError(stage, "原生容器被改动了（这是红线）",
                             "%s -> %s" % (natives_before, natives_after))
        if sav_before != "n/a":
            if not os.path.isfile(sav):
                raise BuildError(stage, "存档文件不见了", sav)
            if sha16(sav) != sav_before:
                raise BuildError(stage, "Scenarios.sav 被改动了", sav)
    except BaseException as exc:                       # noqa: BLE001 —— 失败必须还原
        say(stage, "安装失败：%s" % exc)
        say(stage, "自动还原：把游戏目录恢复到安装前的状态")
        for e in EXTS:
            if os.path.isfile(live[e]):
                os.remove(live[e])
        if moved:
            for e in EXTS:
                src = os.path.join(real_p, "%s.%s" % (base, e))
                if os.path.isfile(src):
                    shutil.move(src, live[e])
        restored = (not have_live and not trio_exists(live)) or \
            (have_live and all(sha16(live[e]) == sha16(os.path.join(
                real_p, "%s.%s" % (base, e))) for e in EXTS))
        say(stage, "还原完成：%s" % ("游戏目录已回到安装前" if restored else "还原可能不完整！"))
        raise

    info = {
        "target": paks_dir,
        "backup": backup,
        "backup_real_p": real_p,
        "backup_txt": os.path.join(backup, "BACKUP.txt"),
        "installed": {e: {"sha16": sha16(live[e]), "sha256": new_h[e]["sha256"],
                          "bytes": new_h[e]["bytes"]} for e in EXTS},
        "replaced": ({e: sha16(os.path.join(real_p, "%s.%s" % (base, e))) for e in EXTS}
                     if moved else {}),
        "natives_unchanged": True,
        "save_unchanged": (sav_before == "n/a" or sha16(sav) == sav_before),
        "save_file": sav if sav_before != "n/a" else "",
        "rollback_cmd": ("powershell -NoProfile -ExecutionPolicy Bypass -File "
                         ".\\scripts\\install_merged.ps1 -Src \"%s\" -Paks \"%s\" "
                         "-Backup \"%s\" -Rollback" % (src_dir, paks_dir, backup)),
        "base": base,
    }
    _write_backup_txt(info, natives_before, sav_before)
    say(stage, "装好了：%s" % ", ".join("%s.%s=%s" % (base, e, info["installed"][e]["sha16"])
                                        for e in EXTS))
    say(stage, "  游戏目录 : %s（原生容器与存档未变）" % paks_dir)
    say(stage, "  回滚记录 : %s" % info["backup_txt"])
    return info


def _write_backup_txt(info: Dict, natives: Dict[str, str], sav_before: str) -> None:
    """写 `BACKUP.txt`：人类可读的账本 + 照抄即可的回滚命令。"""
    base = info.get("base") or DEFAULT_BASE
    lines: List[str] = [
        "CalaPlayer 合并容器安装记录",
        "时间        : %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
        "游戏 Paks   : %s" % info["target"],
        "",
        "本次装进去的容器:",
    ]
    for e in EXTS:
        v = info["installed"][e]
        lines.append("  %s.%s  %s  %s B" % (base, e, v["sha16"], v["bytes"]))
    lines += ["", "被替换掉的容器（在 real_P\\ 里，用 -Rollback 还原）:"]
    if info.get("replaced"):
        for e in EXTS:
            p = os.path.join(info["backup_real_p"], "%s.%s" % (base, e))
            if os.path.isfile(p):
                lines.append("  %s.%s  %s  %s B" % (base, e, sha16(p), os.path.getsize(p)))
    else:
        lines.append("  （安装前没有任何补丁容器）")
    lines += ["", "原生容器（未改动）:"]
    for k in sorted(natives):
        lines.append("  %s  %s" % (k, natives[k]))
    lines += ["", "Scenarios.sav: %s（未改动）" % sav_before]
    lines += ["", "回滚:", "  %s" % info.get("rollback_cmd", "")]
    try:
        with open(info["backup_txt"], "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        pass


def rollback(backup: str, paks_dir: str, base: str = DEFAULT_BASE,
             log: Optional[Log] = None, stage: str = "M7") -> Dict:
    """把 `backup\\real_P\\` 里的容器放回去（= 回到安装前那一次的状态）。"""
    say = (log or (lambda *a, **k: None))
    real_p = os.path.join(backup, "real_P")
    paks_dir = os.path.abspath(paks_dir)
    # 安全网（CP-41b）：回滚目标必须是**游戏的 Paks 目录**，否则宁可不做 ——
    # 之前如果把游戏根目录当目标传进来，会往那里复制出一堆同名容器垃圾。
    if not _looks_like_game_paks(paks_dir):
        raise BuildError(stage, "回滚目标不像是游戏的 Paks 目录（没有 %s.utoc）" % NATIVE_BASE,
                         paks_dir)
    live = trios(paks_dir, base)
    bak = trios(real_p, base)
    if not trio_exists(bak):
        # 安装前这个目录里**本来就没有**补丁容器（用户的游戏是干净的）⇒ "回滚"就是把我们
        # 装进去的那份删掉、回到干净状态。旧代码在这里直接报"备份目录里没有三件套"，于是
        # 干净机器上**装完就再也回不去了**（2026-09-29 沙箱重新对齐到"无补丁"后 G4 抓到）。
        removed = []
        for e in EXTS:
            if os.path.isfile(live[e]):
                os.remove(live[e])
                removed.append("%s.%s" % (base, e))
        info = {"ok": True, "target": paks_dir, "from": real_p, "restored": {},
                "clean": True, "removed": removed}
        say(stage, "回滚完成：安装前这里没有任何补丁容器 ⇒ 已删掉我们装进去的 %s，"
                   "游戏目录回到干净状态" % (", ".join(removed) if removed else "（本来就没有）"))
        return info
    say(stage, "回滚：还原 %s 里的容器" % real_p)
    for e in EXTS:
        if os.path.isfile(live[e]):
            os.remove(live[e])
        shutil.copy2(bak[e], live[e])
    for e in EXTS:
        if sha16(live[e]) != sha16(bak[e]):
            raise BuildError(stage, "回滚后读回不一致 .%s" % e)
    info = {"ok": True, "target": paks_dir, "from": real_p,
            "restored": {e: sha16(live[e]) for e in EXTS}}
    say(stage, "回滚完成：%s" % ", ".join("%s.%s=%s" % (base, e, info["restored"][e])
                                          for e in EXTS))
    return info


def rollback_command(info: Dict) -> str:
    """给界面显示用的一行回滚命令（缺字段时给空串）。"""
    return info.get("rollback_cmd", "") if info else ""
