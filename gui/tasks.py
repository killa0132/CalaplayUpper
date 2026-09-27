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
from core.deploy import DEFAULT_BASE as DEPLOY_BASE, install as deploy_install  # noqa: E402
from core.merger import merge_mods  # noqa: E402

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
        if stage in ("L5", "M7"):
            # 部署（单包 L5 / 合并 M7）必须是原子的：到这里就不再理会取消
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
        # stage tracking for the progress bar: "[ts] [L2] message" for a single
        # build, "[ts] [M3] message" for a mod merge (CP-38)
        try:
            parts = line.split("] [")
            if len(parts) >= 2:
                st = parts[1].split("]")[0].strip()
                if len(st) >= 2 and st[0] in "LM" and st[1:].isdigit() and st != self.stage:
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


def start_merge(params: Dict[str, Any]) -> Task:
    """Create a task and run a multi-mod merge in a worker thread.

    The merge goes through `core.merger.merge_mods()` -- the SAME engine the CLI
    uses -- so the GUI never re-implements the protocol (and `core/` stays the
    single source of truth).  Merge-level failures come back as a report with
    `ok=false`, not as an exception, so the page always gets a verdict.
    """
    tid = uuid.uuid4().hex[:12]
    task = Task(id=tid, params=dict(params))
    with _LOCK:
        _TASKS[tid] = task
    task.thread = threading.Thread(target=_run_merge, args=(task,),
                                   name="cala-merge-%s" % tid, daemon=True)
    task.thread.start()
    return task


# --------------------------------------------------------------------------
def _run_merge(task: Task) -> None:
    p = task.params
    mods = os.path.abspath(p["mods"])
    out = os.path.abspath(p["out"])
    os.makedirs(out, exist_ok=True)
    log = CancelableLog(path=os.path.join(out, "merge.log"), echo=False,
                        cancel=task.cancel)
    log.add_sink(task.push)
    task.out_patch = out
    try:
        kit_obj = None
        if p.get("kit"):
            # same meaning as the CLI's -Kit: use that tool folder instead of the
            # one next to the exe / in the project tree
            from core.kit import load_kit
            kit_obj = load_kit(p["kit"], None, log, "M0")
        rep = merge_mods(mods, p.get("paks") or "", out, p.get("select") or None,
                         log=log, kit=kit_obj, keep_work=bool(p.get("keep_work")))
        d = rep.to_dict()
        task.ok = bool(d.get("ok"))
        task.report = d
        task.error = None if task.ok else (d.get("error") or "合并失败")

        # ---- CP-41：合并成功后**自动安装**（除非勾了「仅产出不安装」）----------
        # 这一步与单包 L5 同一套约定：写前备份 → 写入 → 逐文件读回 sha256 →
        # 任一步不符就自动还原；失败时任务判失败，但报告里保留合并结果。
        if task.ok and not bool(p.get("dry_run")):
            base = (d.get("container") or {}).get("base") or DEPLOY_BASE
            # 安装目标 = 合并器**解析出来的**干净基底（用户填的可能是游戏根目录，
            # 而安装必须落在真正的 Content\Paks 上）
            target = (d.get("resolved") or {}).get("paks_dir") or p.get("paks") or ""
            try:
                info = deploy_install(out, target, base=base, log=log, stage="M7")
                info["ok"] = True
                d["deploy"] = info
            except Exception as e:  # noqa: BLE001
                task.ok = False
                task.error = ("合并成功，但安装进游戏失败（游戏目录已自动还原）：%s"
                              % (str(e) or type(e).__name__))
                d["deploy"] = {"ok": False, "error": str(e) or type(e).__name__}
                log("M7", task.error)
        elif task.ok:
            d["deploy"] = None
            # 用 M6 这个标签（而不是 M7）：勾了「仅产出不安装」时不该出现部署阶段，
            # 否则进度条会显示一个根本没做的步骤
            log("M6", "仅产出不安装（DryRun）：容器留在 %s，游戏目录未被改动" % out)

    except BuildCanceled as e:
        task.ok = False
        task.error = "已取消（取消发生在打包之前，输出目录未被写入）/ canceled: %s" % e
        task.report = {"ok": False, "error": task.error}
    except Exception as e:  # noqa: BLE001
        import traceback
        task.ok = False
        task.error = "%s: %s" % (type(e).__name__, e)
        try:
            log.raw(traceback.format_exc())
        except Exception:  # noqa: BLE001
            pass
        task.report = {"ok": False, "error": task.error}
    finally:
        task.finished = time.time()
        log.close()
        task.push_event("done", {"ok": bool(task.ok), "error": task.error,
                                 "out_patch": task.out_patch,
                                 "seconds": round(task.finished - task.started, 2)})
        task.done.set()


# --------------------------------------------------------------------------
def _run(task: Task) -> None:
    p = task.params
    srcm = os.path.abspath(p["srcm"])
    log_path = os.path.join(os.path.dirname(srcm), DEFAULT_LOG_NAME)
    ctx = Ctx(paks_arg=p["paks"], srcm_arg=srcm,
              fit=p.get("fit", "cover"), force=bool(p.get("force")),
              dry_run=bool(p.get("dry_run")), combined=bool(p.get("combined")),
              ffmpeg=p.get("ffmpeg") or None, kit_dir=p.get("kit") or None,
              no_thumb=bool(p.get("no_thumb")), no_atlas=bool(p.get("no_atlas")),
              # CP-40: -ExportSrc (also write this build as a mergeable Mod)
              export_src=bool(p.get("export_src")), src_name=p.get("src_name") or "")
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
