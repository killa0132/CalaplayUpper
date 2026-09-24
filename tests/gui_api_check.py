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
 6. the real game folder is never touched
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
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
    print("[2] dry run through /api/start + SSE + /api/report")
    r = c.post("/api/start", {"paks": FAKEGAME, "srcm": SRCM, "dry_run": True})
    tid = r["task_id"]
    stages = set()
    t0 = time.time()
    lines, events = c.sse(tid, on_event=lambda k, p: stages.add(p.get("stage"))
                          if k == "stage" else None)
    rep = c.get("/api/report/%s" % tid)
    print("      %d log lines, %d events, %.1fs" % (len(lines), len(events), time.time() - t0))
    check(rep["done"] and rep["ok"], "the task finished ok (%s)" % (rep["error"] or "-"))
    gates = (rep["report"] or {}).get("gates", {})
    check(set(gates) >= {"A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7"} and
          all(g["ok"] for g in gates.values()), "A0~A7 all present and PASS")
    check((rep["report"] or {}).get("deployed") is False, "dry run did not deploy")
    check(any("QUALITY:" in l for l in lines), "SSE carried the QUALITY line")
    check(any("GATE] A5" in l for l in lines), "SSE carried the gate lines")
    seen = {"L0", "L1", "L2", "L3", "L4"}
    check(seen <= stages, "SSE emitted a stage event for each of L0~L4 (got %s)"
          % ",".join(sorted(x for x in stages if x)))
    api_rep = rep["report"]

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
    check(p.returncode == 0 and cli_rep["ok"], "the CLI run also succeeded")
    same_gates = {k: v["ok"] for k, v in gates.items()} == \
                 {k: v["ok"] for k, v in cli_rep["gates"].items()}
    check(same_gates, "identical gate verdicts (API vs CLI)")
    check(api_rep["da_counts"] == cli_rep["da_counts"],
          "identical DA row counts %s" % api_rep["da_counts"])
    a_names = sorted((m["kind"], m["name"], m["key"]) for m in api_rep["materials"])
    c_names = sorted((m["kind"], m["name"], m["key"]) for m in cli_rep["materials"])
    check(a_names == c_names, "identical material list (kind/name/display name)")

    # ------------------------------------------------------- 4) deploy + undo
    print("[4] real deploy via the API, then roll back via /api/uninstall")
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
    print("[5] cancel a running build (must stop before L5)")
    r = c.post("/api/start", {"paks": FAKEGAME, "srcm": SRCM, "dry_run": True})
    tid3 = r["task_id"]
    time.sleep(3.0)
    c.post("/api/cancel/%s" % tid3)
    c.sse(tid3)
    rep3 = c.get("/api/report/%s" % tid3)
    check(rep3["ok"] is False and "已取消" in (rep3["error"] or ""),
          "the build reported itself cancelled (%s)" % (rep3["error"] or "-")[:70])

    # --------------------------------------------------------- 6) real game
    print("[6] the real game folder")
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
