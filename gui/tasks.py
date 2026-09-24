# -*- coding: utf-8 -*-
"""Task registry + worker threads for the GUI.

Design constraints (from the approved plan):
  * the GUI must NOT re-implement the pipeline -- it builds the SAME
    `core.builder.Builder` the CLI builds, with the same `Ctx`;
  * live logs come from `core.common.Log.add_sink`, so `core/` stays untouched;
  * cancellation happens at log boundaries during L0~L4 (everything up to there
    writes only inside `out_patch`).  From the first L5 line onwards cancellation
    is IGNORED, so the deploy step always either completes or rolls back -- never
    half-applied.
"""
from __future__ import annotations

import os
import queue
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.builder import Builder, Ctx  # noqa: E402
from core.common import BuildError, Log  # noqa: E402

MAX_BUFFERED_LINES = 800          # kept for SSE reconnects
DEFAULT_LOG_NAME = "build.log"


class BuildCanceled(Exception):
    """Raised inside the builder thread when the user presses Cancel."""


class CancelableLog(Log):
    """`Log` + a cancellation check, WITHOUT touching core/common.py.

    Raising from the log call is the only cancellation hook we get for free:
    the builder logs at every stage transition, so this gives stage-boundary
    (actually finer) granularity while leaving `core/` byte-identical.
    """

    def __init__(self, *a, cancel: Optional[threading.Event] = None, **kw):
        super().__init__(*a, **kw)
        self._cancel = cancel
        self._armed = True

    def _check(self) -> None:
        if not self._armed or self._cancel is None:
            return
        if self._cancel.is_set():
            raise BuildCanceled("cancelled by the user")

    def __call__(self, stage: str, msg: str = "") -> None:
        super().__call__(stage, msg)
        if stage == "L5":
            # the deploy step must be atomic: stop honouring Cancel here
            self._armed = False
        self._check()

    def raw(self, text: str) -> None:
        super().raw(text)
        self._check()


@dataclass
class Task:
    id: str
    params: Dict[str, Any]
    queue: "queue.Queue" = field(default_factory=queue.Queue)
    cancel: threading.Event = field(default_factory=threading.Event)
    buffer: deque = field(default_factory=lambda: deque(maxlen=MAX_BUFFERED_LINES))
    thread: Optional[threading.Thread] = None
    started: float = field(default_factory=time.time)
    finished: Optional[float] = None
    ok: Optional[bool] = None
    report: Optional[Dict] = None
    error: Optional[str] = None
    stage: str = ""
    done: threading.Event = field(default_factory=threading.Event)
    out_patch: Optional[str] = None

    # ------------------------------------------------------------------ push
    def push(self, line: str) -> None:
        self.buffer.append(line)
        self.queue.put({"kind": "line", "line": line})
        # stage tracking for the progress bar: "[ts] [L2] message"
        try:
            parts = line.split("] [")
            if len(parts) >= 2:
                st = parts[1].split("]")[0].strip()
                if st and st[0] == "L" and st != self.stage:
                    self.stage = st
                    self.queue.put({"kind": "stage", "stage": st, "line": line})
        except Exception:  # noqa: BLE001
            pass

    def push_event(self, kind: str, payload: Dict) -> None:
        self.buffer.append("<%s %s>" % (kind, payload))
        self.queue.put(dict(payload, kind=kind))

    def summary(self) -> Dict:
        return {"id": self.id, "params": self.params, "started": self.started,
                "finished": self.finished, "ok": self.ok, "error": self.error,
                "stage": self.stage, "canceled": self.cancel.is_set(),
                "out_patch": self.out_patch,
                "seconds": round((self.finished or time.time()) - self.started, 2)}


_TASKS: Dict[str, Task] = {}
_LOCK = threading.Lock()


def get(task_id: str) -> Optional[Task]:
    with _LOCK:
        return _TASKS.get(task_id)


def all_tasks() -> List[Dict]:
    with _LOCK:
        return [t.summary() for t in _TASKS.values()]


def request_cancel(task_id: str) -> bool:
    t = get(task_id)
    if not t or t.done.is_set():
        return False
    t.cancel.set()
    t.push("<cancellation requested>")
    return True


def start(params: Dict[str, Any]) -> Task:
    """Create a task and run the build in a worker thread."""
    tid = uuid.uuid4().hex[:12]
    task = Task(id=tid, params=dict(params))
    with _LOCK:
        _TASKS[tid] = task
    task.thread = threading.Thread(target=_run, args=(task,), name="cala-build-%s" % tid,
                                   daemon=True)
    task.thread.start()
    return task


# --------------------------------------------------------------------------
def _run(task: Task) -> None:
    p = task.params
    srcm = os.path.abspath(p["srcm"])
    log_path = os.path.join(os.path.dirname(srcm), DEFAULT_LOG_NAME)
    ctx = Ctx(paks_arg=p["paks"], srcm_arg=srcm,
              fit=p.get("fit", "cover"), force=bool(p.get("force")),
              dry_run=bool(p.get("dry_run")), combined=bool(p.get("combined")),
              ffmpeg=p.get("ffmpeg") or None, kit_dir=p.get("kit") or None)
    log = CancelableLog(path=log_path, echo=False, cancel=task.cancel)
    log.add_sink(task.push)
    b = Builder(ctx, log)
    task.out_patch = None
    try:
        rep = b.run()
        task.ok = True
        task.report = rep
        task.out_patch = ctx.out_patch
    except BuildCanceled as e:
        task.ok = False
        task.error = "已取消（取消发生在 L5 之前，游戏目录未被改动）/ canceled: %s" % e
        task.report = b.report(False, task.error)
        task.out_patch = ctx.out_patch
    except BuildError as e:
        task.ok = False
        task.error = str(e)
        task.report = b.report(False, task.error)
        task.out_patch = ctx.out_patch
    except Exception as e:  # noqa: BLE001
        import traceback
        task.ok = False
        task.error = "%s: %s" % (type(e).__name__, e)
        try:
            log.raw(traceback.format_exc())
            task.report = b.report(False, task.error)
        except Exception:  # noqa: BLE001
            task.report = None
        task.out_patch = ctx.out_patch
    finally:
        task.finished = time.time()
        log.close()
        task.push_event("done", {"ok": bool(task.ok), "error": task.error,
                                 "out_patch": task.out_patch,
                                 "seconds": round(task.finished - task.started, 2)})
        task.done.set()
