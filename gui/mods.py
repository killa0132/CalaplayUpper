# -*- coding: utf-8 -*-
"""Mod folder discovery for the GUI (CP-40): "auto sniff the mod_src folders".

`core/merger.py` stays strict, and that is deliberate -- it wants ONE `-Mods` root
that holds `manifest.json` (the index), whose entries are relative paths, and every
Mod's `folder` must resolve **relative to that root**.  The GUI is the forgiving
side, so this module turns whatever the user picks into something the merger accepts:

  1. one folder that already has a valid index          -> used as-is (nothing written)
  2. one folder whose Mod folders are its children      -> a fresh index is written there
  3. several `_src` folders (or a parent of them, e.g. `out_patch`) -> the Mods are
     staged (hard-linked) under one throw-away root in %TEMP% + a generated index

Case 1 and 2 are the documented protocol; case 3 exists so `-ExportSrc` output can be
fed in directly ("用生成的 mod_src/ 直接喂给合并模式") without the user having to place
the folders by hand.  Nothing here ever writes inside a Mod's own folder except the
generated index, and the merger still treats the whole tree as read-only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from typing import Dict, List, Optional, Tuple

INDEX = "manifest.json"
KINDS = ("da_edit", "ui_text")
MAX_DEPTH = 6                 # `out_patch/mod_src/X_src/manifest.json` is depth 2
MAX_MODS = 64
#: `out_patch` / `merge_work` are deliberately NOT skipped: picking the material
#: folder (whose child is `out_patch/mod_src/X_src/`) must still find the export.
SKIP_DIRS = {"node_modules", ".git", ".svn", "__pycache__", "$recycle.bin",
             "system volume information", "windows", "program files"}
STAGE_DIRNAME = "cala-mods-root"


# --------------------------------------------------------------------------- util
def spec_dirs(spec: str) -> List[str]:
    """Split "D:\\a; D:\\b" (also commas / newlines) into absolute folders.

    A single existing folder wins outright -- Windows paths happily contain commas.
    """
    s = (spec or "").strip().strip('"')
    if not s:
        return []
    if os.path.isdir(s):
        return [os.path.abspath(s)]
    out: List[str] = []
    for chunk in re.split(r"[;,\n\r]", s):
        c = chunk.strip().strip('"').strip()
        if c:
            out.append(os.path.abspath(c))
    return out


def read_json(path: str):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return json.load(fh), ""
    except Exception as e:  # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)


def write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)


def _posix(p: str) -> str:
    return str(p).replace("\\", "/").strip("/")


def _safe_rel(rel: str) -> bool:
    r = _posix(rel)
    return bool(r) and not r.startswith("/") and ".." not in r.split("/") and ":" not in r


def _link_copy(src: str, dst: str) -> None:
    """Hard link when possible (same volume), copy otherwise."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _sanitize(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", (name or "").strip()).strip("._")
    return s or "mod"


def _scan(base: str) -> List[Tuple[str, str]]:
    """Every `manifest.json` under `base` that is NOT `base`'s own index."""
    out: List[Tuple[str, str]] = []
    base = os.path.abspath(base)
    for dirpath, dirs, files in os.walk(base):
        rel = os.path.relpath(dirpath, base)
        depth = 0 if rel == os.curdir else len(_posix(rel).split("/"))
        if depth >= MAX_DEPTH:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS]
        if INDEX in files and depth >= 1 and len(out) < MAX_MODS * 4:
            out.append((os.path.join(dirpath, INDEX), _posix(os.path.join(rel, INDEX))))
    return sorted(out, key=lambda x: x[1].lower())


def _load(base: str, manifest_abs: str, rel: str) -> Tuple[Optional[Dict], str]:
    """Read one Mod manifest -> an entry dict, or (None, why-not).

    A manifest whose declared `folder` does not resolve under `base` is NOT an error:
    the user may have picked a parent (`out_patch` instead of `out_patch/mod_src`).
    Those mods get re-anchored on the folder their manifest actually lives in and are
    marked `re_anchored`, so they are served by the staging root only -- the merger
    would look for the *declared* folder and would not find it.
    """
    man, err = read_json(manifest_abs)
    if man is None:
        return None, "manifest.json 解析失败（%s）：%s" % (rel, err)
    if not isinstance(man, dict):
        return None, "manifest.json 不是一个 JSON 对象：%s" % rel
    if man.get("tool") and not man.get("name"):
        return None, ""            # the pipeline's own state file, not a Mod -> ignore
    if isinstance(man.get("mods"), list) and not man.get("name"):
        return None, ""            # an index manifest -> not a Mod (ignore quietly)
    name = str(man.get("name") or "").strip()
    kind = str(man.get("kind") or "").strip()
    if not name:
        return None, "manifest.json 里没有 name：%s" % rel
    if kind not in KINDS:
        return None, "kind=%r 不是 %s：%s" % (kind, "/".join(KINDS), rel)
    declared = _posix(man.get("folder") or os.path.dirname(rel))
    re_anchored = False
    if _safe_rel(declared):
        folder_abs = os.path.normpath(os.path.join(base, *declared.split("/")))
    else:
        folder_abs = ""
    if not folder_abs or not os.path.isdir(folder_abs) \
            or not os.path.normpath(manifest_abs).startswith(folder_abs):
        # the declared folder does not exist here: the Mod's own folder is the one
        # holding its manifest (that is also the merger's default for a missing `folder`)
        folder_abs = os.path.dirname(os.path.abspath(manifest_abs))
        declared = _posix(os.path.dirname(rel)) or "."
        re_anchored = True
    return {"name": name, "kind": kind,
            "version": str(man.get("version") or ""), "author": str(man.get("author") or ""),
            "folder": declared, "manifest": rel, "path": manifest_abs,
            "base": base, "folder_abs": folder_abs, "re_anchored": re_anchored,
            "targets": man.get("targets") or {},
            "files": len(man.get("files") or []) if isinstance(man.get("files"), list) else None,
            "exists": True}, ""


def _index_entries(mods: List[Dict]) -> List[Dict]:
    """`{"mods": [...]}` -- sorted by name so the generated index is deterministic."""
    return {"mods": [{"name": m["name"], "manifest": m["manifest"]}
                     for m in sorted(mods, key=lambda x: (x["name"].lower(), x["manifest"]))]}


def _public(mods: List[Dict]) -> List[Dict]:
    keep = ("name", "kind", "version", "author", "folder", "manifest", "exists",
            "targets", "files", "re_anchored")
    return [{k: m.get(k) for k in keep} for m in mods]


def _use_index(base: str, idx: str) -> Optional[Dict]:
    """Case 1: an index that really describes what is on disk (else None)."""
    doc, _err = read_json(idx)
    if not isinstance(doc, dict) or not isinstance(doc.get("mods"), list) or not doc["mods"]:
        return None
    mods: List[Dict] = []
    for it in doc["mods"]:
        if not isinstance(it, dict) or not it.get("manifest"):
            return None
        rel = _posix(it["manifest"])
        if not _safe_rel(rel):
            return None
        mabs = os.path.join(base, *rel.split("/"))
        if not os.path.isfile(mabs):
            return None
        ent, _why = _load(base, mabs, rel)
        if ent is None or ent["re_anchored"]:
            return None
        if not mods or all(e["name"].lower() != ent["name"].lower() for e in mods):
            mods.append(ent)
    return {"ok": True, "root": base, "index": idx, "source": "index", "written": False,
            "roots": [base], "mods": _public(mods), "skipped": []}


def _resolves(root: str, m: Dict) -> bool:
    folder_abs = os.path.normpath(os.path.join(root, *m["folder"].split("/")))
    return (os.path.isdir(folder_abs)
            and os.path.normpath(m["path"]).startswith(folder_abs))


def _stage(mods: List[Dict]) -> Tuple[str, List[Dict]]:
    """Case 3: one throw-away root in %TEMP% that holds every Mod as a direct child.

    The staged `manifest.json` gets its `folder` rewritten to the staged folder name --
    that is the only field the GUI is allowed to touch, because `folder` is by
    definition relative to the Mods root and the root is what changed.
    """
    root = os.path.join(tempfile.gettempdir(), STAGE_DIRNAME)
    stamp = hashlib.sha256("|".join(sorted(
        "%s@%s:%s" % (m["path"], os.path.getmtime(m["path"]),
                      os.path.getsize(m["path"])) for m in mods)).encode("utf-8")).hexdigest()[:16]
    state = os.path.join(root, ".state.json")
    doc, _e = read_json(state)
    kept = doc.get("placed") if isinstance(doc, dict) else None
    if (isinstance(doc, dict) and doc.get("stamp") == stamp and isinstance(kept, list) and kept
            and os.path.isfile(os.path.join(root, INDEX))
            and all(os.path.isfile(os.path.join(root, *p["manifest"].split("/")))
                    for p in kept)):
        return root, kept               # nothing changed: reuse the staging root

    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root, exist_ok=True)
    used: Dict[str, int] = {}
    placed: List[Dict] = []
    for m in mods:
        # the Mod's files are relative to its `folder`; the staged folder becomes the new
        # one, and the manifest keeps its own position inside it (`sub` is "." normally)
        sub = _posix(os.path.relpath(os.path.dirname(m["path"]), m["folder_abs"]))
        sub = "" if sub in (".", "") else sub
        base = _sanitize(os.path.basename(m["folder"]) or m["name"])
        if not base.lower().endswith("_src"):
            base = _sanitize(m["name"]) + "_src"
        n = used.get(base.lower(), 0) + 1
        used[base.lower()] = n
        folder = base if n == 1 else "%s_%d" % (base, n)
        dst = os.path.join(root, folder)
        os.makedirs(dst, exist_ok=True)
        src = m["folder_abs"]
        for dirpath, _dirs, files in os.walk(src):
            rel = os.path.relpath(dirpath, src)
            out_dir = dst if rel == os.curdir else os.path.join(dst, rel)
            os.makedirs(out_dir, exist_ok=True)
            for f in files:
                _link_copy(os.path.join(dirpath, f), os.path.join(out_dir, f))
        man, _err = read_json(m["path"])
        man = dict(man or {})
        man["folder"] = folder
        rel_man = _posix(os.path.join(folder, sub, INDEX)) if sub else _posix(
            os.path.join(folder, INDEX))
        write_json(os.path.join(root, *rel_man.split("/")), man)
        placed.append(dict(m, folder=folder, manifest=rel_man))
    write_json(os.path.join(root, INDEX), _index_entries(placed))
    pub = _public(placed)
    write_json(state, {"stamp": stamp, "placed": pub})
    return root, pub


# ------------------------------------------------------------------------ public
def discover(spec: str) -> Dict:
    """Turn a user-picked folder (or several, `;`-separated) into a mergeable root.

    Never raises: the answer is always a dict with `ok`, and `reason`/`message` when
    it is False, so the page can show one specific error per problem.
    """
    dirs = spec_dirs(spec)
    if not dirs:
        return {"ok": False, "reason": "no_dir", "message": "还没有选择 Mod 目录"}
    for d in dirs:
        if not os.path.isdir(d):
            return {"ok": False, "reason": "not_found", "message": "目录不存在：%s" % d}

    if len(dirs) == 1:
        idx = os.path.join(dirs[0], INDEX)
        if os.path.isfile(idx):
            got = _use_index(dirs[0], idx)
            if got:
                return got                      # "优先读总索引"

    mods: List[Dict] = []
    skipped: List[Dict] = []
    for d in dirs:
        for mabs, rel in _scan(d):
            ent, why = _load(d, mabs, rel)
            if ent is None:
                if why:                       # "" = a tool state file, silently ignored
                    skipped.append({"path": os.path.join(d, *rel.split("/")), "why": why})
                continue
            if any(e["name"].lower() == ent["name"].lower() for e in mods):
                skipped.append({"path": ent["path"],
                                "why": "另一个 Mod 已经叫 %s 了（协议要求名字唯一）" % ent["name"]})
                continue
            mods.append(ent)
    if not mods:
        return {"ok": False, "reason": "no_mods", "roots": dirs, "skipped": skipped,
                "message": "这个目录里找不到合法的 Mod（每个 Mod 需要一个含 name/kind 的 "
                           "manifest.json）"}

    if len(mods) > MAX_MODS:
        return {"ok": False, "reason": "too_many", "roots": dirs,
                "message": "一次最多合并 %d 个 Mod（找到 %d 个）" % (MAX_MODS, len(mods))}

    for d in dirs:                              # case 2: the picked folder works as-is
        if all(not m["re_anchored"] and _resolves(d, m) for m in mods):
            idx = os.path.join(d, INDEX)
            doc, _e = read_json(idx) if os.path.isfile(idx) else (None, "")
            if doc != _index_entries(mods):
                write_json(idx, _index_entries(mods))
                written = True
            else:
                written = False
            return {"ok": True, "root": d, "index": idx, "source": "scan",
                    "written": written, "roots": dirs, "mods": _public(mods),
                    "skipped": skipped}

    root, placed = _stage(mods)                 # case 3: several folders / a parent
    return {"ok": True, "root": root, "index": os.path.join(root, INDEX), "source": "staged",
            "written": True, "roots": dirs, "mods": placed, "skipped": skipped}


def validate(spec: str, paks: str, out: str, select: Optional[List[str]] = None) -> Dict:
    """Everything that must be true BEFORE a merge starts (drives the error card)."""
    errors: List[str] = []
    warnings: List[str] = []
    if not (spec or "").strip():
        errors.append("Mod 根目录未填写")
    if not (paks or "").strip():
        errors.append("游戏 Paks 目录未填写（合并需要一个干净基底）")
    elif not os.path.isdir(paks):
        errors.append("游戏 Paks 目录不存在：%s" % paks)
    if not (out or "").strip():
        errors.append("输出目录未填写")
    else:
        o = os.path.abspath(out)
        if os.path.exists(o) and not os.path.isdir(o):
            errors.append("输出目录被一个同名文件占着：%s" % out)
        else:
            parent = os.path.dirname(o) or o
            while parent and not os.path.isdir(parent):
                nxt = os.path.dirname(parent)
                if nxt == parent:
                    break
                parent = nxt
            if not os.path.isdir(parent):
                errors.append("输出目录的上级目录不存在：%s" % parent)

    got: Dict = {}
    if (spec or "").strip() and not [e for e in errors if "Mod 根目录" in e]:
        got = discover(spec)
        if not got.get("ok"):
            errors.append(got.get("message") or "找不到可用的 Mod")
        else:
            names = [m["name"] for m in got["mods"]]
            if select is not None:
                want = [s for s in select]
                missing = [s for s in want if s.lower() not in [n.lower() for n in names]]
                if missing:
                    errors.append("勾选的 Mod 不在目录里：%s" % "、".join(missing))
                if not want:
                    errors.append("一个 Mod 都没勾选（取消勾选的不会参与合并）")
            for s in (got.get("skipped") or []):
                warnings.append(s["why"])
            if got.get("source") == "staged":
                warnings.append("已把找到的 Mod 汇集到一个临时目录再合并：%s" % got["root"])
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "root": got.get("root"), "source": got.get("source"),
            "mods": got.get("mods") or []}
