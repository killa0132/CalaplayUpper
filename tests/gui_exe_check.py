# -*- coding: utf-8 -*-
"""G4 verification: the shipped GUI exe.

    python tests/gui_exe_check.py                 # newest gui_minimal in dist/
    python tests/gui_exe_check.py --exe <path>

Two checks, in the order a user would hit them:

 1. DOUBLE-CLICK: launch the exe with no arguments and prove a real top-level
    window appears and responds.  The window belongs to the PyInstaller
    *child* process (onefile forks), so we enumerate top-level windows and
    match them by the owning process' image path -- never "the process is
    alive".
 2. SELF-TEST: run the exe with --selftest --selftest-ui --selftest-shell and
    read the --log-file it wrote (a --windowed build has no usable stdout),
    then assert the exit code and the evidence lines.
 3. NO-CONSOLE STARTUP: launch --headless --selftest through ShellExecuteW (no
    inherited std handles, exactly like a double-click) and require the HTTP API
    to come up.  This is the regression test for the uvicorn/sys.stdout=None
    crash that check 1's earlier Popen-based version could not see.
"""
from __future__ import annotations

import argparse
import ctypes
import locale
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes

# our own stdout is a GBK console on this machine; dumping an exe log line that
# contains a character GBK cannot encode would kill the checker itself
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _decode(data: bytes) -> str:
    """UTF-8 first, but a --windowed exe's redirected stdout uses the ANSI code
    page (GBK here), so fall back to that when UTF-8 leaves replacement chars."""
    txt = data.decode("utf-8", "replace")
    if "\ufffd" in txt:
        try:
            alt = data.decode(locale.getpreferredencoding(False), "replace")
            if alt.count("\ufffd") < txt.count("\ufffd"):
                txt = alt
        except Exception:  # noqa: BLE001
            pass
    return txt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FAKEGAME = os.path.join(HERE, "fakegame")
SRCM = os.path.join(HERE, "mat", "demo")

u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WM_NULL = 0x0000
SMTO_ABORTIFHUNG = 0x0002

FAILS = []


def check(cond, msg):
    print("  %s %s" % ("PASS" if cond else "FAIL", msg))
    if not cond:
        FAILS.append(msg)


def _pid_image(pid: int) -> str:
    """Full executable path of a pid ('' when it cannot be read)."""
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        k32.CloseHandle(h)


def top_level_windows():
    """[(hwnd, pid, title, class, visible)] for every top-level window."""
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _l):
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        t = ctypes.create_unicode_buffer(512)
        u32.GetWindowTextW(hwnd, t, 512)
        c = ctypes.create_unicode_buffer(256)
        u32.GetClassNameW(hwnd, c, 256)
        out.append((hwnd, pid.value, t.value, c.value, bool(u32.IsWindowVisible(hwnd))))
        return True

    u32.EnumWindows(cb, 0)
    return out


def responding(hwnd, timeout_ms=2000) -> bool:
    res = ctypes.c_ulonglong(0)
    r = u32.SendMessageTimeoutW(hwnd, WM_NULL, 0, 0, SMTO_ABORTIFHUNG,
                                timeout_ms, ctypes.byref(res))
    return bool(r)


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def rm_retry(path: str, tries: int = 24, delay: float = 0.5) -> bool:
    """Delete a file another process may still hold open.

    On Windows the handle survives until the process really exits, so removing
    the exe's --log-file before killing the exe is a race (it already blew up
    once with WinError 32 in the middle of check 3).
    """
    for _i in range(tries):
        try:
            if os.path.isfile(path):
                os.remove(path)
            return True
        except OSError:
            time.sleep(delay)
    print("      (could not remove %s -- still locked)" % path)
    return False


def _dlg_text(hwnd) -> str:
    """Text of a child control of a modal dialog (static controls need WM_GETTEXT)."""
    n = u32.SendMessageW(hwnd, 0x000E, 0, 0)  # WM_GETTEXTLENGTH
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 2)
    u32.SendMessageW(hwnd, 0x000D, n + 2, ctypes.cast(buf, ctypes.c_void_p))
    return buf.value


def _dialog_text(top) -> str:
    """Everything inside a PyInstaller 'Unhandled exception in script' box."""
    parts = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _l):
        t = _dlg_text(hwnd)
        if t.strip():
            parts.append(t)
        return True

    u32.EnumChildWindows(top, cb, 0)
    return "\n".join(parts)


def find_exe(override=None) -> str:
    if override:
        return os.path.abspath(override)
    dist = os.path.join(ROOT, "dist")
    if os.path.isdir(dist):
        for d in sorted(os.listdir(dist), reverse=True):
            p = os.path.join(dist, d, "CalaPlayerSrcmBuilderGUI.exe")
            if os.path.isfile(p):
                return p
    raise SystemExit("no CalaPlayerSrcmBuilderGUI.exe found -- run build_gui.ps1 first")


def double_click(exe: str) -> int:
    print("[1] double-click: %s" % exe)
    # ShellExecuteW is literally what Explorer does on a double-click: no
    # STARTF_USESTDHANDLES, so a --windowed exe gets sys.stdout = None.  Using
    # subprocess here would hand over valid handles and hide exactly the bug
    # that made a real double-click die behind a modal crash box.
    rc = ctypes.windll.shell32.ShellExecuteW(None, "open", exe, None,
                                             os.path.dirname(exe), 1)
    check(rc > 32, "ShellExecute opened the exe (rc=%d)" % rc)
    print("      launched the way Explorer does (no inherited stdout/stderr)")
    hwnd = None
    dialog = None
    deadline = time.time() + 90
    # ONLY pids whose image is this exe.  It is tempting to record every pid we
    # can read an image path for, but those are all the visible windows on the
    # desktop -- and the cleanup below kills them.  That killed the harness (and
    # any other windowed app the user had open) on the first run of this test.
    ours = set()
    while time.time() < deadline:
        for h, pid, title, cls, vis in top_level_windows():
            if not vis:
                continue
            img = _pid_image(pid)
            if not img or os.path.normcase(img) != os.path.normcase(exe):
                continue
            ours.add(pid)
            if "Unhandled exception" in title or "Failed to execute script" in title:
                dialog = (h, pid, title, cls)
                continue
            if "PyInstaller" in cls or "Hidden" in cls:
                continue
            if hwnd is None:
                hwnd = (h, pid, title, cls)
        if hwnd or dialog:
            break
        time.sleep(0.5)

    try:
        check(dialog is None,
              "no PyInstaller crash dialog (a double-click must not pop a modal "
              "'Unhandled exception' box)")
        if dialog:
            print("      CRASH DIALOG: hwnd=0x%X title=%r" % (dialog[0], dialog[2]))
            for line in _dialog_text(dialog[0]).splitlines():
                print("      ! " + line)
        check(hwnd is not None,
              "a real top-level window belonging to the exe appeared (exe pids seen: %d)"
              % len(ours))
        if hwnd:
            h, pid, title, cls = hwnd
            print("      hwnd=0x%X pid=%d class=%s title=%r" % (h, pid, cls, title))
            check(responding(h), "the window answers SendMessageTimeout(WM_NULL)")
            check("CalaPlayer" in title,
                  "the window title says CalaPlayer (got %r)" % title)
    finally:
        # onefile = bootloader + child; kill the tree we started, nothing else
        for pid in ours:
            kill_tree(pid)
        time.sleep(1.0)
    return 0


def no_console_headless(exe: str) -> int:
    """uvicorn must configure its logging with sys.stdout == None.

    This is the bug that got past the first version of this test: launched from
    a shell the exe inherits stdout/stderr, but a double-click gets neither, and
    uvicorn's log formatter calls sys.stdout.isatty() -> AttributeError ->
    'Unable to configure formatter default' behind a modal crash box.
    ShellExecuteW reproduces the double-click environment exactly.
    """
    print("[3] no-console startup (uvicorn logging with sys.stdout == None)")
    logf = os.path.join(tempfile.gettempdir(), "cala_gui_headless_%d.txt" % os.getpid())
    if os.path.isfile(logf):
        os.remove(logf)
    args = '--headless --selftest --log-file "%s"' % logf
    rc = ctypes.windll.shell32.ShellExecuteW(None, "open", exe, args,
                                             os.path.dirname(exe), 1)
    check(rc > 32, "ShellExecute opened the exe with --headless (rc=%d)" % rc)
    log = ""
    deadline = time.time() + 60
    while time.time() < deadline:
        if os.path.isfile(logf):
            log = open(logf, encoding="utf-8", errors="replace").read()
            if "token guard" in log:
                break
        time.sleep(0.5)
    for line in log.splitlines():
        print("      | " + line)
    check("token guard: OK" in log,
          "the HTTP API came up with no console (uvicorn logging configured)")
    check("403" in log or "token guard: OK" in log,
          "an unauthenticated /api request was refused (403)")
    # tear the exe down FIRST, then remove its log file
    for _h, pid, _t, _c, _v in top_level_windows():
        img = _pid_image(pid)
        if img and os.path.normcase(img) == os.path.normcase(exe):
            kill_tree(pid)
    time.sleep(1.0)
    rm_retry(logf)
    return 0


def selftest(exe: str, keep_log: bool = False) -> int:
    print("[2] self-test through the frozen exe (windowed -> logs to a file)")
    # CP-41：自检里那一下"合并 → 自动安装"用的是 tests/regression.py 造的 Mod 夹具
    # （T30）。夹具不在就先把它造出来，否则这一步会静默 SKIP（判据就变弱了）。
    fixture = os.path.join(HERE, "mat", "merge", "ok")
    if not os.path.isdir(fixture):
        print("      building the merge fixture first (tests/regression.py --only T30)")
        try:
            subprocess.run([sys.executable, os.path.join(HERE, "regression.py"),
                            "--only", "T30"], cwd=ROOT, timeout=900,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:  # noqa: BLE001
            print("      fixture build failed: %s: %s" % (type(e).__name__, e))
        print("      fixture present: %s" % os.path.isdir(fixture))
    # the deliverable must not gain files just because the self-test ran a build
    # that gets rejected (a bad srcm folder used to leave a build.log next to the exe)
    kit = os.path.dirname(exe)
    before = {os.path.join(dp, f) for dp, _d, fs in os.walk(kit) for f in fs}
    logf = os.path.join(tempfile.gettempdir(), "cala_gui_selftest_%d.txt" % os.getpid())
    argv = [exe, "--selftest", "--selftest-ui", "--selftest-shell",
            "--paks", FAKEGAME, "--srcm", SRCM, "--log-file", logf,
            # CP-41：冻结 exe 的 _ROOT 是自己的解包目录，夹具路径必须显式传
            "--merge-fixture", os.path.join(HERE, "mat", "merge", "ok"),
            "--selftest-seconds", "60"]
    t0 = time.time()
    out_f = os.path.join(tempfile.gettempdir(), "cala_gui_out_%d.txt" % os.getpid())
    err_f = os.path.join(tempfile.gettempdir(), "cala_gui_err_%d.txt" % os.getpid())
    with open(out_f, "wb") as o, open(err_f, "wb") as e:
        p = subprocess.run(argv, cwd=os.path.dirname(exe), stdout=o, stderr=e,
                           timeout=900)
    secs = time.time() - t0
    # a --windowed exe normally has nowhere to print; with real handles these
    # files catch whatever it did say (and any thread traceback)
    for stream, path in (("stdout", out_f), ("stderr", err_f)):
        txt = _decode(open(path, "rb").read()) if os.path.isfile(path) else ""
        if txt.strip():
            print("      --- exe %s ---" % stream)
            for line in txt.splitlines()[-40:]:
                print("      " + line)
        if os.path.isfile(path):
            os.remove(path)
    log = ""
    if os.path.isfile(logf):
        log = open(logf, encoding="utf-8", errors="replace").read()
    if keep_log:
        kept = os.path.join(ROOT, "logs", "g4_selftest_full.txt")
        os.makedirs(os.path.dirname(kept), exist_ok=True)
        open(kept, "w", encoding="utf-8").write(log)
        print("      full log kept at %s" % kept)
    if os.path.isfile(logf):
        rm_retry(logf, tries=6)
    print("      rc=%d in %.1fs, %d log lines" % (p.returncode, secs, len(log.splitlines())))
    for line in log.splitlines():
        if any(k in line for k in ("window loaded", "vue mounted", "page->api",
                                   "token guard", "theme ", "ui guide", "i18n ",
                                   "ui scramble", "ui squish", "ui glide",
                                   "hub entries", "star popup", "star copy", "star buttons",
                                   "qq popup", "qq copy", "clipboard", "open_url",
                                   "layout ", "split drag", "split reset",
                                   "line sidebar", "line effects", "join ", "open_url api",
                                   "shots extra", "folder dialog",
                                   "dialog window", "ui driven", "ui gates", "ui log",
                                   "ui progress", "ui modal", "ui export", "ui no console",
                                   "ui page gen", "window icon", "ui shots", "SELFTEST",
                                   # CP-40
                                   "ui strict", "ui exportsrc", "ui notice", "ui runbar",
                                   "ui refill", "ui prog frame", "ui merge min",
                                   # CP-41
                                   "ui mergedry", "ui merge deploy", "ui guide scroll",
                                   "ui language", "ui rollback", "ui merge rollback")):
            print("      | " + line)
    check(p.returncode == 0, "the frozen exe exited 0")
    check("WINDOW OK" in log or "SHELL SELFTEST: OK" in log or "UI SELFTEST: OK" in log,
          "the self-test reported OK in the log file")
    check("vue mounted   : yes" in log, "the bundled Vue app mounted inside the exe")
    check("appeared=True" in log, "the native folder dialog really appeared")
    check("ui gates      :" in log and "False" not in log.split("ui gates      :")[1][:200],
          "every A0~A7 gate passed inside the exe")
    check("folder dialog : ok=True" in log, "the dialog call came back cleanly")
    # ---- the UI/UX round, verified inside the shipped exe -------------------
    def line_of(tag):
        for ln in log.splitlines():
            if ln.startswith(tag):
                return ln
        return ""

    check("overflow-y=auto" in line_of("ui log scroll") and "atBottom=True" in line_of("ui log scroll"),
          "the log panel scrolls on its own and follows the tail: %s" % line_of("ui log scroll"))
    # ---- i18n: the switch must really rewrite the page --------------------
    check("i18n zh       : lang=zh html=zh-CN" in log and "lang=en html=en" in log
          and "i18n back     : lang=zh" in log,
          "the language switch did not work inside the exe:\n        %s\n        %s\n        %s"
          % (line_of("i18n zh"), line_of("i18n en"), line_of("i18n back")))
    # ---- the first-run guide, walked inside the shipped exe ----------------
    gd = line_of("ui guide      :")
    check("shown=True" in gd and "hello.png" in gd and "end.png" in gd
          and "stored=True" in gd,
          "the guide opened, ran hello.png -> guide.png -> end.png and remembered "
          "the choice: %s" % gd)
    check("masked=" in gd and "masked=0" not in gd,
          "the guide never spotlighted a real element: %s" % gd)
    try:
        steps = int(gd.split("steps=")[1].split(" ")[0])
        masked = int(gd.split("masked=")[1].split(" ")[0])
        check(steps >= 9 and masked >= 7,
              "the guide is missing the -Force / Advanced steps (%d steps, %d spotlights)"
              % (steps, masked))
    except (IndexError, ValueError):
        check(False, "could not read the guide step counts: %s" % gd)
    # ---- round 6: the guide autoplays exactly once, and it is remembered in
    #      the durable store (localStorage could not: the page origin carries a
    #      fresh random port on every launch) ---------------------------------
    ga = line_of("ui guide acts :")
    check("rows=[1]" in ga and "nowrap=['nowrap']" in ga and "widest-overflow=0px" in ga,
          "the guide's button row wraps/squeezes/overflows its card: %s" % ga)
    ghole = line_of("ui guide hole :")
    check("in-view=" in ghole and "in-view=0 of" not in ghole,
          "the guide's spotlight was drawn off-screen: %s" % ghole)
    g2 = line_of("ui guide 2nd  :")
    check("guide=False" in g2 and "auto=False" in g2 and "stored=True" in g2,
          "the guide came back on the second run (it must only auto-open once): %s" % g2)
    pr = line_of("ui prefs      :")
    check("'cala-onboarded': '1'" in pr and "restored=" in pr,
          "the onboarding flag never reached the durable store: %s" % pr)
    bw = line_of("ui browse btn :")
    check("clipped=False" in bw and "icon=True" in bw and "flex=0/0" in bw,
          "the browse button squeezes its label: %s" % bw)
    lw = line_of("ui left width :")
    check("gutter=stable" in lw and "over=True>True" in lw,
          "the left column changes width when its content grows: %s" % lw)
    # ---- round 6b: the right side must FILL its column at every size --------
    # (a stray `.right` rule from the header used to leak into the work area's
    # right column: the split pane shrank to fit and floated in the middle)
    try:
        for tag in ("layout wide box:", "layout min  box:", "layout big  box:"):
            ln = line_of(tag)
            # `split=<w>px@<left>(right <right>) right=<w>px(right <left>)`
            part = ln.split("split=")[1]
            split_w = int(part.split("px")[0])
            split_r = int(part.split("(right ")[1].split(")")[0])
            rest = ln.split(" right=")[1]
            right_w = int(rest.split("px")[0])
            col_l = int(rest.split("(right ")[1].split(")")[0])
            col_r = col_l + right_w
            pane_al = int(ln.split("paneAL=")[1].split(" ")[0])
            task_r = int(ln.split("taskid.right=")[1].split(" ")[0])
            check(split_w == right_w and split_r == col_r and pane_al == col_l
                  and task_r == col_r,
                  "the right column is not filled at %s: %s" % (tag, ln))
    except (IndexError, ValueError):
        check(False, "could not read the right-column box metrics")
    omin = line_of("ui opt min    :")
    check("trunc=0/" in omin,
          "an option label is truncated at the minimum window size: %s" % omin)
    gh = line_of("ui glide hit  :")
    check("hit-row=1 of 1" in gh and "pos=fixed" in gh and "parent=BODY" in gh,
          "the open dropdown is painted behind another row: %s" % gh)
    ol = line_of("ui opt labels :")
    try:
        fit_h = int(ol.split("opt-fit': '")[1].split("x")[1].split("'")[0])
        check(fit_h <= 22,
              "the fit row label wrapped/truncated (height %s): %s" % (fit_h, ol))
    except (IndexError, ValueError):
        check(False, "could not read the option row geometry: %s" % ol)
    # ---- CP-40: -ExportSrc is a normal option row, and its switch really flips --
    xs = line_of("ui exportsrc  :")
    check("label='-ExportSrc'" in xs and "trunc=False" in xs and "h=16" in xs or
          ("label='-ExportSrc'" in xs and "trunc=False" in xs),
          "the -ExportSrc row is missing from the option list: %s" % xs)
    check("on False->True" in xs and "form False->True" in xs,
          "ticking -ExportSrc did not flip its switch / the build parameter: %s" % xs)
    check("opt-exportsrc" in ol,
          "the -ExportSrc row is not part of the option list: %s" % ol)
    md = line_of("ui merge min")
    check("card=" in md and "clip=0/" in md and "cardOver=0" in md,
          "the merge card does not fit the minimum window: %s" % md)
    # ---- CP-40: the protocol's hard rule must read as a rule -------------------
    st = line_of("ui strict     :")
    check("mark=True('!')" in st and "ruleSwitches=0" in st,
          "the strict-conflict rule is not a badge + text (or the row itself still has a "
          "switch): %s" % st)
    check("color=rgb(247, 231, 141)" in st or "color=rgb(165, 129, 28)" in st,
          "the strict rule is not gold: %s" % st)
    # ---- CP-40: the run/cancel row never spills out of the form column ---------
    for tag in ("ui runbar wide :", "ui runbar min  :"):
        rb = line_of(tag)
        try:
            spill = int(rb.split("spill=")[1].split(" ")[0])
            colo = int(rb.split("colOverflow=")[1].split(" ")[0])
            check(spill <= 1 and colo <= 0,
                  "the run/cancel row spills out of the form column: %s" % rb)
        except (IndexError, ValueError):
            check(False, "could not read the run-bar geometry: %s" % rb)
    # ---- CP-40: the pre-flight card (before a merge task is started) -----------
    for tag, want in (("ui notice empty   :", 3), ("ui notice bad path:", 1)):
        nt = line_of(tag)
        check("visible=True" in nt and "modal=''" in nt and "running=False" in nt,
              "a bad merge input started a task / showed the outcome modal: %s" % nt)
        try:
            lines = int(nt.split("lines=")[1].split(" ")[0])
            check(lines >= want,
                  "the pre-flight card lists %d problem(s), expected >= %d: %s"
                  % (lines, want, nt))
        except (IndexError, ValueError):
            check(False, "could not read the pre-flight card: %s" % nt)
    nerr = log.split("               errors=")
    check(len(nerr) >= 3 and "Mod 根目录未填写" in nerr[1] and "Paks" in nerr[1]
          and "输出目录未填写" in nerr[1],
          "the empty-input case does not list all three missing fields: %s"
          % (nerr[1][:160] if len(nerr) > 1 else ""))
    check(len(nerr) >= 3 and "不存在" in nerr[2],
          "a Mods folder that does not exist is not reported as such: %s"
          % (nerr[2][:160] if len(nerr) > 2 else ""))
    shots = line_of("              : notice=")
    check(all(n in shots for n in ("gui_shot_notice.png", "gui_shot_notice_bad.png",
                                   "gui_shot_merge_min.png")),
          "the CP-40 screenshots were not written: %s" % shots)
    # ---- CP-41：合并自动安装 / 单包错误卡片 / 引导滚动 / 语言嗅探 --------------
    md = line_of("ui mergedry   :")
    check("rows=['opt-strict', 'opt-mergedry']" in md and "label='仅产出不安装'" in md
          and "off=True" in md and "form False->True" in md,
          "the merge mode is missing the 仅产出不安装 switch (default must be OFF): %s" % md)
    md = line_of("ui merge deploy:")
    check("ok=True" in md and "deployed=True" in md and "M7=True" in md,
          "the merge did not auto-install (or the install stage M7 never ran): %s" % md)
    check("txt=True" in line_of("               : backup="),
          "no BACKUP.txt was written for the install: %s"
          % line_of("               : backup="))
    ns = line_of("ui notice single:")
    check("visible=True" in ns and "lines=2" in ns and "modal=''" in ns
          and "running=False" in ns and "Paks" in ns and "素材" in ns,
          "the single-mode pre-flight card is wrong (it must list both paths and not "
          "start a task): %s" % ns)
    gs = line_of("ui guide scroll:")
    try:
        # 注意别用 `before`/`after` 这种名字：本函数开头就有一个同名的文件集合
        # （"自检有没有在 Kit 里留下垃圾"），赋值会把它覆盖掉（CP-41 踩过）
        g_before = int(gs.split("before=")[1].split(" ")[0])
        g_during = int(gs.split("during=")[1].split("(")[0])
        g_after = int(gs.split("after=")[1].split(" ")[0])
        check(g_before > 0 and g_during < g_before and g_after == g_before
              and "inView=True" in gs,
              "the guide did not scroll the target into view / did not restore the "
              "scroll position: %s" % gs)
    except (IndexError, ValueError):
        check(False, "could not read the guide scroll metrics: %s" % gs)
    lg = line_of("ui lang sniff :")
    try:
        lg_lang = lg.split("lang=")[1].split(" ")[0]
        lg_expect = lg.split("expect=")[1].split(" ")[0]
        check(lg_lang == lg_expect and "stored=None" in lg and "persisted=en" in lg
              and "after_reload=en" in lg,
              "language sniffing / persistence is broken: %s" % lg)
    except (IndexError, ValueError):
        check(False, "could not read the language state: %s" % lg)
    more = log.split("              : notice_single=")[1] if "notice_single=" in log else ""
    check(all(n in log for n in ("gui_shot_notice_single.png", "gui_shot_merge_progress.png",
                                 "gui_shot_merge_ok.png", "gui_shot_guide_scroll.png",
                                 "gui_shot_lang_sniff.png")),
          "a CP-41 screenshot is missing (notice_single / merge_progress / merge_ok / "
          "guide_scroll / lang_sniff): %s ... %s" % (more[:90], line_of("              : lang_sniff=")))
    # ---- CP-41b：右下角「回滚」按钮（单包 DryRun 置灰 / 真装可点 / 点了真回滚）----
    rd = line_of("ui rollback dry:")
    check("exists=True" in rd and "disabled=True" in rd
          and "打开输出目录" in rd,
          "the single-mode 回滚 button is missing (REGRESSION) or not greyed out after a "
          "DryRun: %s" % rd)
    rr = line_of("ui rollback run:")
    check("deployed=True" in rr and "btn=True" in rr and "disabled=False" in rr
          and "click={'clicked': True}" in rr,
          "the single-mode 回滚 button cannot be clicked after a real deploy: %s" % rr)
    check("rc=0" in rr or "uninstall.ps1" in rr,
          "clicking 回滚 did not run uninstall.ps1: %s" % rr)
    sand = line_of("               : sandbox ")
    try:
        parts = sand.split("sandbox ")[1].split(" -> ")
        check(len(parts) == 3 and parts[0] != parts[1] and parts[2] == parts[0],
              "the single-mode rollback did not restore the game folder: %s" % sand)
    except (IndexError, ValueError):
        check(False, "could not read the single-mode rollback snapshot: %s" % sand)
    mr = line_of("ui merge rollback:")
    check("btn=True" in mr and "disabled=False" in mr and "click={'clicked': True}" in mr,
          "the merge-mode 回滚 button cannot be clicked after the auto-install: %s" % mr)
    check("已回滚" in mr or "rc=0" in mr,
          "the merge-mode rollback did not report success: %s" % mr)
    # ---- round 6: the community dialog (Octicon, one 2x2 grid, no scrollbar) --
    hi = line_of("hub icon      :")
    check("M10.226 17.284c-2.965-.36-5.054" in hi,
          "the GitHub entry does not use the Octicon mark-github path: %s" % hi)
    hg = line_of("hub grid      :")
    try:
        ws = hg.split("w=[")[1].split("]")[0].split(", ")
        check("display=grid" in hg and "buckets=2" in hg and len(set(ws)) == 1
              and int(ws[0]) > 100,
              "the four community buttons are not one 2x2 grid of equal buttons: %s" % hg)
    except (IndexError, ValueError):
        check(False, "could not read the community button grid: %s" % hg)
    hs = line_of("hub scroll    :")
    try:
        hov = hs.split("hovered=")[1]
        check(int(hov.split("'sw': ")[1].split(",")[0])
              <= int(hov.split("'cw': ")[1].split(",")[0]) + 1
              and int(hov.split("'sh': ")[1].split(",")[0])
              <= int(hov.split("'ch': ")[1].split(",")[0]) + 1,
              "hovering GitHub pulled a scrollbar out of the dialog: %s" % hs)
    except (IndexError, ValueError):
        check(False, "could not read the dialog's scroll metrics: %s" % hs)
    # ---- the decode ripple fired by the language switch ---------------------
    sc = line_of("ui scramble   :")
    check("series=" in sc and "max running=0" not in sc and "noisy=0" not in sc,
          "the language switch did not run a text decode ripple: %s" % sc)
    check("hover running=0" in sc,
          "hovering the text restarted the scramble (it must only fire on a switch): %s" % sc)
    # ---- the Squish Switch ---------------------------------------------------
    sq = line_of("ui squish     :")
    try:
        maxsx = float(sq.split("maxSx=")[1].split(" ")[0])
        minsy = float(sq.split("minSy=")[1].split(" ")[0])
        check(abs(maxsx - 1) > 0.02 and minsy < 0.999,
              "the language switch knob never squished (%s): %s" % (maxsx, sq))
    except (IndexError, ValueError):
        check(False, "could not read the squish samples: %s" % sq)
    # ---- the Glide Select ----------------------------------------------------
    gl = line_of("ui glide pill :")
    try:
        pill1 = float(gl.split("open=")[1].split(" ")[0])
        pill2 = float(gl.split("hover=")[1].split(" ")[0])
        check(abs(pill2 - pill1) >= 20,
              "the highlight pill did not glide between rows (%s -> %s)" % (pill1, pill2))
    except (IndexError, ValueError):
        check(False, "could not read the glide pill positions: %s" % gl)
    check("value=contain" in gl and "state=open rows=2" in line_of("ui glide      :"),
          "the Glide Select did not work inside the exe: %s" % gl)
    # ---- the two new community entries --------------------------------------
    hub = line_of("hub entries   :")
    check("join-github" in hub and "join-qq" in hub and "anim=gh-fly" in hub,
          "the hub is missing the GitHub / QQ entries or their animation: %s" % hub)
    stl = line_of("star popup    :")
    check("open=True" in stl and "art=star.png" in stl and "imgOk=True" in stl,
          "the star dialog does not show star.png: %s" % stl)
    try:
        itop = int(stl.split("imgTop=")[1].split(" ")[0])
        ttop = int(stl.split("textTop=")[1].split(" ")[0])
        check(0 < itop < ttop, "the star dialog is not a vertical stack: %s" % stl)
    except (IndexError, ValueError):
        check(False, "could not read the star dialog layout: %s" % stl)
    qql = line_of("qq popup      :")
    check("open=True" in qql and "art=joinQQ.png" in qql and "no=1054243070" in qql,
          "the QQ dialog does not show joinQQ.png / the group number: %s" % qql)
    check("猫窝" in line_of("qq copy       :"),
          "the QQ copy is not the requested line: %s" % line_of("qq copy       :"))
    cl = line_of("clipboard     :")
    check("after='1054243070'" in cl and "'ok': True" in cl,
          "the QQ group number never reached the clipboard: %s" % cl)
    check("open_url gh   : {'ok': True" in log,
          "the open_url allow-list rejects the GitHub repository: %s"
          % line_of("open_url gh   :"))
    # ---- ReactBits Line Sidebar --------------------------------------------
    ls = line_of("line sidebar  :")
    le = line_of("line effects  :")
    check("opt-force" in ls and "opt-adv" in ls,
          "the options are not a Line Sidebar list: %s" % ls)
    check("opt-force(eff=" in le and "opt-fit(eff=1" in le,
          "the Line Sidebar proximity effect did not run: %s" % le)
    # ---- the "Join us" dialog ---------------------------------------------
    jm = line_of("join modal    :")
    check("open=True" in jm and "art=joinus.png" in jm and "imgOk=True" in jm,
          "the Join-us dialog does not show joinus.png: %s" % jm)
    check("join buttons  : discord=https://discord.com/invite/BGeYfMBwaw" in log
          and "bili='#'" in log,
          "the community buttons point somewhere unexpected: %s" % line_of("join buttons  :"))
    check("join bili note: ''" not in log and line_of("join bili note:"),
          "the Bilibili placeholder says nothing (dead button): %s" % line_of("join bili note:"))
    check("join closed   : open=False" in log,
          "closeJoin() did not dismiss the dialog: %s" % line_of("join closed   :"))
    check("'reason': 'blocked'" in line_of("open_url api  :")
          and "'ok': True" in line_of("open_url api  :"),
          "the open_url allow-list did not behave: %s" % line_of("open_url api  :"))
    # ---- the draggable log / 判据 divider -----------------------------------
    sd = line_of("split drag    :")
    check("handle=" in sd and "err=-" in sd,
          "the divider drag was exercised: %s" % sd)
    check("handle=" in line_of("layout wide    :")
          and "split=" in line_of("layout wide    :"),
          "the layout probe reports the two panes: %s" % line_of("layout wide    :"))
    try:
        a0 = int(sd.split("a0=")[1].split("p")[0])
        a1 = int(sd.split("a_after_drag=")[1].split("p")[0])
        check(a1 - a0 >= 80, "dragging the divider widened pane A (%d -> %d px)" % (a0, a1))
    except (IndexError, ValueError):
        check(False, "could not read the divider drag result: %s" % sd)
    # ------------------------------------------------------------------------
    prog = line_of("ui progress   :")
    check("pct=100" in prog and "fill=" in prog and "src=chongci.gif" in prog,
          "the progress bar reached the end with the chongci.gif head: %s" % prog)
    try:
        fill = int(prog.split("fill=")[1].split("p")[0])
        track = int(prog.split("track=")[1].split("p")[0])
        check(fill >= track - 8, "the progress fill spans the track (%s/%s)" % (fill, track))
        headw = int(prog.split("head=")[1].split("p")[0])
        check(headw >= 68, "the chongci.gif head is 2x the original size (%d px)" % headw)
        check("rail 12px" in prog, "the rail is not back to 12 px: %s" % prog)
        barh = int(prog.split("barH=")[1].split("p")[0])
        check(56 <= barh <= 66 and headw >= 68,
              "the progress frame was not narrowed to ~62 px, or the GIF head changed "
              "size with it (CP-40): %s" % prog)
        railcy = int(prog.split("railCY=")[1].split(" ")[0])
        headcy = int(prog.split("headCY=")[1].split(" ")[0])
        barcy = int(prog.split("barCY=")[1].split(" ")[0])
        check(abs(headcy - railcy) <= 2 and abs(headcy - barcy) <= 3,
              "the chongci.gif head is not vertically centred (head=%d rail=%d bar=%d)"
              % (headcy, railcy, barcy))
    except (IndexError, ValueError):
        check(False, "could not read the progress bar geometry: %s" % prog)
    check("ui modal ok   : open=True kind=ok" in log and "转换成功喵" in log,
          "the success modal appeared with 转换成功喵 inside the exe")
    check("ui modal ok   : " in log and "art=success.png" in line_of("ui modal ok   :")
          and "imgOk=True" in line_of("ui modal ok   :"),
          "the success modal shows success.png: %s" % line_of("ui modal ok   :"))
    mfail = line_of("ui modal fail :")
    check("open=True kind=fail" in mfail and "洗大锅" in mfail
          and "art=cry.png" in mfail and "export=True" in mfail,
          "the failure modal shows cry.png + 洗大锅...出错了喵... + the export button: %s" % mfail)
    check("ui modal close: open=False" in log,
          "closeModal() really dismisses the modal: %s" % line_of("ui modal close:"))
    check("ui export log : ok=True" in log and "empty_case=暂无日志可导出" in log,
          "the error log exports and the empty case answers 暂无日志可导出: %s"
          % line_of("ui export log :"))
    # CP-42: 用户按钮真正走的那条分支（弹原生保存框）以前是零覆盖的 —— 它的过滤器写法不合法
    # 会直接 500。现在 dry=1 必须返回 ok=True 且过滤器是 pywebview 认的那一对。
    check("dry=True dry_files=2" in log,
          "the export-log dry path (the branch the user's button takes) is broken: %s"
          % line_of("ui export log :"))
    # this one is ONLY meaningful in a console-less build like the shipped exe
    nw = line_of("ui no console :")
    check("installed=True" in nw and "patched_hwnd=0" in nw and "last_flags_no_window=True" in nw,
          "every child was spawned with CREATE_NO_WINDOW and got no console window: %s" % nw)
    check("parent_has_console=False" in nw and "control_hwnd=" in nw
          and "control_hwnd=0" not in nw and "control_hwnd=-1" not in nw
          and "control_hwnd=None" not in nw,
          "the black-box check is not vacuous (the positive control really did get "
          "a console window): %s" % nw)
    check("window icon   :" in log and "T_UI.ico" in log,
          "the window icon is the .ico built from T_UI.png")
    after = {os.path.join(dp, f) for dp, _d, fs in os.walk(kit) for f in fs}
    added = sorted(os.path.basename(p) for p in after - before)
    check(not added, "the self-test left files behind in the shipped kit: %s" % added)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=None)
    ap.add_argument("--only", default=None, choices=("1", "2", "3"))
    ap.add_argument("--keep-log", action="store_true",
                    help="copy the frozen exe's --log-file to logs/g4_selftest_full.txt")
    a = ap.parse_args()
    exe = find_exe(a.exe)
    if not os.path.isdir(FAKEGAME) or not os.path.isdir(SRCM):
        print("FATAL: test fixtures missing; run tests/regression.py once first")
        return 2
    if a.only in (None, "1"):
        double_click(exe)
    if a.only in (None, "3"):
        no_console_headless(exe)
    if a.only in (None, "2"):
        selftest(exe, keep_log=a.keep_log)
    print("-" * 74)
    if FAILS:
        print("G4 RESULT: FAILED (%d)" % len(FAILS))
        for f in FAILS:
            print("   - %s" % f)
        return 1
    print("G4 RESULT: OK -- the shipped GUI exe opens a window and drives the whole stack")
    return 0


if __name__ == "__main__":
    sys.exit(main())
