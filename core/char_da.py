# -*- coding: utf-8 -*-
"""DA_Characters 的解析与"新皮肤条目"插入（纯 Python 字节手术）。

数据结构（`SkinRegTool` 时代的实测结论，2026-10-10/11 在真实 DA 上复核）：
    DA_Characters.uexp = [头 8 B][角色数 u32][ 角色条目 ... ]
    角色条目 = key FName(8) + 值（含 Animations / Morphs / Skins 等属性流）
    Skins 是 Map<SkinId, S_SkinAssetData>：
        [count u32][ N * 皮肤条目 ]
    皮肤条目 = key FName(8) + [hdr 2 B = 00 07] + pkg FName(8) + asset FName(8)
              + subPathLen u32(4) + Outlines 数 u32(4) + Outlines 数*20 B + Portrait i32(4)
        条目长度 = 38 + 20 * n   （n = Outlines 元素数；Aika=16 -> 358 B，Celestia=4 -> 118 B）
        Outlines 元素 = 材质包路径 FName(8) + 材质名 FName(8) + subPathLen u32(4)

定位策略（本文件实现、对 20 个实装角色全部实测通过）：
    "皮肤键锚定 + 链式校验" —— 不猜偏移：
      * 在 uexp 里枚举所有形如 `S\\d{3}` 的名称索引的 8 字节 pattern 命中；
      * 对每个命中 k，把 k-4 当作候选 count，要求 count 合理，
        并且从 k 开始能严格解析出 count 个连续皮肤条目（每个条目的 key
        必须是皮肤 ID、pkg/asset 索引必须落在名称表内）；
      * 第一个满足的候选就是该角色的 Skins map —— 皮肤条目链是
        `S\\d{3}` 键的唯一形态（Animations 是数组、Morphs 的键是人名）。

为什么要这么小心：SkinRegTool 旧版"假设 S001 是第一个皮肤键"的启发式在
Julian（第一个皮肤是 S000）上直接算错 count（-12）。这里不再有这种假设。

插入规则（对齐已验证的 S102/S002/S051 生产配方）：
    * 克隆**源皮肤**条目 → 改写 key / pkg / asset（网格）+ 若干 Outlines 槽位；
    * 追加到源条目**之后**（皮肤列表顺序 = 原有顺序 + 新皮肤）；
    * count +1；uasset 的 Export SerialSize 同步 +entry_len；
    * 新名称必须先用 `da-patch addname` 进名称表（只追加、旧索引不动）。
"""
from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .common import BuildError, Log, ensure_dir
from .da import add_names, probe_names
from .kit import Kit

#: 皮肤条目的固定前缀长度（key 8 + hdr 2 + pkg 8 + asset 8 + sub 4 + count 4）
ENTRY_HEAD = 34
#: 每个 Outlines 元素的字节数
ELEM_STRIDE = 20
#: 皮肤 ID 的形态（S000 / S001 / S102 / S051 ...）
SKIN_ID_RE = re.compile(r"^S\d{3}$")


@dataclass
class SkinEntry:
    pos: int                       # 条目起点（key FName 位置）
    key_idx: int                   # 皮肤 ID 的 FName 索引
    length: int                    # 条目总字节数 = 38 + 20n
    outline_count: int             # Outlines 元素数
    pkg_idx: int                   # 网格包路径 FName 索引
    asset_idx: int                 # 网格资产名 FName 索引
    portrait: int                  # 立绘（负数 = import 索引）
    elems: List[Tuple[int, int]] = field(default_factory=list)  # (pkg_idx, asset_idx)


@dataclass
class SkinsMap:
    char_hit: int                  # 角色 key（FName）在 uexp 里的位置
    count_pos: int                 # Skins map 的 count 字段位置
    entries: List[SkinEntry]       # 全部皮肤条目
    end: int                       # 最后一个条目之后的偏移

    def find(self, key_idx: int) -> Optional[SkinEntry]:
        for e in self.entries:
            if e.key_idx == key_idx:
                return e
        return None


# --------------------------------------------------------------------------
# 定位
# --------------------------------------------------------------------------
def _i32(buf: bytes, off: int) -> Optional[int]:
    if off < 0 or off + 4 > len(buf):
        return None
    return struct.unpack_from("<i", buf, off)[0]


def find_skin_id_indexes(names: Sequence[str]) -> Set[int]:
    return {i for i, n in enumerate(names) if SKIN_ID_RE.match(n)}


def _parse_entry(buf: bytes, pos: int, skin_idx: Set[int], n_names: int) -> Optional[SkinEntry]:
    if pos + ENTRY_HEAD > len(buf):
        return None
    key = _i32(buf, pos)
    if key not in skin_idx:
        return None
    n = _i32(buf, pos + 30)
    if n is None or not (0 <= n <= 64):
        return None
    length = 38 + ELEM_STRIDE * n
    if pos + length > len(buf):
        return None
    pkg, asset = _i32(buf, pos + 10), _i32(buf, pos + 18)
    if pkg is None or asset is None or not (0 <= pkg < n_names) or not (0 <= asset < n_names):
        return None
    elems = []
    for k in range(n):
        ep, ea = _i32(buf, pos + ENTRY_HEAD + ELEM_STRIDE * k), \
            _i32(buf, pos + ENTRY_HEAD + ELEM_STRIDE * k + 8)
        if ep is None or ea is None or not (0 <= ep < n_names) or not (0 <= ea < n_names):
            return None
        elems.append((ep, ea))
    return SkinEntry(pos=pos, key_idx=key, length=length, outline_count=n,
                     pkg_idx=pkg, asset_idx=asset,
                     portrait=_i32(buf, pos + 34 + ELEM_STRIDE * n) or 0,
                     elems=elems)


def _parse_chain(buf: bytes, start: int, count: int, skin_idx: Set[int],
                 n_names: int) -> Optional[List[SkinEntry]]:
    out: List[SkinEntry] = []
    pos = start
    for _ in range(count):
        e = _parse_entry(buf, pos, skin_idx, n_names)
        if e is None:
            return None
        out.append(e)
        pos += e.length
    return out


#: 角色条目 value 的 struct 头（实测：20 个实装角色的键后面都紧跟这两个字节）。
#: morph 名虽然也是"大写开头的单词"，但其键后面没有这个头 —— 用它把二者分开。
CHAR_VALUE_HEAD = b"\x00\x07"


def _char_key_hits(buf: bytes, char_idx: int) -> List[int]:
    pat = struct.pack("<i", char_idx) + b"\x00" * 4
    out: List[int] = []
    p = buf.find(pat)
    while p >= 0:
        out.append(p)
        p = buf.find(pat, p + 1)
    return out


def find_skins_map(buf: bytes, char_idx: int, names: Sequence[str],
                   window: int = 400000, require_char_head: bool = True,
                   relaxed_fallback: bool = True) -> SkinsMap:
    """找 `char_idx` 这个角色的 Skins map；找不到抛 BuildError。

    `require_char_head=True`（默认）时要求候选键后面紧跟 `00 07` —— 角色条目的
    value 头。枚举全部名字（GUI 的角色下拉）时必须开着它，否则 Morphs map 里的
    表情名（Anger/Angry…）会被当成角色。对"已知正确的角色键"（导入流程用名称表
    索引直接定位）留了 `relaxed_fallback` 兜底：严格模式找不到时再用宽松模式试一遍。
    """
    skin_idx = find_skin_id_indexes(names)
    n_names = len(names)
    if not skin_idx:
        raise BuildError("C4", "名称表里没有任何 S### 形式的皮肤 ID",
                         "DA 名称表大小 = %d" % n_names)
    chs = _char_key_hits(buf, char_idx)
    if not chs:
        raise BuildError("C4", "名称表里找不到角色 'char idx=%d' 的使用位置" % char_idx)
    # 所有皮肤键 pattern 的命中（全局一次）
    hits: List[int] = []
    for si in skin_idx:
        pat_k = struct.pack("<i", si) + b"\x00" * 4
        q = buf.find(pat_k)
        while q >= 0:
            hits.append(q)
            q = buf.find(pat_k, q + 1)
    hits.sort()
    for h in chs:
        if require_char_head and buf[h + 8:h + 10] != CHAR_VALUE_HEAD:
            continue
        lo, hi = h + 8, min(h + window, len(buf))
        for k in hits:
            if k < lo:
                continue
            if k >= hi:
                break
            cnt = _i32(buf, k - 4)
            if cnt is None or not (1 <= cnt <= 40):
                continue
            chain = _parse_chain(buf, k, cnt, skin_idx, n_names)
            if chain:
                return SkinsMap(char_hit=h, count_pos=k - 4, entries=chain,
                                end=chain[-1].pos + chain[-1].length)
    if require_char_head and relaxed_fallback:
        return find_skins_map(buf, char_idx, names, window,
                              require_char_head=False, relaxed_fallback=False)
    raise BuildError("C4", "角色 (idx=%d) 的 Skins map 定位失败（%d 个候选位置都不通过链式校验）"
                     % (char_idx, len(chs)))


# --------------------------------------------------------------------------
# 条目构建 / 插入
# --------------------------------------------------------------------------
def build_entry_bytes(buf: bytes, src: SkinEntry, new_key_idx: int,
                      pkg_idx: Optional[int] = None, asset_idx: Optional[int] = None,
                      elem_patches: Optional[Dict[int, Tuple[int, int]]] = None,
                      portrait: Optional[int] = None) -> bytes:
    """克隆 `src` 条目并改写索引；返回新条目字节（长度与源相同）。

    `elem_patches` = {元素序号: (新 pkg 索引, 新 asset 索引)}；未列出的槽位
    原样保留（共享材质就该保持 S001 的引用）。
    """
    e = bytearray(buf[src.pos:src.pos + src.length])
    struct.pack_into("<i", e, 0, new_key_idx)
    struct.pack_into("<i", e, 4, 0)
    if pkg_idx is not None:
        struct.pack_into("<i", e, 10, pkg_idx)
        struct.pack_into("<i", e, 14, 0)
    if asset_idx is not None:
        struct.pack_into("<i", e, 18, asset_idx)
        struct.pack_into("<i", e, 22, 0)
    for i, (pp, pa) in (elem_patches or {}).items():
        if not (0 <= i < src.outline_count):
            raise BuildError("C4", "Outlines 槽位 %d 超出条目范围（%d 个）" % (i, src.outline_count))
        off = ENTRY_HEAD + ELEM_STRIDE * i
        struct.pack_into("<i", e, off, pp)
        struct.pack_into("<i", e, off + 4, 0)
        struct.pack_into("<i", e, off + 8, pa)
        struct.pack_into("<i", e, off + 12, 0)
    if portrait is not None:
        struct.pack_into("<i", e, 34 + ELEM_STRIDE * src.outline_count, portrait)
    return bytes(e)


def _serial_size_at(uasset: bytes, old_uexp_len: int, stage: str) -> int:
    needle = struct.pack("<q", old_uexp_len - 4)
    hits = [i for i in range(len(uasset) - 8) if bytes(uasset[i:i + 8]) == needle]
    if len(hits) != 1:
        raise BuildError(stage, "SerialSize(%d) 在 uasset 里命中 %d 次，拒绝盲改"
                         % (old_uexp_len - 4, len(hits)))
    return hits[0]


def insert_skin_entry(uasset_path: str, uexp_path: str, skins: SkinsMap, after: SkinEntry,
                      new_entry: bytes, log: Log, stage: str = "C4") -> Tuple[bytes, bytes]:
    """把新条目插到 `after` 之后、count+1、SerialSize 同步；返回 (uasset, uexp) 字节。"""
    ua = open(uasset_path, "rb").read()
    ux = open(uexp_path, "rb").read()
    if len(new_entry) != after.length:
        raise BuildError(stage, "新条目 %d B 与源条目 %d B 不一致（克隆必须等长）"
                         % (len(new_entry), after.length))
    ip = after.pos + after.length
    if ip > len(ux):
        raise BuildError(stage, "插入位置 %d 越界（uexp %d B）" % (ip, len(ux)))
    cnt = struct.unpack_from("<i", ux, skins.count_pos)[0]
    if cnt != len(skins.entries):
        raise BuildError(stage, "count 字段(%d)与实际条目数(%d)不一致，拒绝修改"
                         % (cnt, len(skins.entries)))
    built = bytearray(ux[:ip] + new_entry + ux[ip:])
    struct.pack_into("<i", built, skins.count_pos, cnt + 1)

    # append-only 证明：除 count 字段与插入的新条目外，一个字节都不许动
    if bytes(built[:skins.count_pos]) != ux[:skins.count_pos] \
            or bytes(built[skins.count_pos + 4:ip]) != ux[skins.count_pos + 4:ip] \
            or bytes(built[ip:ip + len(new_entry)]) != new_entry \
            or bytes(built[ip + len(new_entry):]) != ux[ip:]:
        raise BuildError(stage, "插入后字节核对失败（出现计划外的改动）")

    ua2 = bytearray(ua)
    at = _serial_size_at(ua, len(ux), stage)
    struct.pack_into("<q", ua2, at, len(built) - 4)
    outside = [i for i in range(len(ua2)) if ua2[i] != ua[i] and not (at <= i < at + 8)]
    if outside:
        raise BuildError(stage, "uasset 在 SerialSize 之外被改动：%s" % outside[:16])
    log(stage, "  条目插入：count %d -> %d，uexp %d -> %d B（+%d），SerialSize @0x%X"
        % (cnt, cnt + 1, len(ux), len(built), len(new_entry), at))
    return bytes(ua2), bytes(built)


def entry_summary(entry: SkinEntry, names: Sequence[str]) -> str:
    def nm(i: int) -> str:
        return names[i] if 0 <= i < len(names) else "<bad:%d>" % i
    return "key=%s pkg=%s asset=%s outlines=%d length=%d" % (
        nm(entry.key_idx), nm(entry.pkg_idx), nm(entry.asset_idx),
        entry.outline_count, entry.length)


# --------------------------------------------------------------------------
# 顶层入口
# --------------------------------------------------------------------------
def register_skin(kit: Kit, da_base: str, work: str, char_idx: int, src_skin_idx: int,
                  new_skin_id: str, new_mesh_pkg: str, new_mesh_asset: str,
                  outline_paths: Sequence[str], elem_plan: Dict[int, str],
                  log: Log, stage: str = "C4") -> str:
    """给角色（`char_idx`）新增一个皮肤条目；返回新的 DA uasset 路径。

    参数
    ----
    da_base       : DA_Characters 的路径前缀（不带 .uasset）
    char_idx      : 角色名的 FName 索引（da-patch probe 名称表里查到）
    src_skin_idx  : 源皮肤（如 S001）的 FName 索引
    new_skin_id   : 新皮肤 ID 字符串（如 "S052"）
    new_mesh_pkg  : 新网格的包路径（/Game/CalaPlayer/Characters/Aika/S052/aika-s052）
    new_mesh_asset: 新网格的资产名（aika-s052）
    outline_paths : 需要新路径的 Outlines 材质包路径列表（去重）
    elem_plan     : {Outlines 槽位序号: 新材质包路径} —— 槽位内资产名沿用源条目
    """
    # 1) 新名称先入表（只追加；已存在的名称返回原索引）
    wanted: List[str] = [new_skin_id, new_mesh_pkg, new_mesh_asset]
    for p in list(outline_paths) + list(elem_plan.values()):
        if p not in wanted:
            wanted.append(p)
    log(stage, "注册新皮肤 '%s'：名称表追加 %d 个候选（重复项会被 addname 去重）"
        % (new_skin_id, len(wanted)))
    cur, idx_map = add_names(kit, da_base + ".uasset", work, wanted, log, stage)

    # 2) 用最终 uasset 重读名称表（addname 只追加，旧索引不变）
    names = probe_names(kit, cur, log, stage)
    log(stage, "  名称表：%d 项（新名称 %s）"
        % (len(names), ", ".join("'%s'=%d" % (w, idx_map[w]) for w in wanted[:4])
           + (" ..." if len(wanted) > 4 else "")))

    uasset_path = cur
    uexp_path = os.path.splitext(cur)[0] + ".uexp"
    ux = open(uexp_path, "rb").read()
    skins = find_skins_map(ux, char_idx, names)
    log(stage, "  Skins map：count@%d，%d 个皮肤（%s）" % (
        skins.count_pos, len(skins.entries),
        ", ".join(names[e.key_idx] for e in skins.entries)))

    src = skins.find(src_skin_idx)
    if src is None:
        raise BuildError(stage, "源皮肤 (idx=%d) 不在该角色的 Skins map 里" % src_skin_idx)
    log(stage, "  源条目：%s" % entry_summary(src, names))

    # 3) 克隆 + 改写
    epatches: Dict[int, Tuple[int, int]] = {}
    for slot, new_path in elem_plan.items():
        if not (0 <= slot < src.outline_count):
            raise BuildError(stage, "elem_plan 槽位 %d 超出范围（0..%d）"
                             % (slot, src.outline_count - 1))
        old_pkg_idx, old_asset_idx = src.elems[slot]
        epatches[slot] = (idx_map[new_path], old_asset_idx)
        log(stage, "  槽位 %2d：%s -> %s（资产名沿用 %s）"
            % (slot, names[old_pkg_idx], new_path, names[old_asset_idx]))
    new_entry = build_entry_bytes(ux, src, idx_map[new_skin_id],
                                  pkg_idx=idx_map[new_mesh_pkg],
                                  asset_idx=idx_map[new_mesh_asset],
                                  elem_patches=epatches)
    ua2, ux2 = insert_skin_entry(uasset_path, uexp_path, skins, src, new_entry, log, stage)

    out_dir = ensure_dir(os.path.join(work, "da_out"))
    out_ua = os.path.join(out_dir, os.path.basename(uasset_path))
    out_ux = os.path.splitext(out_ua)[0] + ".uexp"
    open(out_ua, "wb").write(ua2)
    open(out_ux, "wb").write(ux2)
    log(stage, "  写出：%s（uasset %d B，uexp %d B）"
        % (out_dir, len(ua2), len(ux2)))

    # 4) 复核：重新解析一遍新 uexp，新皮肤必须在列
    check = find_skins_map(ux2, char_idx, names)
    got = check.find(idx_map[new_skin_id])
    if got is None:
        raise BuildError(stage, "复核失败：新条目不在 Skins map 里")
    if (got.pkg_idx, got.asset_idx) != (idx_map[new_mesh_pkg], idx_map[new_mesh_asset]):
        raise BuildError(stage, "复核失败：新条目的网格引用不对")
    log(stage, "  复核通过：%s（%d 个皮肤，新条目 %s）"
        % (entry_summary(got, names), len(check.entries), new_skin_id))
    return out_ua
