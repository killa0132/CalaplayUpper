# -*- coding: utf-8 -*-
"""运行时实测「游戏自己的预览图集占了哪些格」。

为什么必须实测
--------------
``config.ATLAS_FIRST_CELL`` / ``atlas.NATIVE_CELLS`` 曾经是**某一版游戏**的实测常数
（0..164 被占用 ⇒ 空位 165..223 = 59 格）。2026-09-29 用户重装游戏后，原生图集第 165 格
已经被游戏自己占用（首个空闲变成 166、空位只剩 58）——常数当场过期，而"往原生已占用的
格子里写"会覆盖游戏自己的缩略图（违反零污染红线），且 A9b 只查 0..164 时还拦不住。

权威来源 = **游戏自己的 ``DA_Backgrounds`` 每一行的 ``@30`` 指向的预览 MI 里的
``SpriteX/SpriteY``**：DA 行 34 B，``@30`` 是 ImportMap 里那条 ``MaterialInstanceConstant``
的 FPackageIndex，MI 的 6 个标量给出它落在图集的哪一格。

⚠️ 逐格扫像素（"黑格 = 空闲"）**不能**当权威：本轮实测 167 行只数出 166 个非黑格，而游戏
作者明确说过"黑色背景的预览和图集底色是融在一起的"（``0mui29ir2``）。少算一格就可能悄悄
覆盖原生缩略图。

成本与缓存
----------
167 个 MI 逐个 ``da-patch miprobe``：串行约 47 s，16 线程并行约 8 s（实测）。占用集合只跟
**原生容器**有关，所以按原生指纹缓存（``config.cache_dir()``，``CALA_CACHE_DIR`` 可覆盖，
自检/回归指向替身目录）。游戏没更新 ⇒ 缓存命中 ⇒ 0 成本；更新了 ⇒ 指纹变 ⇒ 自动重测。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Tuple

from . import config
from .common import BuildError, Log, ensure_dir
from .da import parse_imports

CACHE_NAME = "atlas_cells.json"
SCALAR_RE = re.compile(r"^MIPROBE scalar name=(\S+) value=(\S+)$")
ROW_BASE, ROW_STRIDE, AT30 = 12, 34, 30     # DA_Backgrounds.uexp: 行 i 的 @30
PROBE_JOBS = 16                             # 16 线程把 167 个 MI 从 47 s 压到 ~6 s（实测）


def _fingerprint(native_paks: str, da_uexp: str) -> str:
    """原生指纹：所有原生 .utoc + 原生 DA_Backgrounds.uexp 的 sha256。

    .utoc 是容器的目录索引（游戏一更新它就变），DA 的 uexp 决定行数与 @30 —— 两者一起
    就足以判断"这份占用集合还算不算数"。
    """
    h = hashlib.sha256()
    for f in sorted(os.listdir(native_paks)):
        if f.lower().endswith(".utoc"):
            h.update(f.encode("utf-8"))
            with open(os.path.join(native_paks, f), "rb") as fh:
                h.update(fh.read())
    with open(da_uexp, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def read_row_refs(da_uexp: str) -> List[int]:
    """DA_Backgrounds 每一行的 `@30`（FPackageIndex；0 = 这一行没有预览 MI）。"""
    b = open(da_uexp, "rb").read()
    n = struct.unpack_from("<I", b, 8)[0]
    return [struct.unpack_from("<i", b, ROW_BASE + i * ROW_STRIDE + AT30)[0] for i in range(n)]


def _resolve_mis(kit, da_ua: str, refs: List[int], log: Log, stage: str) -> List[Tuple[str, str]]:
    """每行 `@30` -> (MI 对象名, MI 包路径)。解析不出来一律**失败**，绝不猜。"""
    imp = parse_imports(kit.da(["imports", da_ua, kit.usmap], log, stage).out)
    out: List[Tuple[str, str]] = []
    for r in refs:
        if r == 0:
            out.append(("", ""))            # 这一行没有预览 MI（null），占不了格子
            continue
        if r > 0:
            raise BuildError(stage, "DA_Backgrounds 的某一行 @30=%d 指向本包的 export，"
                                    "不是原生预览 MI —— 拒绝猜它落在哪一格" % r)
        i = -r - 1
        if not (0 <= i < len(imp)):
            raise BuildError(stage, "DA 行 @30=%d 越出 ImportMap（共 %d 条）" % (r, len(imp)))
        cls, obj, outer = imp[i][2], imp[i][3], imp[i][4]
        if cls != "MaterialInstanceConstant":
            raise BuildError(stage, "DA 行 @30=%d 指向 %s（%s），不是预览 MI" % (r, cls, obj))
        j = -outer - 1
        if not (0 <= j < len(imp)):
            raise BuildError(stage, "预览 MI %s 没有包 import（outer=%d）" % (obj, outer))
        out.append((obj, imp[j][3]))
    return out


def _walk_assets(root: str) -> Dict[str, str]:
    """抽取目录 -> {对象名: .uasset 绝对路径}。"""
    found: Dict[str, str] = {}
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if f.lower().endswith(".uasset"):
                found.setdefault(os.path.splitext(f)[0], os.path.join(dirpath, f))
    return found


def _probe_one(kit, ua: str, usmap: str) -> Tuple[bool, Dict[str, float], str]:
    """一个 MI 的渲染真值（只取两个格坐标标量）。

    `usmap` 必须是**这个线程独占**的一份副本：UAssetAPI 是用独占方式打开 usmap 的
    （`File.Open(path, FileMode.Open)` → `FileShare.None`），多进程共享同一个文件会
    随机 `IOException`（实测 16 并发时 167 个里挂 21 个，换成各自副本后 167/167 全过）。
    """
    try:
        r = subprocess.run([kit.da_patch, "miprobe", ua, usmap],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=300)
    except Exception as e:  # noqa: BLE001
        return False, {}, "%s: %s" % (type(e).__name__, e)
    if not r.stdout or "MIPROBE_OK" not in r.stdout:
        return False, {}, (r.stderr or r.stdout or "<no output>").strip()[-300:]
    sc: Dict[str, float] = {}
    for line in r.stdout.splitlines():
        m = SCALAR_RE.match(line.strip())
        if m:
            try:
                sc[m.group(1)] = float(m.group(2))
            except ValueError:
                pass
    return True, sc, ""


_TLS = threading.local()


def _usmap_for(kit, copies_dir: str) -> str:
    """本线程自己的 usmap 副本（懒创建；线程复用同一份）。"""
    p = getattr(_TLS, "usmap", None)
    if p:
        return p
    n = getattr(_TLS, "n", None)
    if n is None:
        with _COUNT_LOCK:
            _COUNT[0] += 1
            n = _COUNT[0]
        _TLS.n = n
    p = os.path.join(copies_dir, "usmap_%02d.usmap" % n)
    if not os.path.isfile(p):
        shutil.copyfile(kit.usmap, p)
    _TLS.usmap = p
    return p


_COUNT = [0]
_COUNT_LOCK = threading.Lock()


def measure(kit, native_paks: str, da_ua: str, work_dir: str, log: Log,
            stage: str = "L0") -> Dict:
    """实测原生预览图集的占用集合（带指纹缓存）。返回 dict，字段见文件头注释。"""
    da_uexp = os.path.splitext(da_ua)[0] + ".uexp"
    if not os.path.isfile(da_uexp):
        raise BuildError(stage, "原生 DA_Backgrounds 没有 .uexp，无法实测图集占用", da_uexp)
    fp = _fingerprint(native_paks, da_uexp)
    cache = os.path.join(config.cache_dir(), CACHE_NAME)

    if os.path.isfile(cache):
        try:
            with open(cache, encoding="utf-8") as fh:
                blob = json.load(fh)
            if blob.get("fingerprint") == fp and blob.get("occupied"):
                occ = {int(k): str(v) for k, v in blob["occupied"].items()}
                log(stage, "原生预览图集占用：%d 格（首个空闲 %d，空位 %d）[缓存命中 %s]"
                    % (len(occ), blob["first_free"], config.ATLAS_SLOTS - len(occ), fp[:16]))
                return {"occupied": occ, "first_free": int(blob["first_free"]),
                        "slots": config.ATLAS_SLOTS, "rows": int(blob.get("rows", 0)),
                        "source": "cache", "fingerprint": fp}
        except Exception as e:  # noqa: BLE001
            log(stage, "WARN: 图集占用缓存读不动（%s），改为重新实测" % e)

    t0 = time.time()
    refs = read_row_refs(da_uexp)
    pairs = _resolve_mis(kit, da_ua, refs, log, stage)
    uniq = sorted({o for o, _p in pairs if o})
    if not uniq:
        raise BuildError(stage, "原生 DA_Backgrounds 的 %d 行里没有一个预览 MI" % len(refs))

    # 只抽这些 MI 所在的目录（一次 retoc 调用；实测 167 个包 0.11 s）
    folder = pairs[[o for o, _p in pairs if o].index(uniq[0])][1].rsplit("/", 1)[0]
    filt = "/".join(folder.split("/")[-2:])
    mi_dir = os.path.join(work_dir, "native_raw", "mi_cells")
    if os.path.isdir(mi_dir):
        shutil.rmtree(mi_dir, ignore_errors=True)
    kit.to_legacy(native_paks, mi_dir, filt, log, stage)
    have = _walk_assets(mi_dir)

    missing = [o for o in uniq if o not in have]
    if missing:
        raise BuildError(stage, "%d 个原生预览 MI 没抽出来（%s）—— 无法实测图集占用"
                         % (len(missing), ", ".join(missing[:4])),
                         "抽取过滤器 %r，目录 %s" % (filt, mi_dir))

    log(stage, "原生预览 MI：%d 个唯一包（DA %d 行），并行 miprobe 读格子坐标…"
        % (len(uniq), len(refs)))
    copies = ensure_dir(os.path.join(work_dir, "usmap_copies"))

    def job(name: str):
        return name, _probe_one(kit, have[name], _usmap_for(kit, copies))

    results: Dict[str, Tuple[bool, Dict[str, float], str]] = {}
    with ThreadPoolExecutor(max_workers=min(PROBE_JOBS, len(uniq))) as ex:
        for name, res in ex.map(job, uniq):
            results[name] = res
    bad = [n for n in uniq if not results[n][0]]
    if bad:
        # 兜底：并发阶段挂掉的（工具偶发、机器忙）改用串行重试一次，仍失败才报错
        log(stage, "  并发阶段有 %d 个失败，串行重试…" % len(bad))
        for n in bad:
            results[n] = _probe_one(kit, have[n], _usmap_for(kit, copies))

    occupied: Dict[int, str] = {}
    unaligned: List[str] = []
    for name in uniq:
        ok, sc, why = results[name]
        if not ok or "SpriteX" not in sc or "SpriteY" not in sc:
            raise BuildError(stage, "读不出原生预览 MI %s 的 SpriteX/SpriteY（%s）"
                             % (name, why or "标量缺失"))
        x, y = float(sc["SpriteX"]), float(sc["SpriteY"])
        idx = config.atlas_cell_index(x, y)
        if idx < 0:
            # 不是游戏自己的格坐标（例如整图形态的 0/0 也算这一格）：保守地当成占用，
            # 只记下来。绝不能因为"看不懂"就当它没占格子。
            unaligned.append("%s@(%g,%g)" % (name, x, y))
            idx = config.atlas_cell_index(0.0, 0.0)
        occupied.setdefault(idx, name)

    first_free = next((i for i in range(config.ATLAS_SLOTS) if i not in occupied),
                      config.ATLAS_SLOTS)
    if unaligned:
        log(stage, "WARN: %d 个原生预览 MI 的坐标不在游戏自己的格线上（%s），已按第 0 格保守处理"
            % (len(unaligned), ", ".join(unaligned[:4])))
    log(stage, "原生预览图集占用：%d 格（首个空闲 %d，空位 %d），实测耗时 %.1fs"
        % (len(occupied), first_free, config.ATLAS_SLOTS - len(occupied), time.time() - t0))

    try:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        tmp = cache + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"fingerprint": fp, "rows": len(refs), "first_free": first_free,
                       "occupied": {str(k): v for k, v in sorted(occupied.items())},
                       "measured_at": time.strftime("%Y-%m-%d %H:%M:%S")}, fh,
                      ensure_ascii=False, indent=1)
        os.replace(tmp, cache)
    except OSError as e:
        log(stage, "WARN: 图集占用缓存写不进去（%s）—— 下一轮会重测" % e)
    return {"occupied": occupied, "first_free": first_free, "slots": config.ATLAS_SLOTS,
            "rows": len(refs), "source": "measured", "fingerprint": fp,
            "unaligned": unaligned}
