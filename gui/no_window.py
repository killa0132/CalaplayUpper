# -*- coding: utf-8 -*-
"""Stop every child process from flashing a console window ("CMD 黑框").

The desktop shell is a `--windowed` process: it has no console of its own, so
every console-subsystem child it spawns -- da-patch, tex-inspect, retoc, ffmpeg,
powershell -- gets a brand new console window, one per invocation.  A 50-image
build calls da-patch 200+ times, which is exactly the storm of black boxes the
user reported.

`core/common.py` is frozen (it may not change by a single byte), so instead of
touching its `run()` we patch the stdlib once, in this process only:

    subprocess.Popen(...)  ->  creationflags |= CREATE_NO_WINDOW

`subprocess.run / call / check_call / check_output` all funnel through
`Popen.__init__`, so one patch covers the whole pipeline (and anything else the
GUI spawns, e.g. the generated install.ps1 / uninstall.ps1).

The patch is deliberately conservative:
  * Windows only.
  * a caller that already asked for DETACHED_PROCESS is left alone;
  * an explicit creationflags from the caller is preserved (we only OR in);
  * the original __init__ is kept, so nothing else about Popen changes.

`probe()` exists for the self-test: it reports whether the patch is live and
whether a console window really is suppressed (with a positive control so the
check can never pass vacuously).
"""
from __future__ import annotations

import subprocess
import sys
import threading

#: winbase.h
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008

_LOCK = threading.Lock()
_ORIG = None
_SLOT = -1              # positional index of creationflags in Popen.__init__(*args)

INSTALLED = False
CALLS = 0
LAST_FLAGS = 0


def _creationflags_slot(func) -> int:
    """Where does `creationflags` sit in `Popen.__init__(self, *args)`?

    Computed from the real signature instead of being hard-coded, so a future
    Python that reorders the parameters cannot silently break the patch.
    """
    try:
        names = list(func.__code__.co_varnames[:func.__code__.co_argcount])
        return names.index("creationflags") - 1     # -1: drop `self`
    except Exception:  # noqa: BLE001
        return -1


def install() -> bool:
    """Patch `subprocess.Popen.__init__`.  Idempotent; True = patch is live."""
    global _ORIG, INSTALLED, _SLOT
    if INSTALLED:
        return True
    if sys.platform != "win32":
        return False
    with _LOCK:
        if INSTALLED:
            return True
        _ORIG = subprocess.Popen.__init__
        _SLOT = _creationflags_slot(_ORIG)

        def patched(self, *a, **kw):                  # noqa: ANN001
            global CALLS, LAST_FLAGS
            flags = int(kw.get("creationflags", 0) or 0)
            if 0 <= _SLOT < len(a):
                try:
                    flags = int(a[_SLOT] or 0)
                except (TypeError, ValueError):
                    flags = 0
            if not flags & DETACHED_PROCESS:
                flags |= CREATE_NO_WINDOW
                kw["creationflags"] = flags
            CALLS += 1
            LAST_FLAGS = flags
            return _ORIG(self, *a, **kw)

        patched.__wrapped__ = _ORIG
        subprocess.Popen.__init__ = patched
        INSTALLED = True
        return True


def uninstall() -> None:
    """Undo the patch (the self-test's positive control needs this)."""
    global INSTALLED
    with _LOCK:
        if INSTALLED and _ORIG is not None:
            subprocess.Popen.__init__ = _ORIG
        INSTALLED = False


# --------------------------------------------------------------------------
# observation, for the self-test
# --------------------------------------------------------------------------
def count_console_windows() -> int:
    """Visible top-level windows of class ConsoleWindowClass (= a classic black box)."""
    if sys.platform != "win32":
        return 0
    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32
    hits = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _l):
        if not u.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(hwnd, buf, 64)
        if buf.value == "ConsoleWindowClass":
            hits.append(hwnd)
        return True

    u.EnumWindows(cb, 0)
    return len(hits)


def has_console() -> bool:
    """Does *this* process own a console?  (A windowed exe does not.)"""
    if sys.platform != "win32":
        return False
    import ctypes

    return bool(ctypes.windll.kernel32.GetConsoleWindow())


def spawn_raw(argv, **kw):
    """Popen a child that does NOT get the patch -- the positive control.

    Calling `Popen.__init__` directly (bypassing the patched attribute) keeps
    the rest of the process protected while we deliberately reproduce the bug.
    """
    p = object.__new__(subprocess.Popen)
    (_ORIG or subprocess.Popen.__init__)(p, argv, **kw)
    return p


def _console_window_of(pid: int) -> int:
    """The console window the *child* owns: 0 = none, -1 = it has no console.

    Counting `ConsoleWindowClass` windows does NOT work on Windows 11, where a
    new console is usually hosted by Windows Terminal instead of conhost -- the
    positive control proved that (it saw nothing even with the patch removed).
    Attaching to the child's console and asking for its window is deterministic,
    and only safe when we own no console ourselves, so callers check that first.
    """
    import ctypes

    k32 = ctypes.windll.kernel32
    k32.FreeConsole()
    if not k32.AttachConsole(int(pid)):
        return -1
    try:
        return int(k32.GetConsoleWindow() or 0)      # kernel32, not user32
    finally:
        k32.FreeConsole()


def _spawn_hwnd(patched: bool) -> int:
    """Run a short-lived console child and report the console window it owns."""
    argv = ["cmd", "/c", "ping -n 3 127.0.0.1 >nul"]
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL)
    p = subprocess.Popen(argv, **kw) if patched else spawn_raw(argv, **kw)
    try:
        import time
        time.sleep(0.8)                 # let the console come up
        return _console_window_of(p.pid)
    finally:
        try:
            p.kill()
            p.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass


def probe(control: bool = True) -> dict:
    """Prove that a console child really gets no console window.

    The property only exists when *this* process has no console: a child of a
    console process inherits that console, so there is no window either way and
    the whole question is moot (the source-mode self-test says so instead of
    pretending to have verified something).
    """
    out = {"installed": INSTALLED, "parent_has_console": has_console(),
           "calls": CALLS, "last_flags": LAST_FLAGS,
           "last_flags_no_window": bool(LAST_FLAGS & CREATE_NO_WINDOW),
           "console_windows": count_console_windows(),
           "patched_hwnd": None, "control_hwnd": None}
    if sys.platform != "win32":
        out["skipped"] = "not windows"
        out["ok"] = True
        return out
    if out["parent_has_console"]:
        out["note"] = ("this parent owns a console, so children inherit it -- no "
                       "window can pop up either way; the frozen windowed exe is "
                       "where the property is real")
        out["ok"] = out["installed"]
        return out

    out["patched_hwnd"] = _spawn_hwnd(patched=True)
    if control:
        out["control_hwnd"] = _spawn_hwnd(patched=False)
    out["ok"] = (out["patched_hwnd"] == 0
                 and (out["control_hwnd"] not in (None, 0, -1)))
    out["console_windows_after"] = count_console_windows()
    return out
