# -*- coding: utf-8 -*-
"""FastAPI backend for the GUI.

Endpoints (see docs/2026-09-23_gui_design.md):
    GET  /                         the built Vue app (gui/dist)
    GET  /api/health               liveness + version
    POST /api/start                {paks, srcm, fit, dry_run, combined, force, ffmpeg, kit}
    GET  /api/logs/{task_id}       Server-Sent Events, live log + stage events
    GET  /api/report/{task_id}     build_report.json of that task
    POST /api/cancel/{task_id}     cooperative cancel (honoured until L5 starts)
    GET  /api/select_folder        native folder dialog (needs the window)
    GET  /api/open_folder          reveal out_patch in Explorer
    POST /api/uninstall            run the generated uninstall.ps1 (rollback)

Security: bound to 127.0.0.1 only AND every /api call must carry the per-run
token (`?t=` or the `X-Cala-Token` header), so another local program cannot
drive the tool.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import queue
import secrets
import socket
import subprocess
import sys
from typing import Any, Dict, Optional

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.builder import TOOL_VERSION  # noqa: E402
from gui import prefs  # noqa: E402
from gui import tasks  # noqa: E402

TOKEN = os.environ.get("CALA_GUI_TOKEN") or secrets.token_urlsafe(18)

#: set by desktop.py once the pywebview window exists (native dialogs need it)
WINDOW = None


def dist_dir() -> str:
    """The built Vue app.  In a frozen exe it lives inside _MEIPASS."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        cand = os.path.join(base, "gui", "dist")
        if os.path.isdir(cand):
            return cand
    return os.path.join(_HERE, "dist")


def pick_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _folder_dialog_kind(webview):
    """`FileDialog.FOLDER` across pywebview versions (6.x turned the old
    FOLDER_DIALOG constant into a deprecated function)."""
    fd = getattr(webview, "FileDialog", None)
    if fd is not None and hasattr(fd, "FOLDER"):
        return fd.FOLDER
    legacy = getattr(webview, "FOLDER_DIALOG", None)
    if callable(legacy):
        try:
            return legacy()
        except Exception:  # noqa: BLE001
            pass
    return 20          # the historical numeric value of FolderDialog


def create_app() -> FastAPI:
    app = FastAPI(title="CalaPlayerSrcmBuilder GUI", version=TOOL_VERSION,
                  docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def _auth(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            got = request.query_params.get("t") or request.headers.get("x-cala-token")
            if got != TOKEN:
                return JSONResponse({"detail": "bad or missing token"}, status_code=403)
        return await call_next(request)

    # ---------------------------------------------------------------- health
    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {"ok": True, "version": TOOL_VERSION, "pid": os.getpid(),
                "tasks": len(tasks.all_tasks())}

    # ---------------------------------------------------------------- prefs
    # A stable home for "remember this between launches".  localStorage is no
    # use: the page's origin carries a fresh random port every launch (see
    # gui/prefs.py), so the onboarding flag/language/theme/split never stuck.
    @app.get("/api/prefs")
    def get_prefs() -> Dict[str, Any]:
        return {"ok": True, "prefs": prefs.all_prefs(), "path": prefs.path()}

    @app.post("/api/prefs")
    def set_prefs(body: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
        return {"ok": True, "prefs": prefs.put(body or {})}

    # ----------------------------------------------------------------- start
    @app.post("/api/start")
    def start(body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        paks = (body.get("paks") or "").strip()
        srcm = (body.get("srcm") or "").strip()
        if not paks or not srcm:
            raise HTTPException(400, "paks and srcm are required")
        if not os.path.isdir(srcm):
            raise HTTPException(400, "srcm folder does not exist: %s" % srcm)
        running = [t for t in tasks.all_tasks()
                   if t["finished"] is None]
        if running:
            raise HTTPException(409, "a build is already running (%s); wait for it or cancel it"
                                % running[0]["id"])
        params = {
            "paks": paks, "srcm": srcm,
            "fit": body.get("fit") or "cover",
            "dry_run": bool(body.get("dry_run")),
            "combined": bool(body.get("combined")),
            "force": bool(body.get("force")),
            "no_atlas": bool(body.get("no_atlas")),
            "ffmpeg": body.get("ffmpeg") or None,
            "kit": body.get("kit") or None,
        }
        t = tasks.start(params)
        return {"task_id": t.id, "params": params}

    # ------------------------------------------------------------------ logs
    @app.get("/api/logs/{task_id}")
    async def logs(task_id: str, request: Request):
        t = tasks.get(task_id)
        if not t:
            raise HTTPException(404, "unknown task")

        async def gen():
            # replay what we already have so a late/reconnecting client is in sync
            yield _sse("snapshot", {"lines": list(t.buffer)[-400:]})
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = t.queue.get_nowait()
                except queue.Empty:
                    if t.done.is_set():
                        break
                    await asyncio.sleep(0.05)
                    continue
                kind = item.pop("kind", "line")
                yield _sse(kind, item)
            yield _sse("end", {"ok": t.ok, "error": t.error,
                               "out_patch": t.out_patch})

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    # ---------------------------------------------------------------- report
    @app.get("/api/report/{task_id}")
    def report(task_id: str) -> Dict[str, Any]:
        t = tasks.get(task_id)
        if not t:
            raise HTTPException(404, "unknown task")
        return {"done": t.done.is_set(), "ok": t.ok, "error": t.error,
                "out_patch": t.out_patch,
                "report": t.report,
                "tasks": tasks.all_tasks()}

    @app.post("/api/cancel/{task_id}")
    def cancel(task_id: str) -> Dict[str, Any]:
        return {"canceled": tasks.request_cancel(task_id)}

    # ---------------------------------------------------------- export the log
    @app.post("/api/export_log/{task_id}")
    def export_log(task_id: str, path: str = Query("")) -> Dict[str, Any]:
        """Failure-modal helper: save this build's whole log to a text file.

        `path` is for scripts/self-tests (write straight there, no dialog).
        Without it we ask the user where to put it through the same native
        pywebview dialog machinery as /api/select_folder.  A build that died
        before it logged anything is NOT an error: it comes back as
        {"ok": false, "message": "暂无日志可导出"} so the page can say so.
        """
        t = tasks.get(task_id)
        text = _log_text(t)
        if not text.strip():
            return {"ok": False, "reason": "empty", "message": "暂无日志可导出"}

        target = (path or "").strip()
        if not target:
            if WINDOW is None:
                raise HTTPException(501, "no desktop window (browser-only mode)")
            import webview

            res = WINDOW.create_file_dialog(
                webview.FileDialog.SAVE,
                directory=os.path.expanduser("~"),
                save_filename="CalaPlayerSrcmBuilder_%s.log" % t.id,
                file_types=("日志 (*.log;*.txt)", "*.log;*.txt", "所有文件 (*.*)", "*.*"))
            if not res:
                return {"ok": False, "reason": "cancelled", "message": "已取消导出"}
            target = res if isinstance(res, str) else res[0]

        try:
            with open(target, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        except OSError as e:
            raise HTTPException(500, "cannot write %s: %s" % (target, e))
        return {"ok": True, "path": target, "bytes": len(text.encode("utf-8"))}


    # ----------------------------------------------------- open an external link
    @app.get("/api/open_url")
    def open_url(url: str = Query(""), dry: int = Query(0)) -> Dict[str, Any]:
        """Hand a community link to the user's real browser.

        A plain `<a target="_blank">` inside WebView2 is not dependable -- the
        host is free to swallow the new-window request, which looks exactly like
        a dead button.  So the page asks the backend to pass the URL to the OS
        instead.  A short allow-list keeps this from becoming an "open anything
        on this machine" primitive.  `dry=1` validates without opening anything
        (used by the self-test, which must not launch a browser).
        """
        u = (url or "").strip()
        allowed = ("https://discord.com/invite/BGeYfMBwaw",
                   "https://discord.gg/BGeYfMBwaw",
                   "https://space.bilibili.com/",
                   "https://www.bilibili.com/",
                   "https://github.com/killa0132/CalaplayUpper")
        if not u or not any(u.startswith(a) for a in allowed):
            return {"ok": False, "reason": "blocked", "message": "url not allowed"}
        if dry:
            return {"ok": True, "would_open": u, "dry": True}
        try:
            import webbrowser
            opened = webbrowser.open(u)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, "cannot open the browser: %s" % e)
        return {"ok": True, "opened": bool(opened), "url": u}

    # ------------------------------------------------------------ clipboard
    @app.get("/api/copy")
    def copy_text(text: str = Query(""), dry: int = Query(0)) -> Dict[str, Any]:
        """Put a short string (the QQ group number) on the Windows clipboard.

        The page could try `navigator.clipboard.writeText`, but inside an
        embedded WebView2 that needs a secure context *and* a user gesture, and
        when either is missing it fails silently -- which is exactly the kind of
        dead button we must not ship.  Doing it in the backend also makes it
        testable: the self-test writes, reads the clipboard back with the same
        API and compares.  `dry=1` only reports what it would do.
        """
        t = text or ""
        if not t.strip():
            return {"ok": False, "reason": "empty", "message": "nothing to copy"}
        if len(t) > 256:
            return {"ok": False, "reason": "too_long", "message": "refusing to copy that much"}
        if dry:
            return {"ok": True, "would_copy": t, "dry": True}
        try:
            import ctypes
            u32 = ctypes.windll.user32
            k32 = ctypes.windll.kernel32
            # 64-bit safe declarations: the default c_int return type would
            # truncate an HGLOBAL (the bug that makes hand-rolled clipboard code
            # fail only on x64)
            k32.GlobalAlloc.restype = ctypes.c_void_p
            k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
            k32.GlobalLock.restype = ctypes.c_void_p
            k32.GlobalLock.argtypes = [ctypes.c_void_p]
            k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            u32.OpenClipboard.argtypes = [ctypes.c_void_p]
            u32.SetClipboardData.restype = ctypes.c_void_p
            u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

            CF_UNICODETEXT = 13
            GMEM_MOVEABLE = 0x0002
            if not u32.OpenClipboard(None):
                raise OSError("OpenClipboard failed (another app is holding it)")
            try:
                if not u32.EmptyClipboard():
                    raise OSError("EmptyClipboard failed")
                data = t.encode("utf-16-le") + b"\x00\x00"
                h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                if not h:
                    raise OSError("GlobalAlloc failed")
                p = k32.GlobalLock(h)
                if not p:
                    raise OSError("GlobalLock failed")
                ctypes.memmove(p, data, len(data))
                k32.GlobalUnlock(h)
                if not u32.SetClipboardData(CF_UNICODETEXT, h):
                    raise OSError("SetClipboardData failed")
            finally:
                u32.CloseClipboard()
        except OSError as e:
            raise HTTPException(500, "cannot use the clipboard: %s" % e)
        return {"ok": True, "copied": t, "chars": len(t)}

    # --------------------------------------------------- native folder picker
    @app.get("/api/select_folder")
    def select_folder(kind: str = Query("srcm"), dir: str = Query("")) -> Dict[str, Any]:
        if WINDOW is None:
            raise HTTPException(501, "no desktop window (browser-only mode)")
        import logging

        import webview

        # NOTE: pywebview 6 deprecated the module-level FOLDER_DIALOG constant and
        # turned it into a *function*.  Passing the function made
        # create_file_dialog fall through every branch, hit an internal exception
        # and return None -- i.e. the button silently did nothing, looking exactly
        # like "the user cancelled".  Always use the FileDialog enum.
        kind_value = _folder_dialog_kind(webview)

        # ... and always hand it a real starting directory: pywebview's own
        # fallback is os.environ['HOMEPATH'], which on Windows has no drive letter
        # (e.g. "\Users\me"), so the dialog can come back instantly/None.
        start_dir = dir if (dir and os.path.isdir(dir)) else os.path.expanduser("~")

        captured: list = []

        class _Cap(logging.Handler):
            def emit(self, record):
                captured.append(record.getMessage())

        # pywebview logs to the 'pywebview' logger (not 'webview')
        logs = [logging.getLogger("pywebview"), logging.getLogger("webview")]
        cap = _Cap()
        for lg in logs:
            lg.addHandler(cap)
        try:
            res = WINDOW.create_file_dialog(kind_value, directory=start_dir)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, "the native dialog failed: %s: %s" % (type(e).__name__, e))
        finally:
            for lg in logs:
                lg.removeHandler(cap)

        if captured:
            # never let a swallowed pywebview exception look like a user cancel
            raise HTTPException(500, "pywebview reported: %s" % " | ".join(captured[-3:]))
        if not res:
            # a cancel and a "silently did nothing" look identical from the UI, so
            # hand back enough detail to tell them apart
            dbg = {}
            try:
                from webview.platforms import winforms as _wf
                gui = getattr(WINDOW, "gui", None)
                dbg = {"gui": getattr(gui, "__name__", type(gui).__name__),
                       "uid": getattr(WINDOW, "uid", None),
                       "registered": list(getattr(_wf.BrowserView, "instances", {}).keys()),
                       "kind": int(kind_value) if isinstance(kind_value, int) else str(kind_value),
                       "start_dir": start_dir}
            except Exception as e:  # noqa: BLE001
                dbg = {"introspect_failed": str(e)}
            return {"path": None, "debug": dbg}
        return {"path": res[0] if isinstance(res, (list, tuple)) else res}

    # --------------------------------------------------------- open in explorer
    @app.get("/api/open_folder")
    def open_folder(task_id: str = Query(""), what: str = Query("out")) -> Dict[str, Any]:
        target = ""
        t = tasks.get(task_id) if task_id else None
        if what == "out" and t and t.out_patch:
            target = t.out_patch
        elif what == "out":
            raise HTTPException(400, "no out_patch known for this task yet")
        elif what == "log":
            srcm = (t.params.get("srcm") if t else "") or ""
            target = os.path.dirname(os.path.abspath(srcm))
        if not target or not os.path.isdir(target):
            raise HTTPException(404, "folder not found: %s" % target)
        subprocess.Popen(["explorer", os.path.normpath(target)])
        return {"opened": target}

    # ------------------------------------------------------------- rollback
    @app.post("/api/uninstall")
    def uninstall(body: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
        """Rollback = run the uninstall.ps1 that the build already produced.
        No new rollback logic lives in the GUI (that is the whole point)."""
        t = tasks.get(body.get("task_id") or "")
        out_patch = (body.get("out_patch") or (t.out_patch if t else "") or "")
        if not out_patch or not os.path.isdir(out_patch):
            raise HTTPException(400, "out_patch not found")
        ps1 = os.path.join(out_patch, "uninstall.ps1")
        if not os.path.isfile(ps1):
            raise HTTPException(404, "uninstall.ps1 not found in %s" % out_patch)
        paks = body.get("paks") or (t.params.get("paks") if t else "") or ""
        argv = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1]
        if paks:
            argv += ["-Paks", paks]
        r = subprocess.run(argv, capture_output=True, text=True)
        return {"rc": r.returncode,
                "stdout": (r.stdout or "")[-4000:],
                "stderr": (r.stderr or "")[-4000:]}

    # -------------------------------------------------------------- static UI
    d = dist_dir()
    if os.path.isdir(d):
        app.mount("/", StaticFiles(directory=d, html=True), name="ui")
    else:
        @app.get("/")
        def _missing() -> Dict[str, Any]:
            return {"error": "gui/dist not built yet", "expected": d}
    return app


def _sse(event: str, payload: Dict) -> str:
    return "event: %s\ndata: %s\n\n" % (event, json.dumps(payload, ensure_ascii=False))


def _log_text(t) -> str:
    """Everything we know about one task, as one UTF-8 text file.

    Three sources, in the order a developer wants to read them: the header
    (params / verdict), the live SSE stream we buffered, and -- when the build
    got far enough to write them -- the on-disk build.log and build_report.json
    that the CLI pipeline produced.
    """
    if t is None:
        return ""
    head = [
        "CalaPlayerSrcmBuilder GUI - build log",
        "=" * 72,
        "task      : %s" % t.id,
        "params    : %s" % json.dumps(t.params, ensure_ascii=False, sort_keys=True),
        "started   : %s" % (t.started or ""),
        "finished  : %s" % (t.finished or ""),
        "stage     : %s" % (t.stage or ""),
        "canceled  : %s" % bool(getattr(t, "cancel", None) and t.cancel.is_set()),
        "ok        : %s" % t.ok,
        "error     : %s" % (t.error or "-"),
        "out_patch : %s" % (t.out_patch or "-"),
        "",
    ]
    body = list(t.buffer or [])
    parts = head + ["=" * 72, "live log stream", "=" * 72] + body
    for name in ("build.log", "build_report.json"):
        p = os.path.join(t.out_patch or "", name)
        if t.out_patch and os.path.isfile(p):
            parts += ["", "=" * 72, name, "=" * 72]
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    parts.append(fh.read())
            except OSError as e:  # noqa: BLE001
                parts.append("<unreadable: %s>" % e)
    text = "\n".join(parts).strip("\n")
    return (text + "\n") if text else ""



class _NullStream(io.TextIOBase):
    """Stand-in for a missing std stream.  A --windowed exe has no console, so
    PyInstaller leaves sys.stdout/sys.stderr as None unless the parent handed
    over real handles -- Explorer does not, a shell with pipes does."""

    encoding = "utf-8"
    errors = "replace"

    def write(self, s):  # noqa: D102
        return len(s)

    def flush(self):  # noqa: D102
        pass

    def isatty(self):  # noqa: D102
        return False

    def writable(self):  # noqa: D102
        return True


def ensure_std_streams() -> None:
    """Make sys.stdout/sys.stderr safe when there is no console.

    uvicorn's log formatter calls ``sys.stdout.isatty()`` while configuring
    logging, so a plain double-click of the windowed exe used to die with
    "Unable to configure formatter 'default'" (AttributeError: 'NoneType'
    object has no attribute 'isatty') behind a modal PyInstaller
    "Unhandled exception in script" box -- the app looked like it never
    started.  Called from both server entry points.
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, _NullStream())


def run_server(port: int, log_level: str = "warning"):
    """Blocking uvicorn run (used by the headless mode)."""
    import uvicorn
    ensure_std_streams()
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level=log_level)


def start_server_thread(port: int, log_level: str = "warning"):
    """Start uvicorn on a daemon thread; returns the Server (call .should_exit)."""
    import uvicorn
    ensure_std_streams()
    config = uvicorn.Config(create_app(), host="127.0.0.1", port=port,
                            log_level=log_level, access_log=False)
    server = uvicorn.Server(config)
    import threading
    th = threading.Thread(target=server.run, name="cala-gui-http", daemon=True)
    th.start()
    return server, th
