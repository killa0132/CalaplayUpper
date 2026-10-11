# -*- coding: utf-8 -*-
"""角色模型导入链路专用的 retoc 包装（扩展 `core/kit.py`，不改它）。

为什么单独一个文件
------------------
`core/kit.py` 是打包引擎冻住的一部分（`Kit` 的每个方法都服务于背景/音频那条
既有管线）。角色导入需要它没有暴露的三件事：

  * `to-legacy` 传**多个** `-f` 过滤器（只要角色目录 + DA_Characters，而不是
    把 4100 个资产全提出来）；
  * `unpack-raw` / `pack-raw`（补丁容器的**字节级**提取与重打包 —— 这是
    "在原 `_P` 基础上只换掉 DA chunk"的关键，实测往返零损耗）；
  * `verify`（写完之后独立复核容器结构）。

这里用组合（持有 `Kit` 实例）而不是继承，避免碰 `Kit` 的既有行为。
"""
from __future__ import annotations

import os
import shutil
from typing import List, Optional

from .common import BuildError, Log, ProcResult, run
from .kit import Kit

#: `to-legacy` 需要的参数（和 `Kit.to_legacy` 保持一致）
_LEGACY_FLAGS = ["--no-script-objects", "--no-shaders", "--version", "UE5_7"]


def _retoc(kit: Kit, args: List[str], log: Log, stage: str, timeout: int = 1800,
           echo: bool = False) -> ProcResult:
    # retoc 从自己所在目录加载 oo2core_9_win64.dll -> cwd 固定为它
    return run([kit.retoc] + args, cwd=os.path.dirname(kit.retoc), log=log,
               stage=stage, echo_stdout=echo, timeout=timeout)


def to_legacy_filters(kit: Kit, paks_dir: str, out_dir: str, filters: List[str],
                      log: Log, stage: str = "C1", timeout: int = 1800) -> ProcResult:
    """`retoc to-legacy <Paks 目录>`，每个 filter 一个 `-f`（目录方式必须传整个
    Paks 目录：单容器输入会因缺少 ScriptObjects chunk 而解析失败，实测）。"""
    os.makedirs(out_dir, exist_ok=True)
    args = ["to-legacy", paks_dir, out_dir] + _LEGACY_FLAGS
    for f in filters:
        args += ["-f", f]
    r = _retoc(kit, args, log, stage, timeout=timeout)
    if not r.ok:
        raise BuildError(stage, "retoc to-legacy 失败（%s）" % paks_dir, r.tail())
    return r


def unpack_raw(kit: Kit, utoc: str, out_dir: str, log: Log,
               stage: str = "C5", timeout: int = 900) -> ProcResult:
    """把容器（.utoc）原样拆成 `chunks/<chunk-id>` + `manifest.json`。

    注意：retoc 要求输出目录**不存在**（它自己创建；已存在的空目录会报
    `os error 183`），所以这里先清掉旧目录而不是预先 makedirs。
    """
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)
    r = _retoc(kit, ["unpack-raw", utoc, out_dir], log, stage, timeout=timeout)
    if not r.ok:
        raise BuildError(stage, "retoc unpack-raw 失败（%s）" % utoc, r.tail())
    return r


def pack_raw(kit: Kit, raw_dir: str, out_utoc: str, log: Log,
             stage: str = "C5", timeout: int = 1800) -> ProcResult:
    """`chunks/` + `manifest.json` → 新容器（容器 id / 头部格式保持不变）。"""
    os.makedirs(os.path.dirname(os.path.abspath(out_utoc)), exist_ok=True)
    r = _retoc(kit, ["pack-raw", raw_dir, out_utoc], log, stage, timeout=timeout)
    if not r.ok:
        raise BuildError(stage, "retoc pack-raw 失败（%s）" % out_utoc, r.tail())
    return r


def verify(kit: Kit, utoc: str, log: Log, stage: str = "C5") -> str:
    """独立复核容器结构；不通过立即抛错（绝不把坏容器交出去）。"""
    r = _retoc(kit, ["verify", utoc], log, stage)
    text = (r.out + r.err).strip()
    if not r.ok or "verified" not in text.lower():
        raise BuildError(stage, "容器校验未通过（%s）" % utoc, r.tail())
    return text


def info(kit: Kit, utoc: str, log: Log, stage: str = "C5") -> str:
    r = _retoc(kit, ["info", utoc], log, stage)
    return r.out + r.err


def list_paths(kit: Kit, utoc: str, log: Log, stage: str = "C5") -> List[str]:
    """`retoc list --path` → 资源路径清单（`../../../CalaPlayer/Content/...`）。"""
    r = _retoc(kit, ["list", "--path", utoc], log, stage)
    if not r.ok:
        raise BuildError(stage, "retoc list 失败（%s）" % utoc, r.tail())
    out: List[str] = []
    for line in r.out.splitlines():
        f = line.split()
        if len(f) >= 3 and f[-1].startswith("../../../"):
            out.append(f[-1])
    if not out:
        raise BuildError(stage, "retoc list 输出为空（%s）" % utoc, r.tail())
    return out


def container_exists(paks_dir: str, base: str = "CalaPlayer-Windows_P") -> bool:
    """容器三件套是否齐全（.pak/.ucas/.utoc）。"""
    return all(os.path.isfile(os.path.join(paks_dir, "%s.%s" % (base, e)))
               for e in ("pak", "ucas", "utoc"))


def package_root_of(path: str) -> str:
    """`../../../CalaPlayer/Content/CalaPlayer/Characters/Aika/S001/x.uasset`
    → `CalaPlayer/Content/CalaPlayer/Characters/Aika/S001/x.uasset`（legacy 树相对路径）。"""
    return path.replace("../../../", "", 1) if path.startswith("../../../") else path


def utoc_of(paks_dir: str, base: str) -> str:
    return os.path.join(paks_dir, "%s.utoc" % base)
