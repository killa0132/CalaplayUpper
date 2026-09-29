# -*- coding: utf-8 -*-
"""Unified mod-merge protocol (PoC): N independent mods -> ONE `_P` patch.

Wire format
-----------
`-Mods <dir>` holds an INDEX manifest (`<dir>/manifest.json`) that lists one
manifest per mod::

    {"mods": [{"name": "CalaplayUpper", "manifest": "CalaplayUpper_src/manifest.json"},
              {"name": "XG_Translations", "manifest": "mods/manifest.json"}]}

Every mod owns a `folder` (relative to `-Mods`).  Two kinds:

  * ``da_edit``  -- row-level edits of a cooked DataAsset table.  The mod ships
    its own pair ``<folder>/<TABLE>.uasset|.uexp`` (built by the single-mod
    pipeline, i.e. "native table + this mod's own appends") plus ``targets``
    naming the rows it owns::

        "targets": {"DA_Backgrounds": {"appended_rows": [165, 166]}}

  * ``ui_text``  -- whole-file replacement of legacy assets (widgets, blueprint
    bytecode).  The mod ships ``files`` (legacy-relative paths, e.g.
    ``CalaPlayer/Content/CalaPlayer/UI/Widgets/WBP_MainMenu.uasset``) which are
    merged into one directory WITHOUT flattening (retoc recovers the package id
    from the directory structure).

``files`` is MANDATORY for both kinds (``[]`` when the mod contributes no asset
file): it declares the mod's change scope, it is what the file-path conflict check
compares, and it is the list whose relative paths must survive verbatim.

Invariants inherited from the single-mod pipeline (never weakened)
-----------------------------------------------------------------
  * the clean ``-Base`` Paks dir is READ ONLY; everything is written inside
    ``-Out`` (this module never installs anything into the game folder);
  * DA tables are merged ROW BY ROW from the native baseline -- an already
    appended table is never re-serialised in place (`da-patch bgref`/`addname`
    on top of it grows the uexp by one row while the row count stays, which the
    trailer gate refuses: the documented `-Combined` bug);
  * a row's ``@30`` hard reference is never fabricated -- it is either the
    native import index (unchanged because the ImportMap only grows at the end)
    or a fresh ``da-patch bgref`` reference;
  * every DA append is proven append-only (`da.assert_append_only`) and every
    name/import change is proven non-reordering
    (`da.assert_name_import_append_only`).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from . import config
from . import da as DA
from .common import (BuildError, Log, ensure_dir, hardlink_or_copy, rmtree,
                     sha256_file, sha16)
from .da import (AUDIO_COUNT_OFF, AUDIO_ROWS_OFF, AUDIO_STRIDE, BG_COUNT_OFF,
                 BG_ROWS_OFF, BG_STRIDE, TRAILER, TRAILER_LEN, AudioRow, BgRow)
from .kit import Kit, load_kit

# --------------------------------------------------------------------------
# table metadata (single source: core/da.py constants)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TableSpec:
    tag: str
    pkg: str
    stride: int
    count_off: int
    rows_off: int
    slots: Tuple[Tuple[str, int], ...]
    ref_off: Optional[int]          # byte offset of the `@30` FPackageIndex (bg only)


TABLE_SPECS: Dict[str, TableSpec] = {
    "DA_Backgrounds": TableSpec("DA_Backgrounds", config.DA_BACKGROUNDS, BG_STRIDE,
                                BG_COUNT_OFF, BG_ROWS_OFF,
                                (("key", 0), ("pkg", 10), ("obj", 18)), 30),
    "DA_BGM": TableSpec("DA_BGM", config.DA_BGM, AUDIO_STRIDE, AUDIO_COUNT_OFF,
                        AUDIO_ROWS_OFF, (("key", 0), ("pkg", 8), ("obj", 16)), None),
    "DA_Ambient": TableSpec("DA_Ambient", config.DA_AMBIENT, AUDIO_STRIDE, AUDIO_COUNT_OFF,
                            AUDIO_ROWS_OFF, (("key", 0), ("pkg", 8), ("obj", 16)), None),
    "DA_Sounds": TableSpec("DA_Sounds", config.DA_SOUNDS, AUDIO_STRIDE, AUDIO_COUNT_OFF,
                           AUDIO_ROWS_OFF, (("key", 0), ("pkg", 8), ("obj", 16)), None),
}

OPS = ("appended_rows", "modified_rows", "deleted_rows")
KINDS = ("da_edit", "ui_text")
TABLE_FILENAMES = tuple(TABLE_SPECS.keys())
WORK_DIRNAME = "merge_work"


def tool_version() -> str:
    """Single source of truth is `core/builder.py::TOOL_VERSION` (imported lazily)."""
    try:
        from .builder import TOOL_VERSION
        return str(TOOL_VERSION)
    except Exception:
        return "1.2.1"


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------
@dataclass
class MergeReport:
    ok: bool = False
    error: str = ""
    seconds: float = 0.0
    tool: str = "CalaPlayerModMerger"
    version: str = ""
    params: Dict = field(default_factory=dict)
    resolved: Dict = field(default_factory=dict)
    selected: List[str] = field(default_factory=list)
    mods: List[Dict] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    tables: Dict[str, Dict] = field(default_factory=dict)
    files: List[str] = field(default_factory=list)
    gates: Dict[str, Dict] = field(default_factory=dict)
    ledger: Dict = field(default_factory=dict)
    container: Dict = field(default_factory=dict)
    work: str = ""
    out_dir: str = ""

    def to_dict(self) -> Dict:
        return {
            "tool": self.tool,
            "version": self.version,
            "ok": bool(self.ok),
            "error": self.error,
            "seconds": round(self.seconds, 2),
            "params": self.params,
            "resolved": self.resolved,
            "selected": self.selected,
            "mods": self.mods,
            "conflicts": self.conflicts,
            "tables": self.tables,
            "files": self.files,
            "gates": self.gates,
            "ledger": self.ledger,
            "container": self.container,
            "work": self.work,
            "out_dir": self.out_dir,
        }


# --------------------------------------------------------------------------
# low level helpers
# --------------------------------------------------------------------------
def _read(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _norm(rel: str) -> str:
    """Forward-slash relative path (the protocol always speaks POSIX style)."""
    return rel.replace("\\", "/").lstrip("/")


def _safe_rel(rel: str) -> str:
    r = _norm(rel)
    if not r or r.startswith("../") or "/../" in r or ":" in r:
        raise BuildError("M0", "unsafe relative path in a mod manifest: %r" % rel)
    return r


def table_rows(uexp: bytes, spec: TableSpec) -> int:
    """Row count of a cooked DA table, with the trailer used as a sanity check."""
    if len(uexp) < spec.rows_off + TRAILER_LEN:
        raise BuildError("M2", "%s: uexp is too short (%d B)" % (spec.tag, len(uexp)))
    n = struct.unpack_from("<I", uexp, spec.count_off)[0]
    end = spec.rows_off + spec.stride * n
    if end + TRAILER_LEN != len(uexp) or uexp[end:] != TRAILER:
        raise BuildError("M2", "%s: row array does not add up (count=%d, uexp=%d B, "
                               "expected %d B)" % (spec.tag, n, len(uexp), end + TRAILER_LEN),
                         "the table is not shaped like a cooked %s" % spec.tag)
    return n


def _row_indices(uexp: bytes, spec: TableSpec, row: int) -> Dict[str, int]:
    off = spec.rows_off + spec.stride * row
    out: Dict[str, int] = {}
    for name, delta in spec.slots:
        out[name] = struct.unpack_from("<I", uexp, off + delta)[0]
    if spec.ref_off is not None:
        out["ref"] = struct.unpack_from("<i", uexp, off + spec.ref_off)[0]
    return out


def import_pkg_path(imports: Sequence[Tuple], imp_idx: int) -> str:
    """`{idx}|ClassPackage|ClassName|ObjectName|Outer` -> the package path of an import."""
    if not (0 <= imp_idx < len(imports)):
        raise BuildError("M3", "import index %d is out of range (%d imports)"
                         % (imp_idx, len(imports)))
    entry = imports[imp_idx]
    outer = int(entry[4])
    if outer >= 0:
        raise BuildError("M3", "import %d has a non-negative outer (%d); expected a package"
                         % (imp_idx, outer))
    pkg_idx = -outer - 1
    if not (0 <= pkg_idx < len(imports)):
        raise BuildError("M3", "import %d points at package import %d, out of range (%d)"
                         % (imp_idx, pkg_idx, len(imports)))
    pkg = imports[pkg_idx]
    if str(pkg[2]) != "Package":
        raise BuildError("M3", "import %d's outer (%d) is a %s, not a Package"
                         % (imp_idx, pkg_idx, pkg[2]))
    return str(pkg[3])


def _to_legacy_raw(kit: Kit, inp: str, out_dir: str, asset_filter: Optional[str],
                   log: Log, stage: str, timeout: int = 900):
    """`kit.to_legacy` with an empty output dir guaranteed (and the same cwd rules).

    NOTE: `scriptobjects.bin` is deliberately NOT collected.  `retoc to-zen` ignores it
    (verified: Xenon-XG's own working patch container carries only `ExportBundleData` +
    `ContainerHeader`), and the game resolves script objects from the native `global`."""
    args = ["to-legacy", inp, out_dir, "--no-script-objects", "--no-shaders",
            "--version", "UE5_7"]
    if asset_filter:
        args += ["-f", asset_filter]
    ensure_dir(out_dir)
    r = kit._retoc(args, log, stage, timeout=timeout)
    if not r.ok:
        raise BuildError(stage, "retoc to-legacy failed for %s" % inp, r.tail())
    return r


def _list_files(root: str) -> Dict[str, str]:
    """{forward-slash rel path: absolute path} for every file below `root`."""
    out: Dict[str, str] = {}
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            ap = os.path.join(dirpath, f)
            out[_norm(os.path.relpath(ap, root))] = ap
    return out


def _set_serial_size(ua_path: str, old_uexp_len: int, new_uexp_len: int) -> None:
    """The export's SerialSize lives in the uasset and must follow the uexp."""
    if old_uexp_len == new_uexp_len:
        return
    ua = bytearray(_read(ua_path))
    needle = struct.pack("<q", old_uexp_len - 4)
    hits = [i for i in range(len(ua) - 8) if bytes(ua[i:i + 8]) == needle]
    if len(hits) != 1:
        raise BuildError("M3", "SerialSize(%d) hit %d times in %s -- refusing a blind patch"
                         % (old_uexp_len - 4, len(hits), os.path.basename(ua_path)))
    struct.pack_into("<q", ua, hits[0], new_uexp_len - 4)
    with open(ua_path, "wb") as f:
        f.write(bytes(ua))


def _assert_inplace_rows(before: bytes, after: bytes, spec: TableSpec,
                         indices: Sequence[int], label: str, log: Log) -> None:
    """Only the addressed rows may differ (same length, same count, trailer intact)."""
    if len(before) != len(after):
        raise BuildError("M3", "%s: in-place edit changed the uexp length (%d -> %d)"
                         % (label, len(before), len(after)))
    n = struct.unpack_from("<I", before, spec.count_off)[0]
    if struct.unpack_from("<I", after, spec.count_off)[0] != n:
        raise BuildError("M3", "%s: in-place edit changed the row count" % label)
    if after[spec.rows_off + spec.stride * n:] != TRAILER:
        raise BuildError("M3", "%s: trailer is gone after the in-place edit" % label)
    allowed = set()
    for i in indices:
        base = spec.rows_off + spec.stride * i
        allowed |= set(range(base, base + spec.stride))
    bad = [i for i in range(len(before)) if before[i] != after[i] and i not in allowed]
    if bad:
        raise BuildError("M3", "%s: %d byte(s) changed outside the edited row(s) "
                               "(first offsets %s)" % (label, len(bad), bad[:10]))
    log("M3", "  IN-PLACE OK  %s: rows %s rewritten, uexp %d B unchanged"
        % (label, list(indices)[:8], len(before)))


# --------------------------------------------------------------------------
# engine
# --------------------------------------------------------------------------
@dataclass
class ModEntry:
    name: str
    kind: str
    folder: str
    root: str                       # absolute folder that owns the mod's files
    manifest_rel: str               # path of the mod manifest, relative to -Mods
    manifest: Dict
    files: List[str] = field(default_factory=list)          # legacy-relative
    tables: Dict[str, str] = field(default_factory=dict)    # tag -> mod's uasset path
    ops: Dict[str, Dict[str, List[int]]] = field(default_factory=dict)


class MergeEngine:
    def __init__(self, mods_dir: str, base_paks: str, out_dir: str,
                 selected_mods: Optional[Sequence[str]], log: Log, kit: Kit,
                 keep_work: bool = False):
        self.mods_dir = os.path.abspath(mods_dir)
        self.base_paks_arg = base_paks
        self.out_dir = os.path.abspath(out_dir)
        self.select = [s for s in (selected_mods or []) if s]
        self.log = log
        self.kit = kit
        self.keep_work = keep_work
        self.work = os.path.join(self.out_dir, WORK_DIRNAME)
        self.legacy = os.path.join(self.work, "legacy")
        self.mods: List[ModEntry] = []
        self.gates: Dict[str, Dict] = {}
        self.conflicts: List[str] = []
        self.da_out: Dict[str, str] = {}          # tag -> merged uasset (in work/da)
        self.da_rel: Dict[str, str] = {}          # tag -> legacy rel path
        self.da_counts: Dict[str, Dict] = {}      # tag -> {native, final, appended, modified, deleted}
        self.appends: Dict[str, List[Tuple[int, List[BgRow]]]] = {}   # tag -> [(start, rows)]
        self.files: List[str] = []
        self.file_owner: Dict[str, str] = {}      # rel -> mod name
        self.file_src: Dict[str, str] = {}        # rel -> absolute source path
        self.base_profile: Dict[str, str] = {}    # tag -> base uasset
        self.base_native_count: Dict[str, int] = {}
        self.gp = None                            # config.GamePaths of the clean base
        self.container: Dict = {}
        self.ledger: Dict = {}
        self.t0 = time.time()

    # ---------------- plumbing ----------------
    def gate(self, gid: str, ok: bool, detail: str, fatal: bool = True,
             stage: str = "M3") -> None:
        self.gates[gid] = {"ok": bool(ok), "detail": detail}
        self.log("GATE", "%s %s  %s" % (gid, "PASS" if ok else "FAIL", detail))
        if not ok and fatal:
            raise BuildError(stage, "gate %s failed" % gid, detail)

    def _rel(self, *parts: str) -> str:
        return os.path.join(self.work, *parts)

    # ---------------- M0: inputs ----------------
    def m0_inputs(self) -> None:
        log = self.log
        idx_path = os.path.join(self.mods_dir, "manifest.json")
        if not os.path.isfile(idx_path):
            raise BuildError("M0", "index manifest not found: %s" % idx_path,
                             "pass -Mods <folder containing manifest.json>")
        try:
            idx = json.loads(_read(idx_path).decode("utf-8-sig"))
        except Exception as e:
            raise BuildError("M0", "index manifest is not valid JSON: %s" % idx_path, str(e))
        items = idx.get("mods")
        if not isinstance(items, list) or not items:
            raise BuildError("M0", "index manifest has no 'mods' list", idx_path)

        seen: Dict[str, str] = {}
        for item in items:
            if not isinstance(item, dict) or not item.get("manifest"):
                raise BuildError("M0", "index entry without a 'manifest' path: %r" % (item,))
            rel = _safe_rel(str(item["manifest"]))
            mpath = os.path.join(self.mods_dir, *rel.split("/"))
            if not os.path.isfile(mpath):
                raise BuildError("M0", "mod manifest listed in the index does not exist: %s" % rel,
                                 "index = %s" % idx_path)
            try:
                man = json.loads(_read(mpath).decode("utf-8-sig"))
            except Exception as e:
                raise BuildError("M0", "mod manifest is not valid JSON: %s" % rel, str(e))
            name = str(man.get("name") or item.get("name") or "").strip()
            if not name:
                raise BuildError("M0", "mod manifest has no 'name': %s" % rel)
            if name in seen:
                raise BuildError("M0", "two mods share the name %r (%s and %s)"
                                 % (name, seen[name], rel))
            seen[name] = rel
            kind = str(man.get("kind") or "").strip()
            if kind not in KINDS:
                raise BuildError("M0", "mod %r has kind=%r; expected one of %s"
                                 % (name, kind, ", ".join(KINDS)))
            folder = str(man.get("folder") or os.path.dirname(rel) or ".").strip()
            root = os.path.normpath(os.path.join(self.mods_dir, *folder.split("/")))
            if not os.path.isdir(root):
                raise BuildError("M0", "mod %r declares folder=%r but %s is not a directory"
                                 % (name, folder, root))
            if not os.path.normpath(os.path.join(self.mods_dir, *rel.split("/"))).startswith(root):
                log("M0", "NOTE: mod %r lives in folder %r but its manifest is at %r"
                    % (name, folder, rel))
            self.mods.append(ModEntry(name=name, kind=kind, folder=folder, root=root,
                                      manifest_rel=rel, manifest=man))

        # selection
        if self.select:
            want = {s.lower() for s in self.select}
            have = {m.name.lower(): m for m in self.mods}
            missing = sorted(want - set(have))
            if missing:
                raise BuildError("M0", "requested mod(s) are not in the index: %s"
                                 % ", ".join(missing),
                                 "available: %s" % ", ".join(m.name for m in self.mods))
            self.mods = [m for m in self.mods if m.name.lower() in want]

        for m in self.mods:
            self._load_mod(m)
        log("M0", "index: %d mod(s) selected of %d listed -- %s"
            % (len(self.mods), len(items),
               ", ".join("%s(%s)" % (m.name, m.kind) for m in self.mods)))
        self.gate("M0", True,
                  "index %s: %d mod(s) selected [%s]; every manifest parsed, folder resolved, "
                  "DA pair(s) and declared file(s) present"
                  % (os.path.relpath(idx_path, self.mods_dir) if idx_path else "-",
                     len(self.mods),
                     ", ".join("%s(%s)" % (m.name, m.kind) for m in self.mods)), stage="M0")

    def _load_mod(self, m: ModEntry) -> None:
        man = m.manifest
        log = self.log
        # ---- targets (da_edit) ----
        targets = man.get("targets") or {}
        if not isinstance(targets, dict):
            raise BuildError("M0", "mod %r: 'targets' must be an object" % m.name)
        for tag, spec_ops in targets.items():
            if tag not in TABLE_SPECS:
                raise BuildError("M0", "mod %r targets the unknown table %r" % (m.name, tag),
                                 "supported tables: %s" % ", ".join(TABLE_FILENAMES))
            if not isinstance(spec_ops, dict):
                raise BuildError("M0", "mod %r: targets.%s must be an object" % (m.name, tag))
            m.ops.setdefault(tag, {op: [] for op in OPS})
            for op, rows in spec_ops.items():
                if op not in OPS:
                    raise BuildError("M0", "mod %r: targets.%s.%s is not a known operation"
                                     % (m.name, tag, op),
                                     "expected one of %s" % ", ".join(OPS))
                if not isinstance(rows, list) or any(not isinstance(r, int) for r in rows):
                    raise BuildError("M0", "mod %r: targets.%s.%s must be a list of integers"
                                     % (m.name, tag, op))
                m.ops[tag][op] = sorted({int(r) for r in rows})
        if m.kind == "ui_text" and any(any(v for v in ops.values()) for ops in m.ops.values()):
            raise BuildError("M0", "mod %r is kind=ui_text but declares row edits in 'targets'"
                             % m.name)
        if m.kind == "da_edit" and not m.ops:
            raise BuildError("M0", "mod %r is kind=da_edit but declares no 'targets'" % m.name)

        # ---- the mod's own DA table pairs (row source) ----
        found = _list_files(m.root)
        for tag in TABLE_SPECS:
            hits = [rel for rel in found
                    if os.path.splitext(os.path.basename(rel))[0] == tag
                    and rel.endswith(".uasset")]
            if not hits:
                continue
            if len(hits) > 1:
                raise BuildError("M0", "mod %r ships %d copies of %s.uasset (%s)"
                                 % (m.name, len(hits), tag, ", ".join(sorted(hits))))
            m.tables[tag] = found[hits[0]]
        for tag, ops in m.ops.items():
            if any(ops.values()) and tag not in m.tables:
                raise BuildError("M0", "mod %r targets %s but ships no %s.uasset/.uexp"
                                 % (m.name, tag, tag))

        # ---- files (MANDATORY for every kind: it declares the mod's change scope) ----
        declared = man.get("files")
        if declared is None:
            raise BuildError("M0", "mod %r has no 'files' list" % m.name,
                             "every mod -- da_edit and ui_text alike -- must declare the asset "
                             "files it contributes relative to its folder; use [] when it "
                             "contributes none (the DA tables it targets are row sources, not "
                             "files)")
        if not isinstance(declared, list) or any(not isinstance(x, str) for x in declared):
            raise BuildError("M0", "mod %r: 'files' must be a list of strings" % m.name)
        for rel in declared:
            r = _safe_rel(rel)
            # `scriptobjects.bin` is never carried into the merged container (confirmed with
            # Xenon-XG 2026-09-27): `retoc to-zen` ignores it, and the patch container needs
            # only ExportBundleData + ContainerHeader.  Declaring it is not an error -- it is
            # skipped loudly so an old manifest cannot smuggle it back in.
            if os.path.basename(r).lower() == "scriptobjects.bin":
                log("M0", "NOTE: mod %r lists scriptobjects.bin -- SKIPPED (the merged "
                          "container never carries script objects)" % m.name)
                continue
            if r not in found:
                raise BuildError("M0", "mod %r declares a file that does not exist: %s"
                                 % (m.name, r), "looked in %s" % m.root)
            stem = os.path.splitext(os.path.basename(r))[0]
            if stem in TABLE_FILENAMES:
                log("M0", "NOTE: mod %r lists the DA table %s as a plain file -- it is "
                          "merged row by row, not copied" % (m.name, stem))
                continue
            m.files.append(r)
        for r in m.files:
            if "Content" not in r.split("/"):
                raise BuildError("M0", "mod %r: %s is not a legacy-relative asset path"
                                 % (m.name, r),
                                 "expected something like CalaPlayer/Content/.../X.uasset")
        m.files = sorted(set(m.files))
        log("M0", "mod %-18s kind=%-8s rows=%s files=%d"
            % (m.name, m.kind, {t: {o: len(v) for o, v in ops.items() if v}
                                for t, ops in m.ops.items()} or "{}", len(m.files)))

    # ---------------- M1: conflicts ----------------
    def m1_conflicts(self) -> None:
        self.log("M1", "conflict check over %d mod(s)" % len(self.mods))
        claims: Dict[Tuple[str, int], List[Tuple[str, str]]] = {}
        files: Dict[str, List[Tuple[str, str]]] = {}
        for m in self.mods:
            for tag, ops in m.ops.items():
                for op, rows in ops.items():
                    for r in rows:
                        claims.setdefault((tag, r), []).append((m.name, op))
            for rel in m.files:
                files.setdefault(rel.lower(), []).append((m.name, rel))

        conflicts: List[str] = []
        for (tag, row), who in sorted(claims.items()):
            mods = sorted({n for n, _op in who})
            if len(mods) > 1:
                conflicts.append("%s 第 %d 行: %s" % (tag, row, " 与 ".join(mods))
                                 + " 同时声明 (%s)"
                                 % ", ".join("%s=%s" % (n, op) for n, op in who))
            elif len(who) > 1:
                conflicts.append("%s 第 %d 行: 同一个 Mod %s 重复声明 (%s)"
                                 % (tag, row, mods[0], ", ".join(op for _n, op in who)))
        for _key, owners in sorted(files.items()):
            names = sorted({n for n, _rel in owners})
            if len(names) > 1:
                conflicts.append("文件 %s: %s 都想提供" % (owners[0][1], " 与 ".join(names)))

        # deleted_rows shifts every later index -> it may not share a table with anyone
        for m in self.mods:
            for tag, ops in m.ops.items():
                if not ops.get("deleted_rows"):
                    continue
                others = [o.name for o in self.mods
                          if o is not m and any(v for v in (o.ops.get(tag) or {}).values())]
                if others:
                    conflicts.append("%s: %s 声明了 deleted_rows，而 %s 也在改这张表"
                                     % (tag, m.name, " 与 ".join(others))
                                     + "（删行会让后面所有行号平移）")

        self.conflicts = conflicts
        if conflicts:
            self.gate("M1", False,
                      "%d conflict(s) between mods -- nothing was merged" % len(conflicts),
                      fatal=True, stage="M1")
        self.gate("M1", True, "no conflict: %d row claim(s) over %d table(s), %d file(s), "
                              "all disjoint"
                  % (len(claims), len({t for t, _r in claims}), len(files)), stage="M1")

    # ---------------- M2: clean base ----------------
    def m2_base(self) -> None:
        log = self.log
        gp = config.discover_game(self.base_paks_arg)
        self.gp = gp
        base_paks = os.path.join(self.work, "base_paks")
        ensure_dir(base_paks)
        n_native = 0
        for f in sorted(os.listdir(gp.paks_dir)):
            src = os.path.join(gp.paks_dir, f)
            if not os.path.isfile(src):
                continue
            if config.looks_like_patch(f, gp.container_base):
                continue
            hardlink_or_copy(src, os.path.join(base_paks, f), log, "M2")
            n_native += 1
        if not os.path.isfile(os.path.join(base_paks, "global.utoc")):
            raise BuildError("M2", "the clean base has no global.utoc", gp.paks_dir)
        log("M2", "clean base: %d container file(s) staged from %s (patch files excluded)"
            % (n_native, gp.paks_dir))

        raw = self._rel("base_legacy")
        _to_legacy_raw(self.kit, base_paks, raw, "DA_", log, "M2")
        found = _list_files(raw)
        for tag in TABLE_SPECS:
            rels = [r for r in found
                    if os.path.splitext(os.path.basename(r))[0] == tag
                    and r.endswith((".uasset", ".uexp"))]
            ua = [r for r in rels if r.endswith(".uasset")]
            if len(ua) != 1:
                raise BuildError("M2", "could not extract the native %s from the clean base "
                                       "(%d hit(s))" % (tag, len(ua)),
                                 "base = %s" % gp.paks_dir)
            self.base_profile[tag] = found[ua[0]]
            self.da_rel[tag] = ua[0]
            self.base_native_count[tag] = table_rows(_read(os.path.splitext(self.base_profile[tag])[0]
                                                           + ".uexp"), TABLE_SPECS[tag])
        log("M2", "native row counts: %s"
            % ", ".join("%s=%d" % (t, self.base_native_count[t]) for t in TABLE_SPECS))
        self.gate("M2", True, "clean base extracted: 4 DA table(s) + native row counts [%s]"
                  % ", ".join("%s=%d" % (t, self.base_native_count[t]) for t in TABLE_SPECS),
                  stage="M2")

    # ---------------- M3: DA row merge ----------------
    def _extract_rows(self, m: ModEntry, tag: str, indices: Sequence[int]) -> List[BgRow]:
        """Read the addressed rows out of the mod's own table as (key, pkg, obj, @30)."""
        spec = TABLE_SPECS[tag]
        ua = m.tables[tag]
        ux = os.path.splitext(ua)[0] + ".uexp"
        uexp = _read(ux)
        n = table_rows(uexp, spec)
        names = DA.probe_names(self.kit, ua, self.log, "M3")
        imports = DA.parse_imports(self.kit.da(["imports", ua, self.kit.usmap],
                                               self.log, "M3").out)
        out: List[BgRow] = []
        for i in indices:
            if not (0 <= i < n):
                raise BuildError("M3", "mod %r: %s row %d is out of range (the mod's table has "
                                       "%d rows)" % (m.name, tag, i, n))
            f = _row_indices(uexp, spec, i)
            vals = {}
            for what, _delta in spec.slots:
                idx = f[what]
                if not (0 <= idx < len(names)):
                    raise BuildError("M3", "mod %r: %s row %d %s FName index %d is out of "
                                           "range (%d names)"
                                     % (m.name, tag, i, what, idx, len(names)))
                vals[what] = names[idx]
            row = BgRow(key=vals["key"], pkg=vals["pkg"], obj=vals["obj"])
            if spec.ref_off is not None:
                ref = f["ref"]
                if ref >= 0:
                    raise BuildError("M3", "mod %r: %s row %d has @30=%d; a merged background "
                                           "row must carry a preview material import"
                                     % (m.name, tag, i, ref))
                imp_idx = -ref - 1
                cls = str(imports[imp_idx][2]) if 0 <= imp_idx < len(imports) else "?"
                if cls != "MaterialInstanceConstant":
                    raise BuildError("M3", "mod %r: %s row %d @30=%d resolves to a %s, not a "
                                           "MaterialInstanceConstant"
                                     % (m.name, tag, i, ref, cls),
                                     "the @30 field is a hard reference; never fabricate it")
                row.mi_obj = str(imports[imp_idx][3])
                row.mi_pkg = import_pkg_path(imports, imp_idx)
                row.mi_ref = ref
            out.append(row)
            self.log("M3", "  %s[%d] <- %s key=%r pkg=%s obj=%s%s"
                     % (tag, i, m.name, row.key, row.pkg, row.obj,
                        ("  @30=%d (%s)" % (row.mi_ref, row.mi_obj)) if spec.ref_off is not None
                        else ""))
        return out

    def _resolve_refs(self, tag: str, cur_ua: str, rows: Sequence[BgRow],
                      mod_imports: Sequence[Tuple], log: Log) -> str:
        """Reuse the native import index when it is unchanged, else `bgref` a fresh one."""
        cur_imp = DA.parse_imports(self.kit.da(["imports", cur_ua, self.kit.usmap],
                                               log, "M3").out)
        todo: List[BgRow] = []
        for r in rows:
            imp_idx = -r.mi_ref - 1
            if 0 <= imp_idx < len(cur_imp) and imp_idx < len(mod_imports) \
                    and tuple(cur_imp[imp_idx]) == tuple(mod_imports[imp_idx]):
                continue                      # native MI: the index did not move
            todo.append(r)
        if not todo:
            return cur_ua
        before = cur_ua
        cur_ua = DA.append_mi_refs(self.kit, cur_ua, self._rel("bgref_%s" % tag), todo, log, "M3")
        for r in todo:
            log("M3", "  %s: new MI import for %s -> @30=%d" % (tag, r.mi_obj, r.mi_ref))
        return cur_ua

    def _merge_table(self, tag: str, log: Log) -> None:
        spec = TABLE_SPECS[tag]
        native = self.base_native_count[tag]
        base_ua = self.base_profile[tag]
        cur_ua = os.path.join(self._rel("da"), os.path.basename(base_ua))
        ensure_dir(os.path.dirname(cur_ua))
        shutil.copy2(base_ua, cur_ua)
        shutil.copy2(os.path.splitext(base_ua)[0] + ".uexp", os.path.splitext(cur_ua)[0] + ".uexp")
        count = native
        stats = {"native": native, "final": native, "appended": 0, "modified": 0, "deleted": 0}
        deletions: List[int] = []

        for m in self.mods:
            ops = m.ops.get(tag)
            if not ops:
                continue
            mod_imports = DA.parse_imports(self.kit.da(
                ["imports", m.tables[tag], self.kit.usmap], log, "M3").out)

            # ---- modified_rows: rewrite the addressed native rows in place ----
            if ops["modified_rows"]:
                rows = self._extract_rows(m, tag, ops["modified_rows"])
                for i in ops["modified_rows"]:
                    if i >= native:
                        raise BuildError("M3", "mod %r: %s modified_rows contains %d, which is "
                                               "not a native row (native count = %d)"
                                         % (m.name, tag, i, native))
                needed: List[str] = []
                for r in rows:
                    for v in (r.key, r.pkg, r.obj):
                        if v not in needed:
                            needed.append(v)
                cur_ua, idx = DA.add_names(self.kit, cur_ua, self._rel("addname_%s" % tag),
                                           needed, log, "M3")
                if spec.ref_off is not None:
                    cur_ua = self._resolve_refs(tag, cur_ua, rows, mod_imports, log)
                ux = os.path.splitext(cur_ua)[0] + ".uexp"
                before = _read(ux)
                data = bytearray(before)
                for r, i in zip(rows, ops["modified_rows"]):
                    off = spec.rows_off + spec.stride * i
                    e = bytearray(data[off:off + spec.stride])
                    for what, delta in spec.slots:
                        struct.pack_into("<I", e, delta, idx[getattr(r, what)])
                    if spec.ref_off is not None:
                        struct.pack_into("<i", e, spec.ref_off, r.mi_ref)
                    data[off:off + spec.stride] = e
                with open(ux, "wb") as f:
                    f.write(bytes(data))
                _assert_inplace_rows(before, bytes(data), spec, ops["modified_rows"],
                                     "%s modified by %s" % (tag, m.name), log)
                stats["modified"] += len(ops["modified_rows"])

            # ---- appended_rows ----
            if ops["appended_rows"]:
                rows = self._extract_rows(m, tag, ops["appended_rows"])
                for i in ops["appended_rows"]:
                    if i < native:
                        raise BuildError("M3", "mod %r: %s appended_rows contains %d, but row "
                                               "%d already exists in the native table "
                                               "(native count = %d)"
                                         % (m.name, tag, i, i, native),
                                         "an appended row must be >= the native row count")
                ux = os.path.splitext(cur_ua)[0] + ".uexp"
                before = _read(ux)
                if tag == "DA_Backgrounds":
                    cur_ua = self._resolve_refs(tag, cur_ua, rows, mod_imports, log)
                    ux = os.path.splitext(cur_ua)[0] + ".uexp"
                    before = _read(ux)
                    cur_ua = DA.append_bg_rows(self.kit, cur_ua, self._rel("append_%s" % tag),
                                               rows, count, log, "M3", allow_uasset_growth=True)
                else:
                    cur_ua = DA.append_audio_rows(self.kit, cur_ua, self._rel("append_%s" % tag),
                                                  [AudioRow(tag, r.key, r.pkg, r.obj)
                                                   for r in rows], log, "M3")
                after = _read(os.path.splitext(cur_ua)[0] + ".uexp")
                DA.assert_append_only(before, after, spec.count_off, spec.stride, spec.rows_off,
                                      len(rows), count, "%s (+%d from %s)"
                                      % (tag, len(rows), m.name), log, "M3")
                self.appends.setdefault(tag, []).append((count, rows))
                count += len(rows)
                stats["appended"] += len(rows)
                log("M3", "  %s: %s appended %d row(s) -> %d"
                    % (tag, m.name, len(rows), count))

            if ops["deleted_rows"]:
                deletions.extend(ops["deleted_rows"])

        # ---- deleted_rows (applied last; exclusively owned, see M1) ----
        if deletions:
            for i in deletions:
                if i >= native:
                    raise BuildError("M3", "%s deleted_rows contains %d, which is not a native "
                                           "row (native count = %d)" % (tag, i, native))
            ux = os.path.splitext(cur_ua)[0] + ".uexp"
            before = _read(ux)
            keep = [i for i in range(count) if i not in set(deletions)]
            data = bytearray(before[:spec.rows_off])
            for i in keep:
                off = spec.rows_off + spec.stride * i
                data += before[off:off + spec.stride]
            data += TRAILER
            struct.pack_into("<I", data, spec.count_off, len(keep))
            with open(ux, "wb") as f:
                f.write(bytes(data))
            _set_serial_size(cur_ua, len(before), len(data))
            count = len(keep)
            stats["deleted"] = len(deletions)
            log("M3", "  %s: %d native row(s) deleted by %s -> %d rows"
                % (tag, len(deletions), ", ".join(m.name for m in self.mods
                                                  if (m.ops.get(tag) or {}).get("deleted_rows")),
                   count))

        stats["final"] = count
        self.da_counts[tag] = stats
        self.da_out[tag] = cur_ua

    def m3_rows(self) -> None:
        log = self.log
        tags = [t for t in TABLE_SPECS
                if any(any(v for v in (m.ops.get(t) or {}).values()) for m in self.mods)]
        if not tags:
            self.gate("M3", True, "no mod edits a DA table -- nothing to merge row by row")
            return
        for tag in tags:
            self._merge_table(tag, log)
        detail = " | ".join("%s %d->%d (+%d/-%d/~%d)"
                            % (t, self.da_counts[t]["native"], self.da_counts[t]["final"],
                               self.da_counts[t]["appended"], self.da_counts[t]["deleted"],
                               self.da_counts[t]["modified"])
                            for t in tags)
        self.gate("M3", True, "DA row merge: " + detail, stage="M3")

    def m6_append_only(self) -> None:
        """Names/ImportMap may only grow at the end -- old indices must stay put."""
        if not self.da_out:
            self.gate("M6", True, "no DA table was rewritten")
            return
        for tag, cur_ua in self.da_out.items():
            DA.assert_name_import_append_only(self.kit, self.base_profile[tag], cur_ua,
                                              "%s (%s + mods)" % (tag, tag), self.log, "M6")
        self.gate("M6", True, "append-only proven at the semantic level for %d table(s): every "
                              "native name/import kept its index" % len(self.da_out),
                  stage="M6")

    # ---------------- M4: files ----------------
    def m4_files(self) -> None:
        log = self.log
        log("M4", "merging the mods' asset files into one legacy tree (%d file(s))"
            % sum(len(m.files) for m in self.mods))
        ensure_dir(self.legacy)
        staged = 0
        for m in self.mods:
            for rel in m.files:
                dst = os.path.join(self.legacy, *rel.split("/"))
                if rel in self.file_owner:
                    raise BuildError("M4", "%s is provided by both %s and %s"
                                     % (rel, self.file_owner[rel], m.name))
                hardlink_or_copy(os.path.join(m.root, *rel.split("/")), dst, log, "M4")
                self.file_owner[rel] = m.name
                self.file_src[rel] = os.path.join(m.root, *rel.split("/"))
                self.files.append(rel)
                staged += 1
        for tag, ua in self.da_out.items():
            rel = self.da_rel[tag]
            dst = os.path.join(self.legacy, *rel.split("/"))
            ensure_dir(os.path.dirname(dst))
            shutil.copy2(ua, dst)
            shutil.copy2(os.path.splitext(ua)[0] + ".uexp", os.path.splitext(dst)[0] + ".uexp")
            self.files.append(rel)
        self.gate("M4", True, "%d file(s) merged into one legacy tree (%d from mods, %d DA "
                              "table(s)); every relative path preserved"
                  % (len(self.files), staged, len(self.da_out)), stage="M4")

    # ---------------- M5: pack + read back ----------------
    def m5_pack(self) -> None:
        log = self.log
        stem = os.path.join(self.out_dir, self.gp.container_base + config.PATCH_SUFFIX)
        out_utoc = stem + ".utoc"
        for ext in ("pak", "ucas", "utoc"):          # never leave a stale container behind
            p = stem + "." + ext
            if os.path.isfile(p):
                os.remove(p)
        self.kit.to_zen(self.legacy, out_utoc, log, "M5")
        for ext in ("pak", "ucas", "utoc"):
            if not os.path.isfile(stem + "." + ext):
                raise BuildError("M5", "retoc produced no .%s" % ext, stem + "." + ext)
        self.container = {
            "base": os.path.basename(stem),
            "files": {e: {"path": stem + "." + e, "bytes": os.path.getsize(stem + "." + e),
                          "sha256": sha256_file(stem + "." + e),
                          "sha16": sha16(stem + "." + e)} for e in ("pak", "ucas", "utoc")},
        }
        info = self.kit.info(out_utoc, log, "M5")
        for line in info.splitlines():
            if "chunks:" in line or "packages:" in line:
                log("M5", "  retoc info: %s" % line.strip())

        # ---- chunk ledger (same discipline as the single-mod A5 gate) ----
        native_utoc = os.path.join(self.gp.paks_dir, self.gp.container_base + ".utoc")
        base_ids = {cid for cid, k in self.kit.list_chunks(native_utoc, log, "M5")
                    if k == "ExportBundleData"}
        mine = self.kit.list_chunks(out_utoc, log, "M5")
        bundles = [cid for cid, k in mine if k == "ExportBundleData"]
        hit = sorted({cid for cid in bundles if cid in base_ids})
        new = sorted({cid for cid in bundles if cid not in base_ids})
        other = sorted({k for _cid, k in mine if k != "ExportBundleData"})
        expect_override = self._expected_overrides(log)
        self.ledger = {"native_chunks": len(base_ids), "our_chunks": len(mine),
                       "new": len(new), "override": len(hit),
                       "expected_override": len(expect_override),
                       "override_of": sorted(expect_override),
                       "other_chunk_kinds": other}
        log("M5", "  ledger: %d brand-new package(s), %d deliberate override(s) "
                  "(expected %d), other chunk kinds: %s"
            % (len(new), len(hit), len(expect_override), ", ".join(other) or "-"))
        if len(hit) != len(expect_override):
            raise BuildError("M5", "chunk ledger mismatch: %d override(s) in the container but "
                                   "%d expected" % (len(hit), len(expect_override)),
                             "expected overrides: %s" % ", ".join(sorted(expect_override)))

        # ---- read the delivered container back ----
        pure = os.path.join(self.work, "stage_pure")
        ensure_dir(pure)
        for f in ("global.utoc", "global.ucas", "global.pak"):
            src = os.path.join(self.gp.paks_dir, f)
            if os.path.isfile(src):
                hardlink_or_copy(src, os.path.join(pure, f), log, "M5")
        for e in ("pak", "ucas", "utoc"):
            hardlink_or_copy(stem + "." + e, os.path.join(pure, os.path.basename(stem) + "." + e),
                             log, "M5")
        rt = os.path.join(self.work, "rt_container")
        self.kit.to_legacy(pure, rt, None, log, "M5")
        found = _list_files(rt)

        checked_rows: List[str] = []
        for tag, ua in self.da_out.items():
            rel = self.da_rel[tag]
            got_ua = found.get(rel)
            got_ux = found.get(os.path.splitext(rel)[0] + ".uexp")
            if not (got_ua and got_ux):
                raise BuildError("M5", "%s did not come back out of the merged container" % tag)
            spec = TABLE_SPECS[tag]
            data = _read(got_ux)
            n = table_rows(data, spec)
            if n != self.da_counts[tag]["final"]:
                raise BuildError("M5", "%s: the container holds %d rows, we merged %d"
                                 % (tag, n, self.da_counts[tag]["final"]))
            names = DA.probe_names(self.kit, got_ua, log, "M5")
            imports = DA.parse_imports(self.kit.da(["imports", got_ua, self.kit.usmap],
                                                   log, "M5").out)
            for start, batch in (self.appends.get(tag) or []):
                for i, row in enumerate(batch):
                    at = start + i
                    f = _row_indices(data, spec, at)
                    for what, _delta in spec.slots:
                        idx = f[what]
                        if not (0 <= idx < len(names)) or names[idx] != getattr(row, what):
                            raise BuildError("M5", "%s row %d %s did not survive the round-trip"
                                             % (tag, at, what),
                                             "got index %d" % idx)
                    if spec.ref_off is not None:
                        # the FPackageIndex must be exactly the row we merged -- a moved
                        # `@30` is the failure mode that once Fatal-crashed the game.
                        if row.mi_ref and f["ref"] != row.mi_ref:
                            raise BuildError("M5", "%s row %d: @30 came back as %d, merged as %d"
                                             % (tag, at, f["ref"], row.mi_ref))
                        # class/object only resolve for references that live in OUR container;
                        # a reference into a native package is unresolved here on purpose
                        # (the read-back container carries global.* + our _P only).
                        ours = row.mi_pkg and \
                            config.legacy_rel_from_pkg(row.mi_pkg) in self.file_owner
                        if ours:
                            imp_idx = -f["ref"] - 1
                            if not (0 <= imp_idx < len(imports)) or \
                                    str(imports[imp_idx][2]) != "MaterialInstanceConstant":
                                raise BuildError("M5", "%s row %d: @30=%d does not resolve to a "
                                                       "MaterialInstanceConstant"
                                                 % (tag, at, f["ref"]))
                            if str(imports[imp_idx][3]) != row.mi_obj:
                                raise BuildError("M5", "%s row %d: @30 resolves to %s, expected %s"
                                                 % (tag, at, imports[imp_idx][3], row.mi_obj))
                    checked_rows.append("%s#%d='%s'" % (tag, at, row.key))
            log("M5", "  read-back %s: %d rows, names=%d imports=%d"
                % (tag, n, len(names), len(imports)))

        missing = [rel for rel in self.files
                   if rel not in found and os.path.splitext(rel)[0] + ".uexp" not in found]
        if missing:
            raise BuildError("M5", "%d merged file(s) are missing from the container: %s"
                             % (len(missing), ", ".join(missing[:6])))
        # a mod's own asset bytes must come back out of our container unchanged
        da_uexp = {os.path.splitext(self.da_rel[t])[0] + ".uexp" for t in self.da_out}
        byte_checked = [rel for rel in self.files
                        if rel.endswith(".uexp") and rel not in da_uexp
                        and self.file_src.get(rel) and rel in found]
        bad = [rel for rel in byte_checked
               if _read(found[rel]) != _read(self.file_src[rel])]
        if bad:
            raise BuildError("M5", "%d merged .uexp did not survive the container byte-for-byte: "
                                   "%s" % (len(bad), ", ".join(bad[:6])),
                             "the merged container does not carry the mod's own bytes")
        log("M5", "  byte check: %d mod .uexp read back byte-identical" % len(byte_checked))
        # retoc's container encoding is NOT byte-deterministic (same inputs -> different
        # .ucas/.utoc hashes, identical payload), so identity has to come from the content:
        lines = []
        for rel in sorted(self.files):
            p = found.get(rel)
            if p and os.path.isfile(p):
                lines.append("%s %s" % (rel, sha256_file(p)))
        self.container["content_sha256"] = hashlib.sha256(
            "\n".join(lines).encode("utf-8")).hexdigest()
        log("M5", "  content fingerprint (%d file(s)): %s"
            % (len(lines), self.container["content_sha256"][:32]))
        self.gate("M5", True,
                  "packed %s (%d B ucas) + read back: DA rows %s; %d merged file(s) present "
                  "(%d mod .uexp byte-identical); ledger %d new / %d override"
                  % (self.gp.container_base + config.PATCH_SUFFIX,
                     self.container["files"]["ucas"]["bytes"],
                     ("[" + " ".join(checked_rows[:8]) + (" …" if len(checked_rows) > 8 else "") + "]")
                     if checked_rows else "(none)",
                     len(self.files), len(byte_checked), len(new), len(hit)), stage="M5")

    def _expected_overrides(self, log: Log) -> set:
        """Our staged packages that also exist in the clean base (i.e. real overrides)."""
        rels = [self.da_rel[t] for t in self.da_out] + [r for r in self.files
                                                        if r.endswith(".uasset")]
        out = set()
        probe_root = os.path.join(self.work, "probe_native")
        cache: Dict[str, str] = {}
        base_paks = os.path.join(self.work, "base_paks")
        for rel in rels:
            stem = os.path.splitext(os.path.basename(rel))[0]
            od = cache.get(stem)
            if od is None:
                od = os.path.join(probe_root, "f_%02d" % len(cache))
                ensure_dir(od)
                self.kit.to_legacy(base_paks, od, stem, log, "M5")
                cache[stem] = od
            if os.path.isfile(os.path.join(od, *rel.split("/"))):
                out.add(rel)
        for tag in self.da_out:                     # only the DA tables we really ship
            out.add(self.da_rel[tag])
        return out

    # ---------------- driver ----------------
    def run(self) -> MergeReport:
        log = self.log
        ensure_dir(self.out_dir)
        try:
            self.m0_inputs()
            self.m1_conflicts()
            self.m2_base()
            self.m3_rows()
            self.m6_append_only()
            self.m4_files()
            self.m5_pack()
            return self.report(True)
        except BuildError as e:
            log("ERR", str(e))
            return self.report(False, str(e))
        finally:
            if not self.keep_work:
                rmtree(self.work)

    def report(self, ok: bool, error: str = "") -> MergeReport:
        return MergeReport(
            ok=ok, error=error, seconds=time.time() - self.t0,
            version=tool_version(),
            params={"mods": self.mods_dir, "base": self.base_paks_arg, "out": self.out_dir,
                    "select": self.select, "keep_work": self.keep_work,
                    "kit": self.kit.root},
            resolved={"paks_dir": getattr(getattr(self, "gp", None), "paks_dir", ""),
                      "container_base": getattr(getattr(self, "gp", None), "container_base", ""),
                      "work": self.work},
            selected=[m.name for m in self.mods],
            mods=[{"name": m.name, "kind": m.kind, "version": str(m.manifest.get("version", "")),
                   "author": str(m.manifest.get("author", "")),
                   "folder": m.folder, "manifest": m.manifest_rel,
                   "rows": {t: {o: len(v) for o, v in ops.items() if v}
                            for t, ops in m.ops.items()},
                   "tables": {t: os.path.basename(p) for t, p in m.tables.items()},
                   "files": len(m.files)} for m in self.mods],
            conflicts=list(self.conflicts),
            tables={t: dict(v) for t, v in self.da_counts.items()},
            files=list(self.files),
            gates=dict(self.gates),
            ledger=dict(self.ledger),
            container=dict(self.container),
            work=self.work, out_dir=self.out_dir)


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
def merge_mods(mods_dir: Union[str, Path], base_paks: Union[str, Path], out_dir: Union[str, Path],
               selected_mods: Optional[Sequence[str]] = None, *,
               log: Optional[Log] = None, kit: Optional[Kit] = None,
               keep_work: bool = False) -> MergeReport:
    """Merge every (selected) mod under `mods_dir` into ONE `_P` container in `out_dir`.

    `mods_dir`   folder holding the index manifest (`manifest.json`)
    `base_paks`  the CLEAN game Paks folder (read only; the installed `_P` is ignored)
    `out_dir`    where the merged `_P.{pak,ucas,utoc}` + `merge_report.json` go
    `selected_mods`  None = all mods, else only these mod names (case-insensitive)

    Returns a `MergeReport`; it never raises for a merge-level failure (check `.ok`).
    """
    own_log = log is None
    lg = log or Log(echo=True)
    try:
        k = kit or load_kit(None, None, lg, "M0")
        eng = MergeEngine(str(mods_dir), str(base_paks), str(out_dir),
                          selected_mods, lg, k, keep_work=keep_work)
        rep = eng.run()
    except BuildError as e:
        lg("ERR", str(e))
        rep = MergeReport(ok=False, error=str(e), gates={}, version=tool_version())
    finally:
        if own_log:
            lg.close()
    return rep
