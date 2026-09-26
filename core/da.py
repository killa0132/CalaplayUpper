# -*- coding: utf-8 -*-
"""DataAsset row appenders -- strictly APPEND-ONLY (user ruling: v1 never
replaces a native entry).

Two proven shapes:

  * audio  `DA_BGM` / `DA_Ambient` / `DA_Sounds`
        uexp = [header 10 B][ N * 28 B ][ 12 B trailer ]
        28 B entry = key FName(8) + package FName(8) + asset FName(8) + empty FString(4)
        map count = u32 @ 6            (measured 2026-09-23)
    appended through `da-patch sndmap` (reflective TMap.Add; UAssetAPI owns the
    name table + SerialSize).

  * backgrounds `DA_Backgrounds`
        uexp = [header 12 B][ N * 34 B ][ 12 B trailer ]
        34 B entry = key FName(8) + u16 0x0500 + soft-path pkg FName(8)
                     + soft-path asset FName(8) + empty SubPath FString(4)
                     + i32 FPackageIndex(4)
        map count = u32 @ 8 ; entries start @ 12
    rows are appended with raw byte surgery (the export is a RawExport) after
    every new FName has been added with `da-patch addname`.

  @30 is a *hard reference* to that row's preview material.  It is copied
  verbatim from the clone source and asserted to resolve to a
  MaterialInstanceConstant.  Never "recompute" it: it only *looks* like
  -(row+2); treating that coincidence as an invariant Fatal-crashed the game
  (Bad import index 166/333).
"""
from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .common import BuildError, Log, ensure_dir
from .kit import Kit

TRAILER = bytes.fromhex("ffffffff00000000c1832a9e")     # 12 B, both DA families
TRAILER_LEN = len(TRAILER)

AUDIO_STRIDE = 28
AUDIO_COUNT_OFF = 6
AUDIO_ROWS_OFF = 10

BG_STRIDE = 34
BG_COUNT_OFF = 8
BG_ROWS_OFF = 12


# --------------------------------------------------------------------------
# generic append-only proof
# --------------------------------------------------------------------------
def assert_append_only(native: bytes, built: bytes, count_off: int, stride: int,
                       rows_off: int, n_new: int, expected_native_count: int,
                       label: str, log: Log, stage: str = "L3") -> None:
    """Prove byte-exactly that `built` == `native` + n_new rows appended."""
    ip = rows_off + stride * expected_native_count
    if len(built) != len(native) + stride * n_new:
        raise BuildError(stage, "%s: length %d != %d + %d*%d"
                         % (label, len(built), len(native), n_new, stride))
    if built[ip + stride * n_new:] != TRAILER:
        raise BuildError(stage, "%s: trailer after the appended rows is wrong" % label)
    if native[ip:] != TRAILER:
        raise BuildError(stage, "%s: native table has no trailer at 0x%X" % (label, ip))
    # every difference must sit inside the count field
    bad = [i for i in range(ip) if built[i] != native[i]
           and not (count_off <= i < count_off + 4)]
    if bad:
        raise BuildError(stage, "%s: %d existing bytes changed (first offsets %s)"
                         % (label, len(bad), bad[:12]))
    cnt = struct.unpack_from("<I", built, count_off)[0]
    if cnt != expected_native_count + n_new:
        raise BuildError(stage, "%s: map count %d != %d + %d"
                         % (label, cnt, expected_native_count, n_new))
    log(stage, "APPEND-ONLY OK  %s: %d -> %d rows, uexp %d -> %d B "
               "(only the count field + appended rows differ)"
        % (label, expected_native_count, cnt, len(native), len(built)))


# --------------------------------------------------------------------------
# audio tables
# --------------------------------------------------------------------------
@dataclass
class AudioRow:
    kind: str
    key: str          # display name shown in the dropdown
    pkg: str          # /Game/... package path
    obj: str          # object name (== last path segment)


def native_audio_count(uexp_path: str) -> int:
    b = open(uexp_path, "rb").read()
    if b[-TRAILER_LEN:] != TRAILER:
        raise BuildError("L3", "%s does not end with the expected 12-byte trailer"
                         % os.path.basename(uexp_path))
    return struct.unpack_from("<I", b, AUDIO_COUNT_OFF)[0]


def append_audio_rows(kit: Kit, da_uasset: str, work: str, rows: Sequence[AudioRow],
                      log: Log, stage: str = "L3") -> str:
    """Chain `da-patch sndmap` once per row. Returns the final uasset path."""
    if not rows:
        return da_uasset
    cur = da_uasset
    for i, r in enumerate(rows):
        od = ensure_dir(os.path.join(work, "sndmap_%02d" % i))
        res = kit.da(["sndmap", cur, kit.usmap, od, r.key, r.pkg, r.obj], log, stage)
        if not res.ok:
            raise BuildError(stage, "da-patch sndmap failed for key '%s' -> %s" % (r.key, r.pkg),
                             res.tail())
        m = re.search(r"appended -> count (\d+)", res.out)
        if not m:
            raise BuildError(stage, "sndmap did not report the new map count",
                             res.tail())
        newu = os.path.join(od, os.path.basename(da_uasset))
        if not os.path.isfile(newu):
            raise BuildError(stage, "sndmap produced no %s" % newu)
        cur = newu
        log(stage, "  +%s key='%s' -> %s  (map count %s)"
            % (r.kind or "audio", r.key, r.pkg, m.group(1)))
    return cur


def add_names(kit: Kit, uasset: str, work: str, names: Sequence[str],
              log: Log, stage: str = "L3") -> Tuple[str, Dict[str, int]]:
    """Chain `da-patch addname`; returns (final uasset, {name: table index}).

    AddNameReference de-duplicates: re-adding an existing name returns its
    original index and leaves the table byte-identical (verified).
    """
    idx: Dict[str, int] = {}
    cur = uasset
    for i, nm in enumerate(names):
        if nm in idx:
            continue
        od = ensure_dir(os.path.join(work, "addname_%02d" % i))
        res = kit.da(["addname", cur, kit.usmap, od, nm], log, stage)
        if not res.ok:
            raise BuildError(stage, "da-patch addname failed for '%s'" % nm, res.tail())
        m = re.search(r"-> index (\d+); names now (\d+)", res.out)
        if not m:
            raise BuildError(stage, "addname did not report an index for '%s'" % nm, res.tail())
        newu = os.path.join(od, os.path.basename(uasset))
        if not os.path.isfile(newu):
            raise BuildError(stage, "addname produced no %s" % newu)
        cur = newu
        idx[nm] = int(m.group(1))
        log(stage, "  name '%s' -> index %s (table size %s)" % (nm, m.group(1), m.group(2)))
    return cur, idx


def parse_imports(text: str) -> List[Tuple[int, str, str, str, int]]:
    rows: List[Tuple[int, str, str, str, int]] = []
    total = mic = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("imports="):
            total = int(s.split("=", 1)[1])
        elif s.startswith("mic="):
            mic = int(s.split("=", 1)[1])
        elif "|" in s:
            f = s.split("|")
            if len(f) == 5:
                rows.append((int(f[0]), f[1], f[2], f[3], int(f[4])))
    if total is None or total != len(rows):
        raise BuildError("L3", "the import table dump looks broken",
                         "imports=%s parsed=%d" % (total, len(rows)))
    return rows


@dataclass
class BgRow:
    key: str          # display name (may be non-ASCII)
    pkg: str
    obj: str
    mi_obj: str = ""  # object name of this row's preview MI (CP-34)
    mi_pkg: str = ""
    mi_ref: int = 0   # FPackageIndex written into @30 (negative = import)


# --------------------------------------------------------------------------
# ImportMap surgery (CP-34): the DA row's @30 hard reference
# --------------------------------------------------------------------------
NAME_RE = re.compile(r"^\s*name\[(\d+)\] = (.*)$")
BGREF_RE = re.compile(r"BGREF_OK ref=(-?\d+) imports=(\d+)->(\d+)")


def probe_names(kit: Kit, uasset: str, log: Log, stage: str = "L3") -> List[str]:
    r = kit.da(["probe", uasset, kit.usmap], log, stage)
    if not r.ok:
        raise BuildError(stage, "da-patch probe failed on %s" % uasset, r.tail())
    out: List[str] = []
    for line in r.out.splitlines():
        m = NAME_RE.match(line)
        if m:
            out.append(m.group(2))
    if not out:
        raise BuildError(stage, "could not read the name table of %s" % uasset, r.tail())
    return out


def assert_name_import_append_only(kit: Kit, before_ua: str, after_ua: str, label: str,
                                   log: Log, stage: str = "L3") -> None:
    """Append-only proof at the *semantic* level.

    UAssetAPI re-serialises the whole package, so a byte diff proves nothing here.
    What must hold is: every pre-existing name keeps its index, and every
    pre-existing import entry keeps its index *and its content*.  A reordered
    ImportMap silently changes the meaning of every negative FPackageIndex in the
    uexp (that is how a fabricated `@30` Fatal-crashed the game once).
    """
    nb = probe_names(kit, before_ua, log, stage)
    na = probe_names(kit, after_ua, log, stage)
    if na[:len(nb)] != nb:
        bad = [i for i in range(len(nb)) if i >= len(na) or na[i] != nb[i]]
        raise BuildError(stage, "%s: existing name entries moved/changed (first bad index %s)"
                         % (label, bad[:8]), "the old %d names must keep their indices" % len(nb))
    ib = parse_imports(kit.da(["imports", before_ua, kit.usmap], log, stage).out)
    ia = parse_imports(kit.da(["imports", after_ua, kit.usmap], log, stage).out)
    if ia[:len(ib)] != ib:
        bad = [i for i in range(len(ib)) if i >= len(ia) or ia[i] != ib[i]]
        raise BuildError(stage, "%s: existing imports were reordered/changed (first bad index %s)"
                         % (label, bad[:8]), "the ImportMap must only ever grow at the end")
    log(stage, "  APPEND-ONLY OK  %s: names %d -> %d, imports %d -> %d, every old index intact"
        % (label, len(nb), len(na), len(ib), len(ia)))


def append_mi_refs(kit: Kit, da_uasset: str, work: str, rows: Sequence[BgRow],
                   log: Log, stage: str = "L3") -> str:
    """Chain `da-patch bgref` once per new preview MI.

    Each call appends exactly 2 imports (Package + MaterialInstanceConstant) to the
    DA ImportMap and reports the FPackageIndex the row's `@30` must carry.
    """
    cur = da_uasset
    for i, r in enumerate(rows):
        od = ensure_dir(os.path.join(work, "bgref_%02d" % i))
        res = kit.da(["bgref", cur, kit.usmap, od, r.mi_pkg, r.mi_obj], log, stage)
        if not res.ok:
            raise BuildError(stage, "da-patch bgref failed for %s" % r.mi_obj, res.tail())
        m = BGREF_RE.search(res.out)
        if not m:
            raise BuildError(stage, "bgref did not report the new reference for %s" % r.mi_obj,
                             res.tail())
        r.mi_ref = int(m.group(1))
        if int(m.group(3)) != int(m.group(2)) + 2:
            raise BuildError(stage, "bgref import accounting is wrong for %s" % r.mi_obj,
                             m.group(0))
        newu = os.path.join(od, os.path.basename(da_uasset))
        if not os.path.isfile(newu):
            raise BuildError(stage, "bgref produced no %s" % newu)
        cur = newu
        log(stage, "  +row MI %s -> %s (@30=%d)" % (r.mi_obj, r.mi_pkg, r.mi_ref))
    if rows:
        assert_name_import_append_only(kit, da_uasset, cur, "DA_Backgrounds + %d MI(s)" % len(rows),
                                       log, stage)
    return cur


def append_bg_rows(kit: Kit, da_uasset: str, work: str, rows: Sequence[BgRow],
                   expected_native_count: int, log: Log, stage: str = "L3",
                   allow_uasset_growth: bool = False) -> str:
    """Add the needed FNames, then append the 34-byte rows. Returns the uasset path.

    `@30` (the row's preview material, a *hard* reference) is either inherited from
    the clone source (`allow_uasset_growth=False`, the v1 behaviour) or taken from
    `row.mi_ref` -- the MI this row's thumbnail must render.
    """
    if not rows:
        return da_uasset
    needed: List[str] = []
    for r in rows:
        for nm in (r.key, r.pkg, r.obj):
            if nm not in needed:
                needed.append(nm)
    log(stage, "background DA: %d new rows, %d new/changed FName(s)" % (len(rows), len(needed)))
    cur, idx = add_names(kit, da_uasset, work, needed, log, stage)

    uxp = os.path.splitext(cur)[0] + ".uexp"
    native = open(uxp, "rb").read()
    native_uasset = open(cur, "rb").read()
    native_len = len(native)
    cnt = struct.unpack_from("<I", native, BG_COUNT_OFF)[0]
    if cnt != expected_native_count:
        raise BuildError(stage, "DA_Backgrounds has %d rows, expected the native %d "
                                "(refusing to double-apply)" % (cnt, expected_native_count))
    if native[BG_ROWS_OFF + BG_STRIDE * cnt:] != TRAILER:
        raise BuildError(stage, "DA_Backgrounds trailer check failed")

    # L1: the clone source's @30 must resolve to a MaterialInstanceConstant
    imp = parse_imports(kit.da(["imports", cur, kit.usmap], log, stage).out)
    src = native[BG_ROWS_OFF:BG_ROWS_OFF + BG_STRIDE]
    src_ref = struct.unpack_from("<i", src, 30)[0]
    ref_i = -src_ref - 1
    if not (0 <= ref_i < len(imp)):
        raise BuildError(stage, "clone source @30=%d -> import index %d out of range (%d)"
                         % (src_ref, ref_i, len(imp)))
    if imp[ref_i][2] != "MaterialInstanceConstant":
        raise BuildError(stage, "clone source @30=%d -> import[%d] class=%s, expected "
                                "MaterialInstanceConstant" % (src_ref, ref_i, imp[ref_i][2]),
                         "the @30 field is a hard reference; never fabricate it")
    log(stage, "  clone source = row 0 (@30=%d -> import[%d] %s / %s)"
        % (src_ref, ref_i, imp[ref_i][2], imp[ref_i][3]))

    MUTABLE = set(range(0, 8)) | set(range(10, 26))
    new_rows = []
    for i, r in enumerate(rows):
        e = bytearray(src)
        struct.pack_into("<I", e, 0, idx[r.key])
        struct.pack_into("<I", e, 4, 0)
        struct.pack_into("<I", e, 10, idx[r.pkg])
        struct.pack_into("<I", e, 14, 0)
        struct.pack_into("<I", e, 18, idx[r.obj])
        struct.pack_into("<I", e, 22, 0)
        mutable = set(MUTABLE)
        if allow_uasset_growth:
            if not r.mi_ref:
                raise BuildError(stage, "row '%s' has no MI reference to write into @30" % r.key,
                                 "run `da-patch bgref` for every new row before appending it")
            struct.pack_into("<i", e, 30, r.mi_ref)
            mutable |= set(range(30, 34))
        if struct.unpack_from("<i", e, 30)[0] != (r.mi_ref if allow_uasset_growth else src_ref):
            raise BuildError(stage, "internal: @30 was mutated for row '%s'" % r.key)
        bad = [o for o in range(BG_STRIDE) if o not in mutable and e[o] != src[o]]
        if bad:
            raise BuildError(stage, "row %d changed bytes outside the 3 slot groups: %s"
                             % (cnt + i, bad))
        new_rows.append(bytes(e))
        log(stage, "  +row #%d key='%s' pkg=%s ast=%s @30=%d (%s)"
            % (cnt + i, r.key, r.pkg, r.obj,
               struct.unpack_from("<i", e, 30)[0],
               "-> our MI import[%d]" % (-r.mi_ref - 1) if allow_uasset_growth
               else "inherited, -> import[%d]" % ref_i))

    ip = BG_ROWS_OFF + BG_STRIDE * cnt
    built = bytearray(native[:ip] + b"".join(new_rows) + native[ip:])
    struct.pack_into("<I", built, BG_COUNT_OFF, cnt + len(rows))
    assert_append_only(native, bytes(built), BG_COUNT_OFF, BG_STRIDE, BG_ROWS_OFF,
                       len(rows), expected_native_count, "DA_Backgrounds", log, stage)

    # export SerialSize = len(uexp) - 4 (PACKAGE_FILE_TAG)
    ua = bytearray(native_uasset)
    old = native_len - 4
    needle = struct.pack("<q", old)
    hits = [i for i in range(len(ua) - 8) if bytes(ua[i:i + 8]) == needle]
    if len(hits) != 1:
        raise BuildError(stage, "SerialSize(%d) hit %d times in %s -- refusing a blind patch"
                         % (old, len(hits), os.path.basename(cur)))
    new_serial = len(built) - 4
    struct.pack_into("<q", ua, hits[0], new_serial)
    if not allow_uasset_growth:
        diff = [i for i in range(len(ua)) if ua[i] != native_uasset[i]]
        outside = [i for i in diff if not (hits[0] <= i < hits[0] + 8)]
        if outside:
            raise BuildError(stage, "uasset changed outside the SerialSize field: %s" % outside[:16])
    else:
        # the ImportMap legitimately grew by 2 entries per new MI -- that was proven
        # append-only (old name/import indices untouched) before we got here.
        log(stage, "  uasset grew by the MI imports (append-only already proven)")
    log(stage, "  SerialSize @0x%X: %d -> %d" % (hits[0], old, new_serial))

    open(uxp, "wb").write(bytes(built))
    open(cur, "wb").write(bytes(ua))
    return cur
