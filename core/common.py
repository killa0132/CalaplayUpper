# -*- coding: utf-8 -*-
"""CalaPlayerSrcmBuilder - shared primitives.

Design contract (do not weaken):
  * L1..L4 may ONLY write inside <out_patch>.  Only L5 touches the game folder.
  * every external command is logged verbatim into build.log
  * every failure carries the object/command/stage it happened at (never a bare FAIL)
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Sequence


# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------
class BuildError(RuntimeError):
    """Fatal, stage-tagged build failure."""

    def __init__(self, stage: str, what: str, detail: str = ""):
        self.stage = stage
        self.what = what
        self.detail = detail
        msg = "[%s] %s" % (stage, what)
        if detail:
            msg += "\n      -> " + detail
        super().__init__(msg)


# --------------------------------------------------------------------------
# logging bus (also feeds the future FastAPI/SSE GUI)
# --------------------------------------------------------------------------
class Log:
    """Append-only log with stage tags; sinks let the GUI stream lines live."""

    def __init__(self, path: Optional[str] = None, echo: bool = True):
        self.path = path
        self.echo = echo
        self.lines: List[str] = []
        self.sinks: List[Callable[[str], None]] = []
        self._fh = None
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self._fh = open(path, "w", encoding="utf-8", newline="\n")

    def add_sink(self, fn: Callable[[str], None]) -> None:
        self.sinks.append(fn)

    def __call__(self, stage: str, msg: str = "") -> None:
        line = "[%s] [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), stage, msg)
        self.lines.append(line)
        if self._fh:
            self._fh.write(line + "\n")
            self._fh.flush()
        for s in self.sinks:
            try:
                s(line)
            except Exception:
                pass
        if self.echo:
            try:
                print(line, flush=True)
            except Exception:
                pass

    def raw(self, text: str) -> None:
        """Already-formatted line (used to mirror tool output)."""
        self.lines.append(text)
        if self._fh:
            self._fh.write(text + "\n")
            self._fh.flush()
        for s in self.sinks:
            try:
                s(text)
            except Exception:
                pass
        if self.echo:
            try:
                print(text, flush=True)
            except Exception:
                pass

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


# --------------------------------------------------------------------------
# hashing / filesystem helpers
# --------------------------------------------------------------------------
def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha16(path: str) -> str:
    return sha256_file(path)[:16].upper()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def rmtree(path: str) -> None:
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def hardlink_or_copy(src: str, dst: str, log: Optional[Log] = None,
                     stage: str = "L0") -> str:
    """Stage a (possibly huge) file without copying when possible.

    The game folder must never be written; hardlinks are free and keep the
    original bytes.  Falls back to symlink, then to a real copy (with a warning
    because a 900 MB ucas copy is slow).
    """
    ensure_dir(os.path.dirname(os.path.abspath(dst)))
    if os.path.exists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
        return "hardlink"
    except OSError:
        pass
    try:
        os.symlink(src, dst)
        return "symlink"
    except OSError:
        pass
    if log:
        log(stage, "WARN: cannot hardlink %s -> %s, doing a full copy" % (src, dst))
    shutil.copy2(src, dst)
    return "copy"


# --------------------------------------------------------------------------
# subprocess
# --------------------------------------------------------------------------
@dataclass
class ProcResult:
    argv: Sequence[str]
    rc: int
    out: str
    err: str
    seconds: float
    cwd: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.rc == 0

    def tail(self) -> str:
        body = (self.err.strip() or self.out.strip())
        return body[-1200:] if body else ""


def _fmt_argv(argv: Sequence[str]) -> str:
    return " ".join('"%s"' % a if (" " in a or not a) else a for a in argv)


def run(argv: Sequence[str], cwd: Optional[str] = None, timeout: int = 900,
        log: Optional[Log] = None, stage: str = "", echo_stdout: bool = False,
        env: Optional[dict] = None) -> ProcResult:
    argv = [str(a) for a in argv]
    if log:
        log(stage, "CMD: %s%s" % (_fmt_argv(argv), ("   (cwd=%s)" % cwd) if cwd else ""))
    t0 = time.time()
    real_env = os.environ.copy()
    if env:
        real_env.update(env)
    try:
        p = subprocess.run(argv, cwd=cwd, timeout=timeout, env=real_env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = p.stdout.decode("utf-8", "replace")
        err = p.stderr.decode("utf-8", "replace")
        rc = p.returncode
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode("utf-8", "replace")
        err = ((e.stderr or b"").decode("utf-8", "replace")
               + "\nTIMEOUT after %ss" % timeout)
        rc = 124
    except FileNotFoundError as e:
        out, err, rc = "", "executable not found: %s" % e, 127
    secs = time.time() - t0
    if log:
        for ln in out.splitlines():
            if echo_stdout:
                log.raw("    | " + ln)
        for ln in err.splitlines():
            log.raw("    ! " + ln)
        if echo_stdout or err.strip():
            log(stage, "rc=%d (%.2fs)" % (rc, secs))
    return ProcResult(argv, rc, out, err, secs, cwd)


def run_ok(argv: Sequence[str], **kw) -> ProcResult:
    r = run(argv, **kw)
    if not r.ok:
        stage = kw.get("stage", "?")
        raise BuildError(stage, "command failed (rc=%d): %s" % (r.rc, _fmt_argv([str(a) for a in argv])),
                         r.tail())
    return r


# --------------------------------------------------------------------------
# misc
# --------------------------------------------------------------------------
def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0
    return "%d B" % n


def reconfigure_stdio() -> None:
    """Keep the Windows console from mojibake-ing our UTF-8 output."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
