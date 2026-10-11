# -*- coding: utf-8 -*-
"""「添加角色模型」的 GUI 侧发现与校验（宽容的一侧，不碰 `core/`）。

和 `gui/mods.py` 同一套立场：页面的下拉列表、开始前的错误卡片都需要"先看一眼
游戏里有什么"，但这一步比真正的导入宽松得多 —— 失败只返回一句人话，绝不抛异常。

- `discover_characters()`：只读地提取 `DA_Characters`，列出游戏里 20 个实装角色
  各自已有的皮肤（下拉用）；结果按 Paks 路径缓存 10 分钟。
- `validate()`：开始导入之前必须成立的条件（路径在不在、素材里有没有 PNG、
  皮肤 ID 的格式），驱动前端那张"一次列全"的错误卡片。
"""
from __future__ import annotations

import os
import re
import tempfile
import time
from typing import Any, Dict, List, Optional

from core import char_da, char_kit, config
from core.common import Log, rmtree
from core.da import probe_names
from core.kit import load_kit

SKIN_RE = re.compile(r"^S\d{3}$")
CHAR_RE = re.compile(r"^[A-Z][a-z][A-Za-z]*$")     # Aika / Celestia / Kokona ...
_CACHE: Dict[str, Any] = {}
_CACHE_TTL = 600.0


def _log() -> Log:
    return Log(None, echo=False)


def _extract_da(paks_dir: str, kit_arg: str, log: Log):
    """提取 DA_Characters（临时目录）→ (names, uexp bytes, char_root)。"""
    kit = load_kit(kit_arg or None, None, log, "GUI")
    tmp = os.path.join(tempfile.gettempdir(), "cala-char-discover")
    rmtree(tmp)
    char_kit.to_legacy_filters(kit, paks_dir, tmp, ["DA_Characters."], log, "GUI")
    base = os.path.join(tmp, "CalaPlayer", "Content", "CalaPlayer", "Characters")
    da = os.path.join(base, "DA_Characters")
    if not os.path.isfile(da + ".uasset"):
        raise RuntimeError("提取树里没有 DA_Characters（这个目录是游戏的 Paks 吗？）")
    names = probe_names(kit, da + ".uasset", log, "GUI")
    ux = open(da + ".uexp", "rb").read()
    return names, ux


def invalidate(paks: str = "") -> None:
    """把角色清单缓存清掉（刚导入完一套皮肤后调用：下次读取要看到新皮肤）。"""
    if not paks:
        _CACHE.clear()
        return
    prefix = os.path.abspath(paks) + "|"
    for k in [k for k in _CACHE if k.startswith(prefix)]:
        _CACHE.pop(k, None)


def discover_characters(paks: str, kit_arg: str = "") -> Dict[str, Any]:
    """游戏里的角色清单（带各自已有皮肤）；失败时 ok=false + message。"""
    paks = (paks or "").strip()
    if not paks:
        return {"ok": False, "message": "游戏 Paks 目录未填写", "characters": []}
    key = "%s|%s" % (os.path.abspath(paks), kit_arg or "")
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    try:
        game = config.discover_game(paks)
        names, ux = _extract_da(game.paks_dir, kit_arg, _log())
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": "%s: %s" % (type(e).__name__, e), "characters": []}

    chars: List[Dict[str, Any]] = []
    for idx, nm in enumerate(names):
        if not CHAR_RE.match(nm):
            continue
        try:
            # 严格模式（不 fallback）：角色键后面必须紧跟 `00 07` 的 value 头。
            # 没有它，Morphs map 里的表情名（Anger/Angry…）也会"定位成功"。
            skins = char_da.find_skins_map(ux, idx, names, relaxed_fallback=False)
        except Exception:  # noqa: BLE001
            continue                      # 不是角色键（动画/morph 名）或布局不认识
        names_list = [names[e.key_idx] for e in skins.entries]
        first_pkg = names[skins.entries[0].pkg_idx] if skins.entries else ""
        m = re.match(r"^/Game/CalaPlayer/Characters/([^/]+)/", first_pkg)
        char_dir = m.group(1) if m else nm
        chars.append({"name": nm, "dir": char_dir, "skins": names_list,
                      "char_idx": idx})
    chars.sort(key=lambda c: c["name"])
    out = {"ok": bool(chars), "characters": chars,
           "message": "" if chars else "没能在 DA 里认出任何角色"}
    _CACHE[key] = (time.time(), out)
    return out


def validate(paks: str, skin: str, character: str = "", skin_id: str = "",
             source_skin: str = "S001") -> Dict[str, Any]:
    """开始导入前的一次性检查（错误一次列全，驱动错误卡片）。"""
    errors: List[str] = []
    warnings: List[str] = []
    if not (paks or "").strip():
        errors.append("游戏 Paks 目录未填写")
    elif not os.path.isdir(paks):
        errors.append("游戏 Paks 目录不存在：%s" % paks)
    if not (skin or "").strip():
        errors.append("素材目录未填写")
    elif not os.path.isdir(skin):
        errors.append("素材目录不存在：%s" % skin)
    else:
        png_dir = skin
        for sub in ("Mesh3D", "mesh3d", "Textures", "textures"):
            d = os.path.join(skin, sub)
            if os.path.isdir(d):
                png_dir = d
                break
        try:
            pngs = [f for f in os.listdir(png_dir) if f.lower().endswith(".png")]
        except OSError:
            pngs = []
        if not pngs:
            errors.append("素材里没有 PNG 贴图：%s" % png_dir)
        else:
            warnings.append("素材目录：%s（%d 张 PNG）" % (png_dir, len(pngs)))
        if (skin_id or "").strip() and not SKIN_RE.match(skin_id.strip()):
            errors.append("新皮肤 ID 必须形如 S052（S + 3 位数字）")
        if (source_skin or "").strip() and not SKIN_RE.match(source_skin.strip()):
            errors.append("源皮肤必须形如 S001（S + 3 位数字）")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "mode": "character"}
