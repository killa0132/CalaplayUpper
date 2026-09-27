# -*- coding: utf-8 -*-
"""G1 verification: drive a real build through the HTTP API and prove the result
matches what the CLI produces.

    python tests/gui_api_check.py

What it checks
--------------
 1. an /api request without the token is refused (403)
 2. POST /api/start + SSE /api/logs/{id} + /api/report/{id} work end to end
    (dry run: gates A0~A7 all ok, deployed=false)
 3. the API's report agrees with a CLI run on the SAME material
    (same gates, same DA row counts, same material list)
 4. a real deploy through the API reports deployed=true, the sandbox really got
    our container, and POST /api/uninstall puts the previous state back
 5. POST /api/cancel/{id} really stops a running build before L5
 6. CP-38: /api/mods lists a Mods index, /api/merge refuses a bad index with 400,
    and a real merge over the API reports M0~M6 PASS + writes the container
 7. the real game folder is never touched
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from gui import app as A  # noqa: E402
from gui import tasks as T  # noqa: E402

MAT = os.path.join(HERE, "mat")
SRCM = os.path.join(MAT, "demo")
OUT = os.path.join(MAT, "out_patch")
FAKEGAME = os.path.join(HERE, "fakegame")
PAKS = os.path.join(FAKEGAME, "Content", "Paks")
PKG = "CalaPlayer-Windows" + "_P"
REAL_GAME = r"D:\CalabiyanGalgameMaker\CalaPlayer\Content\Paks"

FAILS = []


def check(cond, msg):
    print("  %s %s" % ("PASS" if cond else "FAIL", msg))
    if not cond:
        FAILS.append(msg)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def snapshot(paks):
    return {f: sha256(os.path.join(paks, f)) for f in sorted(os.listdir(paks))
            if f.startswith(PKG)} if os.path.isdir(paks) else {}


DA_TABLES = ("DA_Backgrounds", "DA_BGM", "DA_Ambient", "DA_Sounds")


def _find_da(root, tag):
    """The legacy-relative path of <tag>.uasset inside an exported Mod folder."""
    for dirpath, _dirs, fs in os.walk(root):
        if tag + ".uasset" in fs:
            return os.path.relpath(os.path.join(dirpath, tag + ".uasset"), root) \
                     .replace("\\", "/")
    return ""


def check_mod_src(rep, out_patch, tag):
    """CP-40: `<out_patch>/mod_src/<name>_src/` must be a compliant Mod.

    Checks the report entry, the manifest, the DA row source (the shipped table must
    really have max(appended_rows)+1 rows) and that `files` excludes the DA tables,
    keeps the legacy-relative paths and lists files that are all really there.
    """
    sys.path.insert(0, ROOT)
    from core import merger as MG
    ms = (rep or {}).get("mod_src") or {}
    check(bool(ms) and ms.get("root"),
          "%s the report carries the mod_src block: %s" % (tag, ms))
    man_path = ms.get("manifest") or ""
    check(os.path.isfile(man_path), "%s manifest.json was written (%s)" % (tag, man_path))
    if not os.path.isfile(man_path):
        return {}
    man = json.load(open(man_path, encoding="utf-8"))
    root = ms["root"]
    check(man.get("folder") == os.path.basename(root) and bool(man.get("name"))
          and man.get("kind") == "da_edit",
          "%s the manifest names the mod and its folder: %s"
          % (tag, {k: man.get(k) for k in ("name", "folder", "kind")}))
    files = man.get("files") or []
    check(len(files) > 0 and all("Content" in f.split("/") for f in files),
          "%s every declared file keeps its legacy-relative path (%d file(s))"
          % (tag, len(files)))
    listed_da = [f for f in files
                 if os.path.splitext(os.path.basename(f))[0] in DA_TABLES]
    check(not listed_da, "%s the target DA tables are NOT listed in `files`: %s"
          % (tag, listed_da))
    missing = [f for f in files if not os.path.isfile(os.path.join(root, *f.split("/")))]
    check(not missing, "%s every declared file really exists (%s)" % (tag, missing[:3]))
    def _uxp(rel):
        parts = rel.split("/")
        parts[-1] = os.path.splitext(parts[-1])[0] + ".uexp"
        return os.path.join(root, *parts)

    noexp = [f for f in files if f.endswith(".uasset") and not os.path.isfile(_uxp(f))]
    check(not noexp, "%s each .uasset is shipped with its .uexp (%s)" % (tag, noexp[:3]))
    tg = man.get("targets") or {}
    check(bool(tg) and all(v.get("appended_rows") for v in tg.values()),
          "%s targets declare the appended rows: %s" % (tag, tg))
    for t, v in sorted(tg.items()):
        rel = _find_da(root, t)
        if not rel:
            check(False, "%s the row source %s.uasset is not in the export" % (tag, t))
            continue
        ux = os.path.splitext(os.path.join(root, *rel.split("/")))[0] + ".uexp"
        rows = MG.table_rows(open(ux, "rb").read(), MG.TABLE_SPECS[t])
        check(rows == max(v["appended_rows"]) + 1,
              "%s %s ships %d row(s) = max(appended)+1 (%s)"
              % (tag, t, rows, v["appended_rows"]))
    return {"files": len(files), "targets": tg}


class Client:
    def __init__(self, port):
        self.base = "http://127.0.0.1:%d" % port

    def _url(self, path, token=True):
        sep = "&" if "?" in path else "?"
        return self.base + path + (sep + "t=" + A.TOKEN if token else "")

    def get(self, path, token=True, raw=False):
        with urllib.request.urlopen(self._url(path, token), timeout=30) as r:
            b = r.read()
            return b if raw else json.loads(b.decode("utf-8"))

    def post(self, path, body=None, token=True):
        data = json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(self._url(path, token), data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))

    def sse(self, task_id, on_event=None):
        """Consume /api/logs until the `end` event; returns (lines, events)."""
        lines, events = [], []
        with urllib.request.urlopen(self._url("/api/logs/%s" % task_id), timeout=600) as r:
            event = None
            for raw in r:
                s = raw.decode("utf-8", "replace").rstrip("\n")
                if s.startswith("event: "):
                    event = s[7:]
                elif s.startswith("data: "):
                    payload = json.loads(s[6:])
                    events.append(event)
                    if event == "line":
                        lines.append(payload["line"])
                    if on_event:
                        on_event(event, payload)
                    if event == "end":
                        break
        return lines, events


def main() -> int:
    if not os.path.isdir(SRCM):
        print("FATAL: test material missing (%s) -- run tests/regression.py once" % SRCM)
        return 2
    real_before = snapshot(REAL_GAME) if os.path.isdir(REAL_GAME) else None

    port = A.pick_port()
    server, _th = A.start_server_thread(port)
    health = "http://127.0.0.1:%d/api/health?t=%s" % (port, A.TOKEN)
    for _ in range(80):
        try:
            urllib.request.urlopen(health, timeout=2).read()
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.15)
    c = Client(port)
    print("GUI API  : http://127.0.0.1:%d" % port)

    # ---------------------------------------------------------------- 1) token
    print("[1] token guard")
    try:
        c.get("/api/health", token=False)
        check(False, "an unauthenticated /api call must be refused")
    except urllib.error.HTTPError as e:
        check(e.code == 403, "unauthenticated /api call -> 403")

    # ------------------------------------------------- 2) dry run via the API
    print("[2] dry run through /api/start + SSE + /api/report (+ -ExportSrc)")
    r = c.post("/api/start", {"paks": FAKEGAME, "srcm": SRCM, "dry_run": True,
                             "export_src": True})
    tid = r["task_id"]
    stages = set()
    t0 = time.time()
    lines, events = c.sse(tid, on_event=lambda k, p: stages.add(p.get("stage"))
                          if k == "stage" else None)
    rep = c.get("/api/report/%s" % tid)
    print("      %d log lines, %d events, %.1fs" % (len(lines), len(events), time.time() - t0))
    check(rep["done"] and rep["ok"], "the task finished ok (%s)" % (rep["error"] or "-"))
    gates = (rep["report"] or {}).get("gates", {})
    check(set(gates) >= {"A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"} and
          all(g["ok"] for g in gates.values()), "A0~A8 all present and PASS")
    check((rep["report"] or {}).get("deployed") is False, "dry run did not deploy")
    check(any("QUALITY:" in l for l in lines), "SSE carried the QUALITY line")
    check(any("GATE] A5" in l for l in lines), "SSE carried the gate lines")
    # CP-34: the two new user-facing messages must reach the GUI log panel, which
    # is fed by the very same `Log` sink that writes the CLI's build.log.
    check(any("非 16:9" in l for l in lines), "SSE carried the aspect-ratio warning")
    check(any("preview MI MI_" in l for l in lines), "SSE carried the preview-MI line")
    seen = {"L0", "L1", "L2", "L3", "L4"}
    check(seen <= stages, "SSE emitted a stage event for each of L0~L4 (got %s)"
          % ",".join(sorted(x for x in stages if x)))
    api_rep = rep["report"]

    # ------------------------------------- 2b) CP-40: -ExportSrc (the Mod source)
    print("[2b] -ExportSrc: <out_patch>/mod_src/<name>_src/ is a compliant Mod")
    ms = check_mod_src(api_rep, OUT, "[api]")
    check(any("-ExportSrc" in l for l in lines), "the SSE carried the -ExportSrc line")

    # ------------------------------------------------------ 3) CLI agreement
    print("[3] the API run vs a CLI run on the same material")
    exe_cands = []
    for d in sorted(os.listdir(os.path.join(ROOT, "dist")), reverse=True):
        p = os.path.join(ROOT, "dist", d, "CalaPlayerSrcmBuilder.exe")
        if os.path.isfile(p):
            exe_cands.append(p)
    cmd = [exe_cands[0]] if exe_cands else [sys.executable,
                                            os.path.join(ROOT, "cli", "build_srcm.py")]
    p = subprocess.run(cmd + ["-Paks", FAKEGAME, "-Srcm", SRCM, "-DryRun", "-Quiet"],
                       capture_output=True, timeout=1800)
    cli_rep = json.load(open(os.path.join(OUT, "build_report.json"), encoding="utf-8"))
    check(p.returncode == 0 and cli_rep["ok"], "the CLI run also succeeded (%s)"
          % (p.stderr or b"")[-200:])
    same_gates = {k: v["ok"] for k, v in gates.items()} == \
                 {k: v["ok"] for k, v in cli_rep["gates"].items()}
    check(same_gates, "identical gate verdicts (API vs CLI)")
    check(api_rep["da_counts"] == cli_rep["da_counts"],
          "identical DA row counts %s" % api_rep["da_counts"])
    a_names = sorted((m["kind"], m["name"], m["key"]) for m in api_rep["materials"])
    c_names = sorted((m["kind"], m["name"], m["key"]) for m in cli_rep["materials"])
    check(a_names == c_names, "identical material list (kind/name/display name)")
    # the -ExportSrc FLAG (CLI surface) is exercised through the source entry point:
    # the frozen exe in dist/ only learns about it once build_srcm.ps1 has been re-run
    p2 = subprocess.run([sys.executable, os.path.join(ROOT, "cli", "build_srcm.py"),
                         "-Paks", FAKEGAME, "-Srcm", SRCM, "-DryRun", "-Quiet",
                         "-ExportSrc", "-SrcName", "SrcFlagCheck"],
                        capture_output=True, timeout=1800)
    cli2 = json.load(open(os.path.join(OUT, "build_report.json"), encoding="utf-8"))
    check(p2.returncode == 0 and cli2["ok"], "the CLI accepted -ExportSrc / -SrcName (%s)"
          % (p2.stderr or b"")[-200:])
    check((cli2.get("mod_src") or {}).get("folder") == "SrcFlagCheck_src"
          and (cli2.get("params") or {}).get("export_src") is True,
          "the CLI exported under the requested Mod name: %s" % (cli2.get("mod_src") or {}))
    check_mod_src(cli2, OUT, "[cli-flag]")
    shutil.rmtree(os.path.join(OUT, "mod_src", "SrcFlagCheck_src"), ignore_errors=True)

    # ------------------- 3b) CP-40: feed that very mod_src back into the merger
    print("[3b] the exported mod_src merged back into one _P (M0~M6)")
    mods_root = os.path.join(OUT, "mod_src")
    idx = os.path.join(mods_root, "manifest.json")
    if os.path.isfile(idx):
        os.remove(idx)                       # prove the recursive sniff + auto index
    lm = c.get("/api/mods?dir=" + urllib.parse.quote(mods_root))
    check(lm.get("ok") and [m["name"] for m in lm["mods"]] == ["CalaplayUpper"]
          and lm.get("source") == "scan" and lm.get("written") is True,
          "the export is auto-sniffed and the index is generated (source=%s written=%s): %s"
          % (lm.get("source"), lm.get("written"), lm.get("message") or "-"))
    check(os.path.isfile(idx),
          "the generated index really landed next to the Mod folders: %s" % idx)
    lm2 = c.get("/api/mods?dir=" + urllib.parse.quote(OUT))
    check(lm2.get("ok") and lm2.get("source") == "staged"
          and any(m["name"] == "CalaplayUpper" for m in lm2["mods"]),
          "picking the PARENT folder still finds the export (staged root): %s"
          % {k: lm2.get(k) for k in ("ok", "source", "root", "message")})
    mout = os.path.join(MAT, "export_merge_out")
    shutil.rmtree(mout, ignore_errors=True)
    sandbox_pre = snapshot(PAKS)
    r = c.post("/api/merge", {"mods": mods_root, "paks": FAKEGAME, "out": mout,
                              "select": ["CalaplayUpper"], "dry_run": True})
    tid_x = r["task_id"]
    xstages = set()
    c.sse(tid_x, on_event=lambda k, p: xstages.add(p.get("stage")) if k == "stage" else None)
    repx = c.get("/api/report/%s" % tid_x)
    rx = repx["report"] or {}
    check(repx["ok"], "the export merged back (%s)" % (repx["error"] or "-"))
    mgx = rx.get("gates", {})
    check(set(mgx) >= {"M0", "M1", "M2", "M3", "M4", "M5", "M6"}
          and all(v["ok"] for v in mgx.values()), "M0~M6 all PASS on the self-made Mod")
    tb = rx.get("tables") or {}
    check((tb.get("DA_Backgrounds") or {}).get("final")
          == (cli_rep.get("da_counts") or {}).get("DA_Backgrounds"),
          "the merged table has exactly the rows the single build produced: %s" % tb)
    check(os.path.isfile(os.path.join(mout, PKG + ".ucas")),
          "the round-trip container was written")
    # CP-41：勾了「仅产出不安装」时**不许**碰游戏目录
    check(rx.get("deploy") is None,
          "dry_run was ignored: the merge reported a deploy block: %s" % rx.get("deploy"))
    check(snapshot(PAKS) == sandbox_pre and "M7" not in xstages,
          "the produce-only merge still wrote to the game folder (stages %s)"
          % ",".join(sorted(x for x in xstages if x)))

    # ------------------------------------- 3c) CP-40: /api/validate (pre-flight)
    print("[3c] /api/validate lists the problems before a merge starts")
    v = c.post("/api/validate", {"mods": "", "paks": "", "out": ""})
    check(v["ok"] is False and len(v["errors"]) == 3
          and any("Mod 根目录" in e for e in v["errors"])
          and any("Paks" in e for e in v["errors"])
          and any("输出目录" in e for e in v["errors"]),
          "the empty inputs are reported one by one: %s" % v["errors"])
    v = c.post("/api/validate", {"mods": os.path.join(MAT, "no_such_mods_xyz"),
                                 "paks": FAKEGAME, "out": os.path.join(MAT, "vout")})
    check(v["ok"] is False and any("不存在" in e for e in v["errors"]),
          "a folder that does not exist is reported as such: %s" % v["errors"])
    v = c.post("/api/validate", {"mods": OUT, "paks": FAKEGAME,
                                 "out": os.path.join(MAT, "vout"),
                                 "select": ["CalaplayUpper"]})
    check(v["ok"] is True and bool(v.get("root")) and not v["errors"],
          "a valid set of inputs passes the pre-flight: %s" % v)
    v = c.post("/api/validate", {"mods": OUT, "paks": FAKEGAME,
                                 "out": os.path.join(MAT, "vout"), "select": ["Nope"]})
    check(v["ok"] is False and any("勾选" in e for e in v["errors"]),
          "a selected mod that is not there is refused: %s" % v["errors"])
    # ---- CP-41：单包模式也用同一张错误卡片 -----------------------------------
    v = c.post("/api/validate", {"mode": "single", "paks": "", "srcm": ""})
    check(v["ok"] is False and len(v["errors"]) == 2
          and any("Paks" in e for e in v["errors"])
          and any("素材" in e for e in v["errors"]),
          "the single-mode pre-flight does not list both missing paths: %s" % v["errors"])
    v = c.post("/api/validate", {"mode": "single", "paks": os.path.join(MAT, "nope"),
                                 "srcm": os.path.join(MAT, "nope2")})
    check(v["ok"] is False and len(v["errors"]) == 2
          and all("不存在" in e for e in v["errors"]),
          "the single-mode pre-flight does not report non-existent paths: %s" % v["errors"])
    v = c.post("/api/validate", {"mode": "single", "paks": FAKEGAME, "srcm": SRCM})
    check(v["ok"] is True and not v["errors"],
          "a valid single-mode build passes the pre-flight: %s" % v)

    # ------------------------------------------------------- 4) deploy + undo
    print("[6] real deploy via the API, then roll back via /api/uninstall")
    before = snapshot(PAKS)
    r = c.post("/api/start", {"paks": FAKEGAME, "srcm": SRCM})
    tid2 = r["task_id"]
    c.sse(tid2)
    rep2 = c.get("/api/report/%s" % tid2)
    rep2r = rep2["report"] or {}
    check(rep2["ok"] and rep2r.get("deployed") is True, "the API report says deployed=true")
    want = (rep2r.get("container", {}).get("files", {}).get("ucas", {}) or {}).get("sha256")
    live = sha256(os.path.join(PAKS, PKG + ".ucas"))
    check(want and live == want, "the sandbox really received our container")
    u = c.post("/api/uninstall", {"task_id": tid2, "paks": PAKS})
    check(u["rc"] == 0, "uninstall.ps1 rc=0")
    check(snapshot(PAKS) == before, "rollback restored the sandbox to the pre-deploy state")

    # ---------------------------------------------------------- 5) cancellation
    print("[7] cancel a running build (must stop before L5)")
    r = c.post("/api/start", {"paks": FAKEGAME, "srcm": SRCM, "dry_run": True})
    tid3 = r["task_id"]
    time.sleep(3.0)
    c.post("/api/cancel/%s" % tid3)
    c.sse(tid3)
    rep3 = c.get("/api/report/%s" % tid3)
    check(rep3["ok"] is False and "已取消" in (rep3["error"] or ""),
          "the build reported itself cancelled (%s)" % (rep3["error"] or "-")[:70])

    # ------------------------------------------------- 6) CP-38 mod merge
    print("[8] /api/mods + /api/merge (several mods -> one _P)")
    mdir = os.path.join(MAT, "merge_api")
    shutil.rmtree(mdir, ignore_errors=True)
    for folder, name, kind in (("ModA_src", "ModA", "da_edit"), ("ModB_src", "ModB", "ui_text")):
        os.makedirs(os.path.join(mdir, folder), exist_ok=True)
        with open(os.path.join(mdir, folder, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump({"name": name, "folder": folder, "kind": kind,
                       "targets": {}, "files": []}, fh, ensure_ascii=False)
    with open(os.path.join(mdir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({"mods": [{"name": "ModA", "manifest": "ModA_src/manifest.json"},
                            {"name": "ModB", "manifest": "ModB_src/manifest.json"}]},
                  fh, ensure_ascii=False)
    lm = c.get("/api/mods?dir=" + urllib.parse.quote(mdir))
    check(lm.get("ok") and [m["name"] for m in lm["mods"]] == ["ModA", "ModB"]
          and [m["kind"] for m in lm["mods"]] == ["da_edit", "ui_text"],
          "the index manifest is listed with its mods (name + kind)")
    miss = c.get("/api/mods?dir=" + urllib.parse.quote(os.path.join(MAT, "no_such_dir")))
    check(miss.get("ok") is False and miss.get("reason") == "not_found",
          "an unknown Mods folder answers ok=false (not a crash): %s" % miss.get("reason"))
    try:
        c.post("/api/merge", {"mods": mdir, "out": os.path.join(MAT, "merge_api_out")})
        check(False, "a mods folder without a valid index must be refused")
    except urllib.error.HTTPError as e:
        check(e.code == 400, "a mods folder whose entries have no assets -> HTTP 400")

    # a REAL merge over HTTP needs cooked DA pairs; tests/regression.py builds that
    # fixture (T30), so run it when it is there and say so when it is not
    ok_tree = os.path.join(MAT, "merge", "ok")
    if os.path.isdir(ok_tree):
        out = os.path.join(MAT, "merge", "api_out")
        shutil.rmtree(out, ignore_errors=True)
        # CP-41：合并默认**自动安装进游戏**（这里 = 沙箱）。装完必须把沙箱还原，
        # 否则"沙箱 == 真机"这个不变式就被这次测试弄脏了。
        sandbox_before = snapshot(PAKS)
        natives_before = {f: sha256(os.path.join(PAKS, f)) for f in sorted(os.listdir(PAKS))
                          if f.startswith("CalaPlayer-Windows.")}
        r = c.post("/api/merge", {"mods": ok_tree, "paks": FAKEGAME, "out": out})
        tid4 = r["task_id"]
        mstages = set()
        mlines, _ = c.sse(tid4, on_event=lambda k, p: mstages.add(p.get("stage"))
                          if k == "stage" else None)
        rep4 = c.get("/api/report/%s" % tid4)
        mr = rep4["report"] or {}
        check(rep4["ok"], "the merge finished ok (%s)" % (rep4["error"] or "-"))
        mg = mr.get("gates", {})
        check(set(mg) >= {"M0", "M1", "M2", "M3", "M4", "M5", "M6"}
              and all(v["ok"] for v in mg.values()), "M0~M6 all present and PASS")
        check({"M0", "M1", "M2", "M3", "M4", "M5", "M6"} <= mstages,
              "SSE emitted a stage event per merge stage (got %s)"
              % ",".join(sorted(x for x in mstages if x)))
        check(os.path.isfile(os.path.join(out, PKG + ".ucas")),
              "the merged container was written to the output folder")
        check((mr.get("tables") or {}).get("DA_Backgrounds", {}).get("appended") == 1,
              "the merged table carries the appended row: %s" % (mr.get("tables") or {}))
        check(rep4["out_patch"] == out, "the task's out_patch is the merge output folder")

        # ---- CP-41：自动安装（备份 → 写入 → 读回 → 失败还原）------------------
        dep = mr.get("deploy") or {}
        check(dep and dep.get("ok") is not False,
              "the merge did not auto-install: %s" % dep)
        check("M7" in mstages, "SSE never reported the install stage M7 (got %s)"
              % ",".join(sorted(x for x in mstages if x)))
        want_ucas = (mr.get("container", {}).get("files", {}).get("ucas", {}) or {}).get("sha256")
        live = sha256(os.path.join(PAKS, PKG + ".ucas"))
        check(want_ucas and live == want_ucas,
              "the sandbox did not receive the freshly merged container")
        check((dep.get("installed") or {}).get("ucas", {}).get("sha256") == want_ucas,
              "the deploy block's ucas hash does not match the container")
        check(os.path.isdir(dep.get("backup") or "") and
              os.path.isfile(dep.get("backup_txt") or ""),
              "no install_backup_* / BACKUP.txt was written: %s" % dep.get("backup"))
        check(os.path.basename(dep.get("backup") or "").startswith("install_backup_"),
              "the backup folder is not named install_backup_*: %s" % dep.get("backup"))
        if sandbox_before.get(PKG + ".ucas"):
            txt = open(dep["backup_txt"], encoding="utf-8").read()
            check(sandbox_before[PKG + ".ucas"][:16] in txt,
                  "BACKUP.txt does not record the container it replaced")
        check({f: sha256(os.path.join(PAKS, f)) for f in sorted(os.listdir(PAKS))
               if f.startswith("CalaPlayer-Windows.")} == natives_before,
              "the native containers were rewritten by the install")

        # ---- ... 以及 GUI 的回滚（走 install_backup_*，不是 uninstall.ps1）------
        u = c.post("/api/uninstall", {"task_id": tid4, "paks": PAKS})
        check(u["rc"] == 0 and snapshot(PAKS) == sandbox_before,
              "the merge rollback did not put the sandbox back: %s" % u.get("stdout", "")[:120])
    else:
        print("      SKIP the end-to-end merge (run tests/regression.py once to build it)")

    # --------------------------------------------------------- 7) real game
    print("[9] the real game folder")
    if real_before is not None:
        check(snapshot(REAL_GAME) == real_before, "the real game folder was not touched")
    server.should_exit = True

    print("-" * 74)
    if FAILS:
        print("G1 RESULT: FAILED (%d)" % len(FAILS))
        for f in FAILS:
            print("   - %s" % f)
        return 1
    print("G1 RESULT: OK -- the HTTP API drives the same pipeline with the same verdicts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
