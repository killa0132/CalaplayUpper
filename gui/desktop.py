# -*- coding: utf-8 -*-
"""PyWebView desktop shell: uvicorn on a daemon thread + the native window.

    python gui/desktop.py                       normal window
    python gui/desktop.py --headless            HTTP API only (scripts/CI)
    python gui/desktop.py --selftest            open the window, prove the page
                                                mounted AND reached the API, exit
    python gui/desktop.py --selftest-ui         also drive a REAL build from the
                                                page (fills the form, clicks Run,
                                                waits for the gates)

The UI self-test talks to the same tiny hook the page exposes on purpose:
`window.__cala.setParams({...}) / run() / cancel() / state()`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from gui import app as gui_app  # noqa: E402
from gui import no_window  # noqa: E402
from gui import prefs  # noqa: E402

TITLE = "CalaPlayerSrcmBuilder"

#: fixed backend port in --dev so gui/frontend/vite.config.js can proxy /api to it
DEV_PORT = 8756


def _ensure_working_dir() -> str:
    """Give the process a sane working directory.

    A double-clicked exe inherits CWD = its own folder, and the builder has a
    fallback that writes `build.log` there when it cannot even work out an
    `out_patch` (e.g. the user picked a folder that is not a srcm folder at all).
    Shipping kits must not grow files just because a build was rejected, so we
    sit in per-user app data instead.  Nothing in the pipeline depends on the
    CWD: kit discovery and ffmpeg probing are exe/_MEIPASS based.
    """
    base = os.path.join(os.environ.get("LOCALAPPDATA")
                        or os.path.expanduser("~"), "CalaPlayerSrcmBuilder")
    try:
        os.makedirs(base, exist_ok=True)
        os.chdir(base)
        return base
    except OSError:
        return os.getcwd()


def _window_icon() -> str:
    """The .ico for the title bar (and, once packed, the exe icon too).

    pywebview's winforms backend does honour `webview.start(icon=...)` -- but
    only for a real .ico (`System.Drawing.Icon`), so the PNG in gui/dist is
    converted to one at build time (`T_UI.ico`, multi-size).
    """
    cand = os.path.join(gui_app.dist_dir(), "T_UI.ico")
    return cand if os.path.isfile(cand) else ""

#: every message also goes to --log-file; a --windowed (no console) build has no
#: usable stdout, so this file is the only way to verify the frozen exe.
_LOG_FH = None
_LOG_PATH = ""


def say(msg: str = "") -> None:
    # a redirected/console stdout on this box is GBK, so printing an exotic
    # character must never be what kills the app -- the log file below is the
    # authoritative copy anyway
    try:
        print(msg)
    except Exception:  # noqa: BLE001
        pass
    if _LOG_FH:
        try:
            _LOG_FH.write(str(msg) + "\n")
            _LOG_FH.flush()
        except Exception:  # noqa: BLE001
            pass

#: does the Vue app exist, did it talk to the backend, which theme is on?
PROBE_JS = ("(function(){try{"
            "var b=document.getElementById('backend');"
            "return JSON.stringify({hook:!!window.__cala,"
            "backend:b?b.textContent.trim():'',"
            "theme:document.documentElement.dataset.theme,"
            "origin:Math.round(performance.timeOrigin)});"
            "}catch(e){return JSON.stringify({err:String(e)});}})()")

#: read the two cross-fading background layers (::before = light, ::after = dark)
BG_JS = ("(function(){"
         "var a=getComputedStyle(document.body,'::before');"
         "var b=getComputedStyle(document.body,'::after');"
         "return JSON.stringify({theme:document.documentElement.dataset.theme,"
         "light:a.opacity,lightImg:/bg_light[.]jpg/.test(a.backgroundImage),"
         "dark:b.opacity,darkImg:/bg_dark[.]jpg/.test(b.backgroundImage)});"
         "})()")

#: is the layout still usable after a resize?
LAYOUT_JS = ("(function(){try{"
             "var g=document.querySelector('.grid'),l=document.querySelector('.grid > .col.left'),"
             "lg=document.querySelector('.uv-log');"
             "if(!g||!l||!lg)return JSON.stringify({err:'missing elements'});"
             "var sp=document.querySelectorAll('.uv-split > .uv-pane'),"
             "hd=document.querySelector('.uv-handle'),"
             "sv=document.querySelector('.uv-split'),"
             "rt=document.querySelector('.grid > .col.right'),"
             "ch=document.querySelector('.grid > .col.right > .chips'),"
             "tk=document.getElementById('taskid'),"
             "ga=document.getElementById('card-gates'),"
             "r=function(e){return e?e.getBoundingClientRect():null;},"
             "pane=function(i){return sp[i]?Math.round(sp[i].getBoundingClientRect().width):0;};"
             "var spr=r(sv),rtr=r(rt),chr=r(ch),tkr=r(tk),gar=r(ga),lgr=r(lg);"
             "return JSON.stringify({w:window.innerWidth,h:window.innerHeight,"
             "cols:getComputedStyle(g).gridTemplateColumns.split(' ').length,"
             "left:Math.round(l.getBoundingClientRect().width),"
             "log:Math.round(lg.getBoundingClientRect().height),"
             "panes:sp.length,paneA:pane(0),paneB:pane(1),"
             "handle:hd?Math.round(hd.getBoundingClientRect().width):0,"
             "splitW:spr?Math.round(spr.width):0,"
             "splitRight:spr?Math.round(spr.right):0,"
             "rightW:rtr?Math.round(rtr.width):0,"
             "rightRight:rtr?Math.round(rtr.right):0,"
             "paneAL:spr&&sp[0]?Math.round(r(sp[0]).left):0,"
             "paneBL:spr&&sp[1]?Math.round(r(sp[1]).left):0,"
             "chipsW:chr?Math.round(chr.width):0,"
             "chipsRight:chr?Math.round(chr.right):0,"
             "taskRight:tkr?Math.round(tkr.right):0,"
             "logW:lgr?Math.round(lgr.width):0,logLeft:lgr?Math.round(lgr.left):0,"
             "gatesW:gar?Math.round(gar.width):0,gatesLeft:gar?Math.round(gar.left):0,"
             "splitDisp:sv?getComputedStyle(sv).display:'',"
             "cursor:hd?getComputedStyle(hd).cursor:''});"
             "}catch(e){return JSON.stringify({err:String(e)});}})()")

#: drag the divider with real pointer events (the whole point of the feature).
#: Only the events + the model value are read here: Vue re-renders on the next
#: tick, so the pane geometry has to be measured by a second probe.
SPLIT_DRAG_JS = ("(function(){try{"
                 "var h=document.querySelector('.uv-handle'),sp=document.querySelector('.uv-split'),"
                 "panes=document.querySelectorAll('.uv-split > .uv-pane');"
                 "if(!h||!sp||panes.length<2)return JSON.stringify({err:'no divider'});"
                 "var r=sp.getBoundingClientRect();"
                 "var a0=panes[0].getBoundingClientRect().width;"
                 "var x=Math.round(r.left+a0+7);"
                 "h.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,button:0,clientX:x}));"
                 "window.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,clientX:x+150}));"
                 "window.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,clientX:x+150}));"
                 "var out={ratio:window.__cala.getSplit(),width:Math.round(r.width),"
                 "a0:Math.round(a0),handle:Math.round(h.getBoundingClientRect().width)};"
                 "setTimeout(function(){var p=document.querySelectorAll('.uv-split > .uv-pane');"
                 "window.__calaSplitAfterDrag=p.length>1?Math.round(p[0].getBoundingClientRect().width):0;},"
                 "350);"
                 "return JSON.stringify(out);"
                 "}catch(e){return JSON.stringify({err:String(e)});}})()")

#: pane A's width some time after the drag above (set by that probe's timeout)
SPLIT_AFTER_DRAG_JS = "window.__calaSplitAfterDrag||0"

#: the first-run guide (Onboarding.vue).  It reports not just "the component is
#: mounted" but WHERE the card actually is and whether it is really painted --
#: an element can be in the DOM, on the right step, and still be invisible.
ONBOARD_JS = ("(function(){try{"
              "var api=window.__cala&&window.__cala.onboard;"
              "if(!api)return JSON.stringify({exists:false});"
              "var st=api.state(),root=document.querySelector('.uv-ob');"
              "if(!root){st.exists=true;st.open=false;return JSON.stringify(st);}"
              "var art=root.querySelector('.uv-ob-art');"
              "st.exists=true;st.open=true;st.z=getComputedStyle(root).zIndex;"
              "st.artOk=art?!!(art.complete&&art.naturalWidth>0):false;"
              "st.dots=root.querySelectorAll('.uv-ob-dots i').length;"
              "st.activeDot=root.querySelectorAll('.uv-ob-dots i.on').length;"
              "var c=root.querySelector('.uv-ob-card');"
              "if(c){var cs=getComputedStyle(c),b=c.getBoundingClientRect();"
              "st.card={x:Math.round(b.left),y:Math.round(b.top),"
              "w:Math.round(b.width),h:Math.round(b.height),"
              "vis:cs.visibility,op:cs.opacity,disp:cs.display,"
              "inView:(b.left>=0&&b.top>=0&&b.right<=window.innerWidth+1"
              "&&b.bottom<=window.innerHeight+1)};}"
              "else st.card=null;"
              # the spotlight has to be INSIDE the window too: a hole drawn past
              # the edge is a spotlight nobody can see (the user's complaint about
              # off-screen targets in a non-maximised window)
              "if(st.hole){st.holeInView=(st.hole.x>=-1&&st.hole.y>=-1"
              "&&st.hole.x+st.hole.w<=window.innerWidth+1"
              "&&st.hole.y+st.hole.h<=window.innerHeight+1);}"
              "else st.holeInView=null;"
              "return JSON.stringify(st);"
              "}catch(e){return JSON.stringify({exists:false,err:String(e)});}})()")

#: the log panel must scroll on its own and follow the tail
LOG_JS = ("(function(){try{"
          "var el=document.querySelector('.uv-log');if(!el)return JSON.stringify({err:'no log'});"
          "var st=getComputedStyle(el);"
          "return JSON.stringify({overflowY:st.overflowY,overflow:st.overflow,"
          "scrollHeight:el.scrollHeight,clientHeight:el.clientHeight,scrollTop:Math.round(el.scrollTop),"
          "atBottom:(el.scrollHeight-el.scrollTop-el.clientHeight)<40,"
          "lines:el.children.length,w:Math.round(el.getBoundingClientRect().width)});"
          "}catch(e){return JSON.stringify({err:String(e)});}})()")

#: the bottom progress bar + its chongci.gif head
PROGRESS_JS = ("(function(){try{"
               "var b=document.getElementById('progress');if(!b)return JSON.stringify({exists:false});"
               "var f=b.querySelector('.uv-prog-fill'),h=b.querySelector('.uv-prog-head'),"
               "t=b.querySelector('.uv-prog-track');"
               "var pct=parseFloat(getComputedStyle(b).getPropertyValue('--p'))||0;"
               "var hr=h?h.getBoundingClientRect():null,tr=t?t.getBoundingClientRect():null;"
               "return JSON.stringify({exists:true,pct:pct,"
               "fill:Math.round(f?f.getBoundingClientRect().width:0),"
               "track:Math.round(tr?tr.width:0),"
               "bar:Math.round(b.getBoundingClientRect().width),"
               "head:h?Math.round(hr.left):null,"
               "headW:h?Math.round(hr.width):0,"
               "headH:h?Math.round(hr.height):0,"
               "trackH:tr?Math.round(tr.height):0,"
               "headCY:hr?Math.round(hr.top+hr.height/2):0,"
               "trackCY:tr?Math.round(tr.top+tr.height/2):0,"
               "barCY:Math.round(b.getBoundingClientRect().top+b.getBoundingClientRect().height/2),"
               "trackLeft:tr?Math.round(tr.left):null,"
               "headSrc:h?(h.getAttribute('src')||''):'',"
               "running:b.classList.contains('running'),done:b.classList.contains('done'),"
               "failed:b.classList.contains('failed'),"
               "label:b.querySelector('.uv-prog-cap span')?b.querySelector('.uv-prog-cap span').textContent.trim():''});"
               "}catch(e){return JSON.stringify({exists:false,err:String(e)});}})()")

#: i18n: read a fixed sample of visible strings + the html lang attribute
I18N_JS = ("(function(){try{"
           "var q=function(s){var e=document.querySelector(s);"
           "return e?e.textContent.replace(/\\s+/g,' ').trim().slice(0,64):null;};"
           "return JSON.stringify({"
           "lang:window.__cala.lang(),htmlLang:document.documentElement.getAttribute('lang'),"
           "run:q('#run'),cancel:q('#cancel'),join:q('#join'),guide:q('#help'),"
           "inputs:q('#card-inputs .uv-card-title'),opts:q('#card-options .uv-card-title'),"
           "gates:q('#card-gates .uv-card-title'),"
           "optDry:q('#opt-dryrun .lab i'),optForce:q('#opt-force .lab i'),optAdv:q('#opt-adv .lab i'),"
           "empty:q('.uv-log .empty')"
           "});}catch(e){return JSON.stringify({err:String(e)});}})()")

#: ReactBits Line Sidebar: kick the proximity effect from a synthetic pointer
LINESIDE_MOVE_JS = ("(function(){try{"
                    "var ul=document.querySelector('.uv-ls-list'),t=document.querySelector('#opt-force');"
                    "if(!ul||!t)return JSON.stringify({err:'no line sidebar'});"
                    "var r=t.getBoundingClientRect();"
                    "ul.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,"
                    "clientX:Math.round(r.left+30),clientY:Math.round(r.top+r.height/2)}));"
                    "var ids=[];"
                    "Array.prototype.forEach.call(document.querySelectorAll('.uv-ls-item'),"
                    "function(e){ids.push(e.id);});"
                    "return JSON.stringify({ids:ids,target:'opt-force',"
                    "cy:Math.round(r.top+r.height/2)});"
                    "}catch(e){return JSON.stringify({err:String(e)});}})()")

#: ... and read `--effect` / the shifted transform / the mixed colour back
LINESIDE_READ_JS = ("(function(){try{"
                    "var out={};"
                    "Array.prototype.forEach.call(document.querySelectorAll('.uv-ls-item'),"
                    "function(e){var row=e.querySelector('.uv-ls-row'),lab=e.querySelector('.uv-ls-label');"
                    "var tx=0,m=/matrix\\(([^)]+)\\)/.exec(getComputedStyle(row).transform);"
                    "if(m){var p=m[1].split(',');tx=parseFloat(p[4]);}"
                    "out[e.id]={eff:Math.round((parseFloat(getComputedStyle(e)"
                    ".getPropertyValue('--effect'))||0)*1000)/1000,"
                    "tx:Math.round(tx*10)/10,color:getComputedStyle(lab).color,"
                    "marker:!!e.querySelector('.uv-ls-marker'),"
                    "active:e.classList.contains('is-active')};});"
                    "return JSON.stringify(out);"
                    "}catch(e){return JSON.stringify({err:String(e)});}})()")

#: the "Join us" dialog
JOIN_JS = ("(function(){try{"
           "var m=document.querySelector(\".uv-modal-backdrop[data-kind='join']\");"
           "var tr=(window.__calaJoinTrace||[]).join(' ');"
           "if(!m)return JSON.stringify({open:false,trace:tr,state:window.__calaJoinState||null,"
           "app:window.__cala.joinState()});"
           "var img=m.querySelector('.join-art'),d=m.querySelector('#join-discord'),"
           "b=m.querySelector('#join-bili'),n=m.querySelector('.join-note'),"
           "t=m.querySelector('.uv-modal-text'),body=m.querySelector('.join-body');"
           "return JSON.stringify({open:true,trace:tr,app:window.__cala.joinState(),"
           "title:t?t.textContent.trim():'',"
           "bodyHead:body?body.textContent.replace(/\\s+/g,' ').trim().slice(0,44):'',"
           "bodyLen:body?body.textContent.trim().length:0,"
           "src:img?(img.getAttribute('src')||''):'',"
           "imgOk:img?!!(img.complete&&img.naturalWidth>0):false,"
           "imgW:img?Math.round(img.getBoundingClientRect().width):0,"
           "discord:d?(d.getAttribute('href')||''):'',bili:b?(b.getAttribute('href')||''):'',"
           "note:n?n.textContent.trim():'',"
           "anim:getComputedStyle(m.querySelector('.uv-modal')).animationName});"
           "}catch(e){return JSON.stringify({open:false,err:String(e)});}})()")

#: the success / failure modal
MODAL_JS = ("(function(){try{"
            "var errs=(window.__calaErrors||[]).slice(-4).join(' ~ ');"
            "var tr=(window.__calaModalTrace||[]).join(' ');"
            "var m=document.querySelector(\".uv-modal-backdrop:not([data-kind='join'])\");"
            "if(!m)return JSON.stringify({open:false,trace:tr,errors:errs,"
            "state:window.__calaModalState||null});"
            "var img=m.querySelector('.uv-modal-art'),t=m.querySelector('.uv-modal-text'),"
            "e=m.querySelector('#export-log');"
            "return JSON.stringify({open:true,kind:m.getAttribute('data-kind'),"
            "text:t?t.textContent.trim():'',"
            "src:img?(img.getAttribute('src')||''):'',"
            "imgOk:img?!!(img.complete&&img.naturalWidth>0):false,"
            "hasExport:!!e,anim:getComputedStyle(m.querySelector('.uv-modal')).animationName,"
            "trace:tr,errors:errs,state:window.__calaModalState||null});"
            "}catch(e){return JSON.stringify({open:false,err:String(e)});}})()")



def _find_dialog_window(pid: int):
    """Return the hwnd of a visible top-level #32770 dialog owned by `pid`.

    The Vista-style folder picker is a #32770 dialog; locating it directly is a
    far stronger signal than "the call took a while", and it lets us close it
    deterministically (sending Esc only works if the dialog happens to be the
    foreground window).
    """
    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lparam):
        if not u.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(hwnd, cls, 64)
        if cls.value != "#32770":
            return True
        owner = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            found.append(hwnd)
            return False
        return True

    u.EnumWindows(cb, 0)
    return found[0] if found else None


def _close_window(hwnd) -> None:
    import ctypes
    ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)      # WM_CLOSE


def _watch_and_close_dialog(pid: int, result: dict, wait: float = 10.0,
                            before_close: float = 1.2) -> None:
    """Wait for the native dialog to appear, then close it."""
    import time as _t
    t0 = _t.time()
    hwnd = None
    while _t.time() - t0 < wait:
        hwnd = _find_dialog_window(pid)
        if hwnd:
            break
        _t.sleep(0.15)
    result["window_appeared"] = bool(hwnd)
    result["appeared_after"] = round(_t.time() - t0, 2)
    if hwnd:
        _t.sleep(before_close)
        _close_window(hwnd)
        _t.sleep(0.4)
        if _find_dialog_window(pid):                # still there -> try again
            _close_window(hwnd)


def _select_folder_async(port: int, result: dict, timeout: float = 30.0) -> None:
    """Call /api/select_folder in a worker (the endpoint blocks on the dialog)."""
    url = "http://127.0.0.1:%d/api/select_folder?kind=srcm&t=%s" % (port, gui_app.TOKEN)
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
        result.update({"ok": True, "path": body.get("path"),
                       "debug": body.get("debug"), "secs": round(time.time() - t0, 2)})
    except urllib.error.HTTPError as e:
        result.update({"ok": False, "status": e.code, "secs": round(time.time() - t0, 2),
                       "err": "HTTP %d" % e.code})
    except Exception as e:  # noqa: BLE001
        result.update({"ok": False, "secs": round(time.time() - t0, 2), "err": str(e)})


def _select_folder_over_http(port: int, timeout: float = 25.0) -> dict:
    """Call /api/select_folder.  The endpoint blocks until the dialog is answered,
    so another thread has to dismiss it."""
    url = "http://127.0.0.1:%d/api/select_folder?kind=srcm&t=%s" % (port, gui_app.TOKEN)
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
        return {"ok": True, "path": body.get("path"), "debug": body.get("debug"), "secs": round(time.time() - t0, 2)}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "secs": round(time.time() - t0, 2),
                "err": "HTTP %d" % e.code}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "secs": round(time.time() - t0, 2), "err": str(e)}


def _window_rect(title: str = TITLE):
    """(hwnd, screen rect) of our own top-level window (for the screenshots)."""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:  # noqa: BLE001
        return None, None
    u = ctypes.windll.user32
    pid = os.getpid()
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _l):
        p = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value != pid or not u.IsWindowVisible(h):
            return True
        n = u.GetWindowTextLengthW(h)
        b = ctypes.create_unicode_buffer(n + 2)
        u.GetWindowTextW(h, b, n + 2)
        if b.value == title:
            found.append(h)
        return True

    u.EnumWindows(cb, 0)
    if not found:
        return None, None
    r = wintypes.RECT()
    u.GetWindowRect(found[0], ctypes.byref(r))
    return found[0], (r.left, r.top, r.right, r.bottom)


def _raise_topmost(hwnd) -> bool:
    """Put our window above everything *for the duration of the screenshot*.

    Our own self-test window opens on the user's desktop, so a chat app that
    pops up in the middle of a run ends up in the picture.  A plain
    SetForegroundWindow is not enough (Windows' foreground lock refuses it from
    a background process), and a topmost-then-notopmost dance loses to another
    app that is *itself* topmost.  So: set topmost and leave it set while
    ImageGrab copies the composited screen, then clear it again.
    """
    if not hwnd:
        return False
    import ctypes
    u = ctypes.windll.user32
    SW_RESTORE, HWND_TOPMOST, SWP_NOMOVE_NOSIZE = 9, -1, 0x0003
    try:
        u.ShowWindow(hwnd, SW_RESTORE)
        u.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE_NOSIZE)
        u.SetForegroundWindow(hwnd)
        u.BringWindowToTop(hwnd)
        time.sleep(0.45)
        return True
    except Exception:  # noqa: BLE001
        return False


def _unraise(hwnd) -> None:
    if not hwnd:
        return
    import ctypes
    try:
        ctypes.windll.user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0003)  # NOTOPMOST
    except Exception:  # noqa: BLE001
        pass


def _print_window(hwnd, box):
    """Capture the window's own pixels, independent of what covers it.

    ImageGrab copies the composited screen, so raising our window is the only
    way to keep other apps out of the picture -- and that loses to an app which
    keeps re-raising itself (a chat popup, in practice).  `PrintWindow` with
    `PW_RENDERFULLCONTENT` asks the window to render itself into a DC instead,
    which no other window can interfere with.  Returns a PIL image or None.
    """
    try:
        import ctypes
        from ctypes import wintypes
        from PIL import Image
    except Exception:  # noqa: BLE001
        return None
    left, top, right, bottom = box
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        return None

    u = ctypes.windll.user32
    g = ctypes.windll.gdi32

    class BMIH(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    hdc = mdc = bmp = old = None
    try:
        hdc = u.GetWindowDC(hwnd)
        if not hdc:
            return None
        mdc = g.CreateCompatibleDC(hdc)
        bmp = g.CreateCompatibleBitmap(hdc, w, h)
        if not (mdc and bmp):
            return None
        old = g.SelectObject(mdc, bmp)
        if not u.PrintWindow(hwnd, mdc, 2):        # 2 = PW_RENDERFULLCONTENT
            return None
        bi = BMIH()
        bi.biSize = ctypes.sizeof(BMIH)
        bi.biWidth = w
        bi.biHeight = -h                            # negative = top-down rows
        bi.biPlanes = 1
        bi.biBitCount = 32
        bi.biCompression = 0                        # BI_RGB
        buf = ctypes.create_string_buffer(w * h * 4)
        if not g.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0):
            return None
        return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            if mdc and old:
                g.SelectObject(mdc, old)
            if bmp:
                g.DeleteObject(bmp)
            if mdc:
                g.DeleteDC(mdc)
            if hdc:
                u.ReleaseDC(hwnd, hdc)
        except Exception:  # noqa: BLE001
            pass


def _is_blank(img) -> bool:
    """A window that refused to render comes back as one flat colour."""
    try:
        lo, hi = img.convert("L").getextrema()
        return (hi - lo) < 8
    except Exception:  # noqa: BLE001
        return True


def _grab(tag: str) -> str:
    """Screenshot our window -- visual evidence for the self-test."""
    try:
        from PIL import ImageGrab
    except Exception as e:  # noqa: BLE001
        return "no PIL: %s" % e
    hwnd, box = _window_rect()
    if not box:
        return "window not found"
    path = os.path.join(_shot_dir(), "gui_shot_%s.png" % tag)
    # keep the occlusion-proof route: ask the window to render itself, and only
    # fall back to a screen copy when it refuses (then raise it and hope)
    how = "printwindow"
    img = _print_window(hwnd, box)
    if img is None or _is_blank(img):
        how = "screengrab"
        raised = _raise_topmost(hwnd)
        try:
            img = ImageGrab.grab(bbox=box, all_screens=True)
        except Exception as e:  # noqa: BLE001
            return "grab failed: %s: %s" % (type(e).__name__, e)
        finally:
            if raised:
                _unraise(hwnd)
    try:
        img.save(path)
    except Exception as e:  # noqa: BLE001
        return "save failed: %s: %s" % (type(e).__name__, e)
    return "%s [%s]" % (path, how)


def _shot_dir() -> str:
    d = os.path.dirname(os.path.abspath(_LOG_PATH)) if _LOG_PATH else os.getcwd()
    return d if os.path.isdir(d) else os.getcwd()


def _export_log_empty_case(port: int) -> dict:
    """"nothing to export" must be a friendly answer, never a crash."""
    url = "http://127.0.0.1:%d/api/export_log/no_such_task?t=%s" % (port, gui_app.TOKEN)
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": None, "err": "%s: %s" % (type(e).__name__, e)}


def _export_log_over_http(port: int, task_id: str) -> dict:
    """Verify the failure modal's 导出错误日志 button end to end.

    The page's button calls the same endpoint without `path`, which opens the
    native SAVE dialog (same pywebview machinery as the folder picker checked in
    step 2b).  Here we pass `path`, so the file itself is what gets verified:
    it exists, it is UTF-8, and it carries the failure reason.
    """
    if not task_id:
        return {"ok": False, "err": "no task id"}
    out = os.path.join(tempfile.gettempdir(), "cala_selftest_export.log")
    if os.path.isfile(out):
        os.remove(out)
    url = ("http://127.0.0.1:%d/api/export_log/%s?path=%s&t=%s"
           % (port, urllib.parse.quote(task_id), urllib.parse.quote(out), gui_app.TOKEN))
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, e)}
    body["path"] = out
    if os.path.isfile(out):
        body["size"] = os.path.getsize(out)
        with open(out, encoding="utf-8", errors="replace") as fh:
            txt = fh.read()
        body["lines"] = txt.count("\n")
        body["head"] = txt[:200].replace("\n", " | ")
        body["mentions_task"] = task_id in txt
    body["empty_case"] = _export_log_empty_case(port)
    return body


def _open_url_dry(port: int, url: str) -> dict:
    """Validate /api/open_url without launching a browser (dry=1)."""
    q = ("http://127.0.0.1:%d/api/open_url?dry=1&url=%s&t=%s"
         % (port, urllib.parse.quote(url, safe=""), gui_app.TOKEN))
    try:
        with urllib.request.urlopen(q, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": None, "err": "%s: %s" % (type(e).__name__, e)}


#: The decode ripple is sampled **inside the page**.  A cross-process
#: `evaluate_js` round trip costs more than the wave itself lasts, so reading it
#: from Python can only ever see the settled end state -- the trigger and the
#: sampling have to happen in one JS turn.
SCRAMBLE_RUN_JS = ("(function(){try{"
                   "window.__calaScr={samples:[]};"
                   "var snap=function(){var all=document.querySelectorAll('.uv-scramble');"
                   "var running=0;"
                   "for(var i=0;i<all.length;i++){if(!all[i].hasAttribute('data-settled'))running++;}"
                   "var e=document.querySelector('#run .uv-scramble');"
                   "window.__calaScr.samples.push({t:Math.round(performance.now()),"
                   "run:e?e.textContent:'',running:running});};"
                   "snap();"
                   "window.__cala.setLang('en',{x:Math.round(window.innerWidth/2),y:44});"
                   "for(var i=1;i<=14;i++){(function(k){setTimeout(snap,k*60);})(i);}"
                   "return JSON.stringify({ok:true});"
                   "}catch(e){return JSON.stringify({err:String(e)});}})()")

SCRAMBLE_SERIES_JS = ("(function(){try{var s=window.__calaScr||{samples:[]};"
                      "return JSON.stringify({n:(s.samples||[]).length,samples:s.samples});"
                      "}catch(e){return JSON.stringify({err:String(e)});}})()")

#: ... and the same trick for "hovering must NOT restart it"
SCRAMBLE_HOVER_JS = ("(function(){try{"
                     "window.__calaHov={samples:[]};"
                     "var snap=function(){var all=document.querySelectorAll('.uv-scramble');"
                     "var running=0;"
                     "for(var i=0;i<all.length;i++){if(!all[i].hasAttribute('data-settled'))running++;}"
                     "var e=document.querySelector('#run .uv-scramble');"
                     "window.__calaHov.samples.push({run:e?e.textContent:'',running:running});};"
                     "var el=document.querySelector('#run'),r=el.getBoundingClientRect();"
                     "for(var i=0;i<5;i++){el.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,"
                     "clientX:Math.round(r.left+15+i*14),clientY:Math.round(r.top+r.height/2)}));}"
                     "snap();"
                     "for(var i=1;i<=6;i++){(function(k){setTimeout(snap,k*55);})(i);}"
                     "return JSON.stringify({ok:true});"
                     "}catch(e){return JSON.stringify({err:String(e)});}})()")

SCRAMBLE_HOVER_READ_JS = ("(function(){try{var s=window.__calaHov||{samples:[]};"
                          "return JSON.stringify({n:(s.samples||[]).length,samples:s.samples});"
                          "}catch(e){return JSON.stringify({err:String(e)});}})()")

#: the language switch: a Squish Switch.  A real press is dispatched (the
#: component toggles on pointerup, not on a synthetic .click()), then the knob's
#: transform is sampled every 45 ms -- that is what proves the "squish": the
#: scale along the travel axis must rise above 1 while the other axis dips.
SQUISH_MOVE_JS = ("(function(){try{"
                  "var b=document.querySelector('#lang-switch');"
                  "if(!b)return JSON.stringify({err:'no language switch'});"
                  "var r=b.getBoundingClientRect();"
                  "window.__calaSquish={samples:[],wasOn:b.hasAttribute('data-on')};"
                  "var sample=function(){var t=b.querySelector('.uv-ss-thumb');"
                  "var m=/matrix\\(([^)]+)\\)/.exec(getComputedStyle(t).transform);"
                  "var p=m?m[1].split(',').map(Number):[1,0,0,1,0,0];"
                  "window.__calaSquish.samples.push({tx:Math.round(p[4]*10)/10,"
                  "sx:Math.round(p[0]*10000)/10000,sy:Math.round(p[3]*10000)/10000,"
                  "on:b.hasAttribute('data-on')});};"
                  "sample();"
                  "var opt={bubbles:true,button:0,pointerId:7,clientX:Math.round(r.left+10),"
                  "clientY:Math.round(r.top+r.height/2),pointerType:'mouse'};"
                  "b.dispatchEvent(new PointerEvent('pointerdown',opt));"
                  "b.dispatchEvent(new PointerEvent('pointerup',opt));"
                  "for(var i=1;i<=16;i++){(function(k){setTimeout(sample,k*45);})(i);}"
                  "return JSON.stringify({ok:true,w:Math.round(r.width),h:Math.round(r.height),"
                  "wasOn:window.__calaSquish.wasOn});"
                  "}catch(e){return JSON.stringify({err:String(e)});}})()")

SQUISH_READ_JS = ("(function(){try{var s=window.__calaSquish||{samples:[]};"
                  "var out=s.samples||[];"
                  "var maxSx=1,minSy=1,last=out.length?out[out.length-1]:null;"
                  "for(var i=0;i<out.length;i++){"
                  "if(Math.abs(out[i].sx-1)>Math.abs(maxSx-1))maxSx=out[i].sx;"
                  "if(out[i].sy<minSy)minSy=out[i].sy;}"
                  "return JSON.stringify({n:out.length,wasOn:s.wasOn,maxSx:maxSx,minSy:minSy,"
                  "last:last,lang:window.__cala.lang(),errors:(window.__calaErrors||[]).slice(-3).join(' ~ ')});"
                  "}catch(e){return JSON.stringify({err:String(e)});}})()")

#: the decode ripple: read every ScrambleText node (shown text + settled flag)
SCRAMBLE_JS = ("(function(){try{"
               "var pick=function(sel){var e=document.querySelector(sel+' .uv-scramble');"
               "if(!e)return null;"
               "return {text:e.textContent,settled:e.hasAttribute('data-settled'),len:e.textContent.length};};"
               "var all=document.querySelectorAll('.uv-scramble'),settled=0,running=0;"
               "for(var i=0;i<all.length;i++){"
               "if(all[i].hasAttribute('data-settled'))settled++;else running++;}"
               "return JSON.stringify({run:pick('#run'),cancel:pick('#cancel'),"
               "inputs:pick('#card-inputs .uv-card-title'),gates:pick('#card-gates .uv-card-title'),"
               "help:pick('#help'),total:all.length,settled:settled,running:running,"
               "lang:window.__cala.lang(),errors:(window.__calaErrors||[]).slice(-3).join(' ~ ')});"
               "}catch(e){return JSON.stringify({err:String(e)});}})()")

#: Glide Select: open -> read (pill position) -> hover the other row -> read again
GLIDE_OPEN_JS = ("(function(){try{"
                 "var t=document.querySelector('.uv-gs-trigger');"
                 "if(!t)return JSON.stringify({err:'no glide select'});"
                 "var r=t.getBoundingClientRect();"
                 "t.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,button:0,"
                 "pointerId:11,clientX:Math.round(r.left+12),clientY:Math.round(r.top+r.height/2),"
                 "pointerType:'mouse'}));"
                 "return JSON.stringify({ok:true});"
                 "}catch(e){return JSON.stringify({err:String(e)});}})()")

GLIDE_READ_JS = ("(function(){try{"
                 "var m=document.querySelector('.uv-gs-menu'),p=document.querySelector('.uv-gs-pill'),"
                 "t=document.querySelector('.uv-gs-trigger'),"
                 "opts=document.querySelectorAll('.uv-gs-opt');"
                 "var ty=null;"
                 "if(p){var mm=/matrix\\(([^)]+)\\)/.exec(getComputedStyle(p).transform);"
                 "ty=mm?Math.round(Number(mm[1].split(',')[5])*100)/100:0;}"
                 "var sel=-1;for(var i=0;i<opts.length;i++){if(opts[i].getAttribute('aria-selected')==='true')sel=i;}"
                 # the popup is teleported to <body>; the click-through bug was
                 # "clicking 背景适配>contain actually hit the DryRun row", so
                 # ask the document what is really painted at that point
                 "var hit=null,hx=null,hy=null;"
                 "if(opts.length){var last=opts[opts.length-1],lr=last.getBoundingClientRect();"
                 "hx=Math.round(lr.left+lr.width/2);hy=Math.round(lr.top+lr.height/2);"
                 "var he=document.elementFromPoint(hx,hy);"
                 "var own=he&&he.closest?he.closest('.uv-gs-opt'):null;"
                 "hit=own?Number(own.dataset.index):(he?-1:-2);}"
                 "return JSON.stringify({menu:m?true:false,state:m?m.dataset.state:'absent',"
                 "rows:opts.length,pillY:ty,pillOpacity:p?Number(getComputedStyle(p).opacity):0,"
                 "selected:sel,hit:hit,hitX:hx,hitY:hy,"
                 "menuZ:m?getComputedStyle(m).zIndex:'',"
                 "menuPos:m?getComputedStyle(m).position:'',"
                 "menuParent:m&&m.parentElement?(m.parentElement.tagName||''):'',"
                 "trace:(window.__calaGsTrace||[]).slice(-12).join(' '),"
                 "labels:Array.prototype.map.call(opts,function(o){"
                 "return o.querySelector('.uv-gs-name').textContent.trim();}),"
                 "trigger:t?t.querySelector('.uv-gs-label').textContent.trim():'',"
                 "fit:window.__cala.getParams().fit,"
                 "errors:(window.__calaErrors||[]).slice(-3).join(' ~ ')});"
                 "}catch(e){return JSON.stringify({err:String(e)});}})()")

GLIDE_HOVER_JS = ("(function(){try{"
                  "var m=document.querySelector('.uv-gs-menu');"
                  "if(!m)return JSON.stringify({err:'menu is not open'});"
                  "var opts=m.querySelectorAll('.uv-gs-opt');"
                  "var last=opts[opts.length-1];if(!last)return JSON.stringify({err:'no rows'});"
                  "var r=last.getBoundingClientRect();"
                  "last.dispatchEvent(new PointerEvent('pointerover',{bubbles:true,pointerId:12,"
                  "clientX:Math.round(r.left+20),clientY:Math.round(r.top+r.height/2),pointerType:'mouse'}));"
                  "return JSON.stringify({ok:true,row:opts.length-1});"
                  "}catch(e){return JSON.stringify({err:String(e)});}})()")

GLIDE_PICK_JS = ("(function(){try{"
                 "var m=document.querySelector('.uv-gs-menu');"
                 "if(!m)return JSON.stringify({err:'menu is not open'});"
                 "var list=m.querySelector('.uv-gs-list'),opts=m.querySelectorAll('.uv-gs-opt');"
                 "var last=opts[opts.length-1];var r=last.getBoundingClientRect();"
                 "var y=Math.round(r.top+r.height/2),x=Math.round(r.left+20);"
                 "var o={bubbles:true,button:0,pointerId:13,clientX:x,clientY:y,pointerType:'mouse'};"
                 "list.dispatchEvent(new PointerEvent('pointerdown',o));"
                 "list.dispatchEvent(new PointerEvent('pointerup',o));"
                 "return JSON.stringify({ok:true,picked:opts.length-1});"
                 "}catch(e){return JSON.stringify({err:String(e)});}})()")

#: the "leave me a star" popup (vertical: art on top, copy below)
STAR_JS = ("(function(){try{"
           "var m=document.querySelector(\".uv-modal-backdrop[data-kind='star']\");"
           "if(!m)return JSON.stringify({open:false,app:window.__cala.joinState()});"
           "var img=m.querySelector('img'),t=m.querySelector('.uv-modal-text'),"
           "b=m.querySelector('.join-body'),go=m.querySelector('#star-go'),"
           "later=m.querySelector('#star-later');"
           "var ir=img?img.getBoundingClientRect():null,tr=t?t.getBoundingClientRect():null;"
           "return JSON.stringify({open:true,src:img?(img.getAttribute('src')||''):'',"
           "imgOk:img?!!(img.complete&&img.naturalWidth>0):false,"
           "imgW:ir?Math.round(ir.width):0,imgH:ir?Math.round(ir.height):0,"
           "natW:img?img.naturalWidth:0,natH:img?img.naturalHeight:0,"
           "imgTop:ir?Math.round(ir.top):0,textTop:tr?Math.round(tr.top):0,"
           "title:t?t.textContent.trim():'',bodyLen:b?b.textContent.trim().length:0,"
           "bodyHead:b?b.textContent.replace(/\\s+/g,' ').trim().slice(0,40):'',"
           "href:go?(go.getAttribute('href')||''):'',hasLater:!!later,"
           "anim:getComputedStyle(m.querySelector('.uv-modal')).animationName,"
           "app:window.__cala.joinState()});"
           "}catch(e){return JSON.stringify({open:false,err:String(e)});}})()")

#: the QQ popup (art + group number + copy button)
QQ_JS = ("(function(){try{"
         "var m=document.querySelector(\".uv-modal-backdrop[data-kind='qq']\");"
         "if(!m)return JSON.stringify({open:false,app:window.__cala.joinState()});"
         "var img=m.querySelector('img'),no=m.querySelector('#qq-no'),"
         "t=m.querySelector('.uv-modal-text'),b=m.querySelector('.join-body'),"
         "n=m.querySelector('.uv-modal-note'),c=m.querySelector('#qq-copy');"
         "return JSON.stringify({open:true,src:img?(img.getAttribute('src')||''):'',"
         "imgOk:img?!!(img.complete&&img.naturalWidth>0):false,"
         "imgW:img?Math.round(img.getBoundingClientRect().width):0,"
         "imgH:img?Math.round(img.getBoundingClientRect().height):0,"
         "natW:img?img.naturalWidth:0,natH:img?img.naturalHeight:0,"
         "no:no?no.textContent.trim():'',"
         "title:t?t.textContent.trim():'',bodyLen:b?b.textContent.trim().length:0,"
         "bodyHead:b?b.textContent.replace(/\\s+/g,' ').trim().slice(0,44):'',"
         "note:n?n.textContent.trim():'',hasCopy:!!c,"
         "anim:getComputedStyle(m.querySelector('.uv-modal')).animationName,"
         "app:window.__cala.joinState()});"
         "}catch(e){return JSON.stringify({open:false,err:String(e)});}})()")

#: the hub now has four entries (Discord / Bilibili / GitHub / QQ).  Round 6
#: added the geometry of the button block (one 2x2 grid, four equal buttons),
#: the dialog's own scroll metrics (a horizontal bar used to appear on hover)
#: and the GitHub icon's path (it has to be the Octicon, not a star).
HUB_JS = ("(function(){try{"
          "var m=document.querySelector(\".uv-modal-backdrop[data-kind='join']\");"
          "if(!m)return JSON.stringify({open:false});"
          "var ids=[];"
          "Array.prototype.forEach.call(m.querySelectorAll('.uv-btn'),function(b){if(b.id)ids.push(b.id);});"
          "var gh=m.querySelector('#join-github');"
          "var card=m.querySelector('.uv-modal');"
          "var acts=m.querySelector('.join-acts');"
          "var bs=acts?Array.prototype.map.call(acts.querySelectorAll('.uv-btn'),function(b){"
          "var r=b.getBoundingClientRect();return {id:b.id,w:Math.round(r.width),"
          "x:Math.round(r.left),y:Math.round(r.top)};}):[];"
          "var rows={};bs.forEach(function(b){rows[b.y]=1;});"
          "var ic=gh?gh.querySelector('.ic'):null;"
          "var pa=ic?ic.querySelector('path'):null;"
          "var d=pa?(pa.getAttribute('d')||''):'';"
          "return JSON.stringify({open:true,ids:ids,"
          "ghHref:gh?(gh.getAttribute('href')||''):'',"
          "flies:gh?gh.querySelectorAll('.gh-fly i').length:0,"
          "flyAnim:gh&&gh.querySelector('.gh-fly i')"
          "?getComputedStyle(gh.querySelector('.gh-fly i')).animationName:'',"
          "iconD:d.slice(0,42),iconFill:pa?getComputedStyle(pa).fill:'',"
          "iconBox:ic?Math.round(ic.getBoundingClientRect().width):0,"
          "actsDisplay:acts?getComputedStyle(acts).display:'',"
          "actCols:acts?getComputedStyle(acts).gridTemplateColumns:'',"
          "btnRows:Object.keys(rows).length,btnW:bs.map(function(b){return b.w;}),"
          "btnIds:bs.map(function(b){return b.id;}),"
          "scroll:card?{sw:card.scrollWidth,cw:card.clientWidth,"
          "sh:card.scrollHeight,ch:card.clientHeight,ox:getComputedStyle(card).overflowX}:null,"
          "app:window.__cala.joinState()});"
          "}catch(e){return JSON.stringify({open:false,err:String(e)});}})()")

#: hover the GitHub entry, then read the hub again: the flying stars are
#: absolutely positioned and must NOT grow the dialog's scrollable overflow
GH_HOVER_JS = ("(function(){try{"
               "var b=document.querySelector('#join-github');"
               "if(!b)return JSON.stringify({err:'no github entry'});"
               "b.dispatchEvent(new PointerEvent('pointerover',{bubbles:true,pointerId:21,"
               "pointerType:'mouse'}));"
               "return JSON.stringify({ok:true});"
               "}catch(e){return JSON.stringify({err:String(e)});}})()")

#: the browse button must keep its label on one line inside its own box
BROWSE_JS = ("(function(){try{"
             "var b=document.querySelector('#card-inputs .uv-browse');"
             "if(!b)return JSON.stringify({err:'no browse button'});"
             "var r=b.getBoundingClientRect(),ic=b.querySelector('svg'),"
             "sp=b.querySelector('.uv-scramble')||b.querySelector('span');"
             "var sr=sp?sp.getBoundingClientRect():null;"
             "return JSON.stringify({w:Math.round(r.width),h:Math.round(r.height),"
             "label:sp?sp.textContent.trim():'',"
             "labelW:sr?Math.round(sr.width):0,labelH:sr?Math.round(sr.height):0,"
             "hasIcon:!!ic,iconW:ic?Math.round(ic.getBoundingClientRect().width):0,"
             "clipped:b.scrollWidth>b.clientWidth+1,"
             "flex:getComputedStyle(b).flexGrow+'/'+getComputedStyle(b).flexShrink,"
             "ws:getComputedStyle(b).whiteSpace});"
             "}catch(e){return JSON.stringify({err:String(e)});}})()")

#: every option row must stay on ONE line: "背景适配" used to wrap into two rows
#: once the fit chip got wide (and reserving the scrollbar gutter cost 11px)
OPTLAB_JS = ("(function(){try{"
             "var out={};"
             "Array.prototype.forEach.call(document.querySelectorAll('.uv-ls-item'),function(li){"
             "var b=li.querySelector('.uv-ls-label b');"
             "if(!b)return;var r=b.getBoundingClientRect();"
             "var side=li.querySelector('.uv-ls-side');"
             "out[li.id]={h:Math.round(r.height),w:Math.round(r.width),"
             # a nowrap label that does not fit is silently ellipsized -- that is
             # just as bad as wrapping, so it is measured too
             "trunc:b.scrollWidth>b.clientWidth+1,"
             "text:b.textContent.trim(),"
             "sideW:side?Math.round(side.getBoundingClientRect().width):0};});"
             "var chip=document.querySelector('#opt-fit .uv-gs-trigger');"
             "return JSON.stringify({rows:out,"
             "chipW:chip?Math.round(chip.getBoundingClientRect().width):0,"
             "chipText:chip?chip.querySelector('.uv-gs-label').textContent.trim():''});"
             "}catch(e){return JSON.stringify({err:String(e)});}})()")

#: the left column must not change its inner width when its content grows past
LEFTW_JS = ("(function(){try{"
            "var l=document.querySelector('.grid > .col.left'),c=document.querySelector('#card-inputs');"
            "if(!l||!c)return JSON.stringify({err:'no left column'});"
            "var w0=Math.round(c.getBoundingClientRect().width),"
            "o0=l.scrollHeight>l.clientHeight;"
            "var d=document.createElement('div');d.style.height='1400px';l.appendChild(d);"
            "void l.offsetHeight;"
            "var w1=Math.round(c.getBoundingClientRect().width),"
            "o1=l.scrollHeight>l.clientHeight;"
            "var g=getComputedStyle(l).scrollbarGutter;"
            "d.remove();void l.offsetHeight;"
            "var w2=Math.round(c.getBoundingClientRect().width);"
            "return JSON.stringify({w0:w0,w1:w1,w2:w2,over0:o0,over1:o1,gutter:g,"
            "colW:Math.round(l.getBoundingClientRect().width),"
            "colClientW:l.clientWidth,colOffsetW:l.offsetWidth});"
            "}catch(e){return JSON.stringify({err:String(e)});}})()")


def _clipboard_get() -> str:
    """Read the Windows clipboard text (test helper, so the copy test can also
    put back whatever the user had there before)."""
    import ctypes
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    u32.OpenClipboard.argtypes = [ctypes.c_void_p]
    u32.GetClipboardData.restype = ctypes.c_void_p
    u32.GetClipboardData.argtypes = [ctypes.c_uint]
    if not u32.OpenClipboard(None):
        return ""
    try:
        h = u32.GetClipboardData(13)          # CF_UNICODETEXT
        if not h:
            return ""
        p = k32.GlobalLock(h)
        if not p:
            return ""
        try:
            return ctypes.wstring_at(p)
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


def _copy_over_http(port: int, text: str, dry: int = 0) -> dict:
    q = ("http://127.0.0.1:%d/api/copy?dry=%d&text=%s&t=%s"
         % (port, dry, urllib.parse.quote(text, safe=""), gui_app.TOKEN))
    try:
        with urllib.request.urlopen(q, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": None, "err": "%s: %s" % (type(e).__name__, e)}


def _prefs_http(port: int, body=None) -> dict:
    """Read (body=None) or merge (body=dict) the durable settings store."""
    url = "http://127.0.0.1:%d/api/prefs?t=%s" % (port, gui_app.TOKEN)
    try:
        if body is None:
            req = urllib.request.Request(url)
        else:
            req = urllib.request.Request(
                url, data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8")) or {}
    except Exception as e:  # noqa: BLE001
        return {"ok": None, "err": "%s: %s" % (type(e).__name__, e)}


def _wait_health(port: int, timeout: float = 20.0) -> dict:
    url = "http://127.0.0.1:%d/api/health?t=%s" % (port, gui_app.TOKEN)
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.15)
    raise RuntimeError("the HTTP API never came up on port %d (%s)" % (port, last))


def _token_guard_check(port: int) -> bool:
    """A request without the token must be refused (403)."""
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/api/health" % port, timeout=2)
        return False
    except urllib.error.HTTPError as e:
        return e.code == 403
    except Exception:  # noqa: BLE001
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="calagui")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--headless", action="store_true", help="HTTP API only, no window")
    ap.add_argument("--selftest", action="store_true",
                    help="open the window, verify the page mounted and reached the API")
    ap.add_argument("--selftest-ui", action="store_true",
                    help="also drive a real build through the page")
    ap.add_argument("--selftest-shell", action="store_true",
                    help="also exercise window resize and the native folder dialog")
    ap.add_argument("--selftest-seconds", type=float, default=40.0)
    ap.add_argument("--dev", action="store_true",
                    help="developer mode: load the page from the Vite dev server "
                         "(npm run dev) and enable the WebView2 DevTools")
    ap.add_argument("--dev-url", default="http://127.0.0.1:5173",
                    help="the Vite dev server URL used by --dev")
    ap.add_argument("--log-file", default=None,
                    help="also write every message here (needed for the no-console exe)")
    ap.add_argument("--paks", default=os.path.join(_ROOT, "tests", "fakegame"))
    ap.add_argument("--srcm", default=os.path.join(_ROOT, "tests", "mat", "demo"))
    a = ap.parse_args(argv)
    # no console (double-click on the windowed exe) => sys.stdout is None; fix it
    # before anything can call .isatty() on it (uvicorn, pywebview, print)
    gui_app.ensure_std_streams()
    # ... and make sure our own children never pop a console window either
    no_window.install()
    # pywebview computes `base_uri()` (a *default argument*, i.e. at import time)
    # from `sys.argv[0]` -- and _ensure_working_dir() chdir's away from wherever
    # we were launched, so a relative `gui\desktop.py` turned into a path that
    # does not exist.  Pin it to an absolute path first.
    sys.argv[0] = os.path.abspath(sys.argv[0])
    # scratch space: never let a rejected build drop files next to the exe
    say("working dir   : %s" % _ensure_working_dir())
    global _LOG_FH, _LOG_PATH
    if a.log_file:
        _LOG_PATH = os.path.abspath(a.log_file)
        _LOG_FH = open(a.log_file, "w", encoding="utf-8")

    port = a.port or (DEV_PORT if a.dev else gui_app.pick_port())
    server, _th = gui_app.start_server_thread(port)
    health = _wait_health(port)
    # check the token guard while the server is definitely alive (after the
    # window closes we set should_exit, so doing it later is a race)
    guard_ok = _token_guard_check(port)
    if a.dev:
        # the page comes from vite (5173) and reaches this backend through the
        # dev-server proxy, so the token still has to ride along in the URL
        url = "%s/?t=%s" % (a.dev_url.rstrip("/"), gui_app.TOKEN)
    else:
        url = "http://127.0.0.1:%d/?t=%s" % (port, gui_app.TOKEN)
    say("HTTP API : http://127.0.0.1:%d  (token protected)" % port)
    say("health   : %s" % health)
    if a.dev:
        say("dev mode : page <- %s   (start it first: cd gui\\frontend && npm.cmd run dev)"
            % a.dev_url)
        say("dev api  : %s" % url)

    if a.headless:
        say("headless : http://127.0.0.1:%d/?t=%s" % (port, gui_app.TOKEN))
        if a.selftest:
            ok = guard_ok
            say("token guard: %s" % ("OK (unauthenticated request refused)" if ok else "FAIL"))
            server.should_exit = True
            return 0 if ok else 1
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.should_exit = True
        return 0

    import webview
    # ---- the "first run only" guide needs a real first run ------------------
    # CP-37c: run the whole prefs dance in a throw-away folder.  The old "save / clear / restore
    # the user's own settings" rule was LOSSY when the user had no other settings yet -- the
    # restore deleted the real store, so their next launch popped the guide again (reported
    # 2026-09-26).  With the redirect the self-test cannot touch the real file at all.
    _selftest_prefs = os.path.join(os.environ.get("TEMP") or os.path.expanduser("~"),
                                   "cala-selftest-prefs-%d" % os.getpid())
    os.environ["CALA_PREFS_DIR"] = _selftest_prefs
    try:
        os.makedirs(_selftest_prefs, exist_ok=True)
    except OSError:
        pass
    prefs_before = prefs.all_prefs()
    prefs.clear(["cala-onboarded"])
    say("prefs before  : %s" % (prefs_before or "{}"))
    say("prefs file    : %s" % prefs.path())
    R = {"loaded": threading.Event(), "probe": {}, "bg_dark": {}, "bg_light": {},
         "ui": {}, "ui_fail": {}, "error": "", "lay_wide": {}, "lay_min": {},
         "lay_back": {}, "dialog": {}, "log": {}, "prog": {}, "prog_seen": [],
         "modal_ok": {}, "modal_fail": {}, "modal_early": {}, "export": {},
         "nowin": {}, "lay_big": {}, "modal_closed": {}, "shot_ok": "",
         "shot_fail": "", "ob0": {}, "ob_walk": [], "ob_end": {}, "ob_shot": "",
         "shot_layout_min": "", "optlab_min": {},
         "split_drag": {}, "split_after": {}, "split_moved": None, "shot_layout": "",
         "i18n_zh": {}, "i18n_en": {}, "i18n_back": {}, "shot_en": "",
         "scr_zh": {}, "scr_mid": {}, "scr_mid2": {}, "scr_en": {}, "scr_hover": {}, "scr_back": {},
         "shot_scramble": "", "squish_move": {}, "squish": {}, "shot_squish": "",
         "glide_open": {}, "glide_1": {}, "glide_hover": {}, "glide_2": {},
         "glide_pick": {}, "glide_3": {}, "shot_glide": "",
         "theme0": {}, "bg_a": {}, "bg_b": {}, "bg_c": {},
         "hub": {}, "star": {}, "star_closed": {}, "qq": {}, "qq_closed": {},
         "shot_star": "", "shot_qq": "", "url_gh": {},
         "clip_before": "", "clip_after": "", "clip_dry": {}, "clip_dry_bad": {},
         "ls_move": {}, "ls_poke2": {}, "ls_tries": 0, "ls_read": {}, "shot_ls": "",
         "join": {}, "join_bili": {}, "join_closed": {}, "shot_join": "", "url_ok": {},
         "url_bad": {}, "optlab": {},
         # round 6: the durable prefs store, the guide's second run, the geometry
         # of the things that used to overlap or get squeezed
         "prefs_before": {}, "prefs_after": {}, "prefs_second": {}, "prefs_restored": {},
         "ob_second": {}, "reload_shot": "", "browse": {}, "reload_gen": {},
         "join_scroll": {}, "gh_hover": {}, "leftw": {}, "shot_join_hover": ""}
    window = webview.create_window(TITLE, url, width=1240, height=820,
                                   min_size=(960, 620), text_select=True)
    gui_app.WINDOW = window
    window.events.loaded += lambda *_a: R["loaded"].set()

    def js(code):
        try:
            v = window.evaluate_js(code)
            return json.loads(v) if isinstance(v, str) and v.startswith("{") else v
        except Exception as e:  # noqa: BLE001
            R["error"] = "evaluate_js failed: %s" % e
            return None

    def jsq(code):
        """Same, but a failure is expected: `location.reload()` tears the page
        down mid-call, and that must not be recorded as "the page broke"."""
        try:
            v = window.evaluate_js(code)
            return json.loads(v) if isinstance(v, str) and v.startswith("{") else v
        except Exception:  # noqa: BLE001
            return None

    def monitor():
        if not R["loaded"].wait(a.selftest_seconds):
            R["error"] = "the window never reported 'loaded'"
            if a.selftest:
                window.destroy()
            return

        # 1) did the Vue app mount and talk to the backend?
        t0 = time.time()
        while time.time() - t0 < a.selftest_seconds:
            p = js(PROBE_JS)
            if p and p.get("hook") and (p.get("backend") or "").startswith("v"):
                R["probe"] = p
                break
            time.sleep(0.25)
        if not R["probe"] and not R["error"]:
            R["error"] = "the page never exposed __cala / never read /api/health"

        # 1a) the first-run guide.  The durable flag was cleared before the window
        #     was even created, so this is a REAL first run: the guide must be up
        #     on its own, without anyone calling restart().  It is walked BEFORE
        #     anything else because it covers the whole page (z-index 45) and the
        #     dropdown / sidebar probes need an unobstructed document.  Every step
        #     is recorded with its spotlight geometry, so "the hole really is on
        #     the element it talks about" is a fact, not a guess.
        if R["probe"]:
            # 0) the theme the page came up with, BEFORE anything in this run can
            #    touch it -- printed so a "we did not start dark" surprise is
            #    evidence instead of a mystery (the layer assertion below is
            #    deliberately order-independent).
            R["theme0"] = js(BG_JS) or {}
            time.sleep(0.8)
            R["ob0"] = js(ONBOARD_JS) or {}
            if not R["ob0"].get("open"):
                # a second run (flag already set) still has to be walkable -- the
                # "Guide" button does exactly this
                say("ui guide  auto: NOT shown (flag already set) -> restarting by hand")
                js("window.__cala.onboard && window.__cala.onboard.restart(0)")
                time.sleep(0.8)
                R["ob0"] = js(ONBOARD_JS) or {}
            R["ob_shot"] = _grab("guide")
            walk = []
            for _i in range(int(R["ob0"].get("total") or 6)):
                st = js(ONBOARD_JS) or {}
                # A card caught mid-fade is not evidence of a broken dialog, so
                # wait for the animation to land and read again (up to 3 tries)
                # rather than weakening the "really visible" assertion.
                for _try in range(3):
                    card = st.get("card") or {}
                    try:
                        op = float(card.get("op") or 0)
                    except (TypeError, ValueError):
                        op = 0.0
                    if st.get("open") and 0.0 < op < 0.5:
                        time.sleep(0.3)
                        st = js(ONBOARD_JS) or {}
                    else:
                        break
                walk.append(st)
                js("window.__cala.onboard && window.__cala.onboard.next()")
                time.sleep(0.55)
            R["ob_walk"] = walk
            time.sleep(0.5)
            R["ob_end"] = js(ONBOARD_JS) or {}
            # ... and the flag really did land in the durable store (the whole
            # point of the round-6 fix: localStorage lived on a per-launch origin)
            R["prefs_after"] = _prefs_http(port)
            say("prefs after   : %s" % R["prefs_after"])

        # 1b) language + the decode ripple + the Squish Switch + the Glide Select.
        #     zh first so the rest of the run is deterministic, then prove the
        #     switch really rewrites the page, then switch back.
        if R["probe"]:
            # the guide just scrolled the left column around; put it back at the
            # top so the dropdown/sidebar probes (and their screenshots) see the
            # page the way a user does when they open it
            js("var l=document.querySelector('.grid > .col.left'); if(l) l.scrollTop=0;")
            time.sleep(0.4)
            js("window.__cala.setLang && window.__cala.setLang('zh')")
            time.sleep(1.4)
            R["i18n_zh"] = js(I18N_JS) or {}
            R["scr_zh"] = js(SCRAMBLE_JS) or {}
            # the switch + the in-page sample series of the decode ripple
            R["scr_run"] = js(SCRAMBLE_RUN_JS) or {}
            time.sleep(0.34)
            R["shot_scramble"] = _grab("scramble")
            time.sleep(1.25)
            R["scr_series"] = js(SCRAMBLE_SERIES_JS) or {}
            R["i18n_en"] = js(I18N_JS) or {}
            R["scr_en"] = js(SCRAMBLE_JS) or {}
            R["shot_en"] = _grab("en")
            # hovering the text must NOT restart the wave (the user was explicit)
            R["scr_hover_run"] = js(SCRAMBLE_HOVER_JS) or {}
            time.sleep(0.65)
            R["scr_hover"] = js(SCRAMBLE_HOVER_READ_JS) or {}
            js("window.__cala.setLang('zh')")
            time.sleep(1.4)
            R["i18n_back"] = js(I18N_JS) or {}
            R["scr_back"] = js(SCRAMBLE_JS) or {}

            # the Squish Switch: a real press (it toggles on pointerup), then the
            # knob's transform is sampled while it travels
            R["squish_move"] = js(SQUISH_MOVE_JS) or {}
            time.sleep(0.55)
            R["shot_squish"] = _grab("squish")
            time.sleep(0.55)
            R["squish"] = js(SQUISH_READ_JS) or {}
            js("window.__cala.setLang('zh')")
            time.sleep(1.4)

            # the Glide Select behind 背景适配: open -> hover the other row -> pick
            R["glide_open"] = js(GLIDE_OPEN_JS) or {}
            time.sleep(0.45)
            R["glide_1"] = js(GLIDE_READ_JS) or {}
            R["shot_glide"] = _grab("glide")
            R["glide_hover"] = js(GLIDE_HOVER_JS) or {}
            time.sleep(0.55)
            R["glide_2"] = js(GLIDE_READ_JS) or {}
            R["glide_pick"] = js(GLIDE_PICK_JS) or {}
            time.sleep(0.55)
            R["glide_3"] = js(GLIDE_READ_JS) or {}
            js("window.__cala.setParams({fit:'cover'})")

        # 2) the two background layers must be wired to bg_light / bg_dark.
        #    Read the state that is on, toggle, and assert the toggle really flipped
        #    BOTH the theme attribute and the visible layer -- hardcoding "we start
        #    dark" makes the check dependent on a remembered theme (and on whether
        #    an earlier step in this very run happened to press the chip).
        R["bg_a"] = js(BG_JS) or {}
        js("window.__cala && window.__cala.toggleTheme()")
        time.sleep(1.1)                      # let the 620 ms cross-fade settle
        R["bg_b"] = js(BG_JS) or {}
        js("window.__cala && window.__cala.toggleTheme()")
        time.sleep(1.1)
        R["bg_c"] = js(BG_JS) or {}

        # 2b) the shell: layout at the widest and at the minimum size, and the
        #     native folder dialog really opening (we dismiss it with Esc)
        if a.selftest_shell:
            R["lay_wide"] = js(LAYOUT_JS) or {}
            try:
                window.resize(960, 620)
                time.sleep(1.4)
                R["lay_min"] = js(LAYOUT_JS) or {}
                # the smallest window is where "the right side adapts badly" is
                # visible, so it gets its own piece of evidence -- and the option
                # rows must still fit their labels there
                R["shot_layout_min"] = _grab("layout_min")
                R["optlab_min"] = js(OPTLAB_JS) or {}
                window.resize(1460, 940)
                time.sleep(1.4)
                R["lay_big"] = js(LAYOUT_JS) or {}
                window.resize(1240, 820)
                time.sleep(1.4)
                R["lay_back"] = js(LAYOUT_JS) or {}
            except Exception as e:  # noqa: BLE001
                R["error"] = "window.resize failed: %s" % e
            # the log / 判据 divider has to actually move when dragged
            R["split_drag"] = js(SPLIT_DRAG_JS) or {}
            time.sleep(0.8)
            R["split_moved"] = js(SPLIT_AFTER_DRAG_JS)
            js("window.__cala.setSplit(50)")
            time.sleep(0.5)
            R["split_after"] = js(LAYOUT_JS) or {}

            # the ReactBits Line Sidebar: poke the pointer at one row and read the
            # per-row --effect / shift / colour back after the easing settles.
            # The poke is repeated right before the read on purpose: the physical
            # mouse can wander over the window at any time and a real pointermove
            # (or pointerleave) legitimately re-targets the effect -- sampling a
            # stale instant would be measuring the user's hand, not the widget.
            R["ls_move"] = js(LINESIDE_MOVE_JS) or {}
            time.sleep(0.4)
            # CP-35: the read is a bounded *settle loop*.  A single sample taken 0.28 s after the
            # poke once measured eff=0.618 (the easing had not finished / a real pointermove had
            # re-targeted the effect) and made the frozen-exe acceptance flaky even though the widget
            # was fine.  The assertion stays just as strong (the settled value must still be > 0.75);
            # the widget simply gets up to three chances and the BEST sample is reported, so a real
            # regression still shows up as a failing number.
            best, best_eff, tries = {}, -1.0, 0
            for _i in range(3):
                tries += 1
                if _i == 0:
                    R["ls_poke2"] = js(LINESIDE_MOVE_JS) or {}
                else:
                    R["ls_poke%d" % (_i + 2)] = js(LINESIDE_MOVE_JS) or {}
                time.sleep(0.45)
                got = js(LINESIDE_READ_JS) or {}
                eff = ((got or {}).get("opt-force") or {}).get("eff") or 0
                if eff > best_eff:
                    best, best_eff = got, eff
                if best_eff > 0.75:
                    break
            R["ls_tries"] = tries
            R["ls_read"] = best
            R["shot_ls"] = _grab("ls")

            # the "Join us" hub + the two new entries (GitHub star popup, QQ group)
            js("window.__cala.openJoin && window.__cala.openJoin()")
            time.sleep(0.75)
            R["join"] = js(JOIN_JS) or {}
            R["hub"] = js(HUB_JS) or {}
            R["shot_join"] = _grab("join")
            # hover the GitHub entry and read the dialog again: the "满天飞" stars
            # must not pull a scrollbar out of it (they used to)
            R["gh_hover"] = js(GH_HOVER_JS) or {}
            time.sleep(0.5)
            R["join_scroll"] = js(HUB_JS) or {}
            R["shot_join_hover"] = _grab("join_hover")
            js("var b=document.querySelector('#join-bili'); b&&b.click();")
            time.sleep(0.4)
            R["join_bili"] = js(JOIN_JS) or {}
            R["url_ok"] = _open_url_dry(port, "https://discord.com/invite/BGeYfMBwaw/login")
            R["url_gh"] = _open_url_dry(port, "https://github.com/killa0132/CalaplayUpper")
            R["url_bad"] = _open_url_dry(port, "https://example.com/not-allowed")
            # GitHub: opens the repository AND pops "leave me a star"
            js("var b=document.querySelector('#join-github'); b&&b.click();")
            time.sleep(0.95)
            R["star"] = js(STAR_JS) or {}
            R["shot_star"] = _grab("star")
            js("var b=document.querySelector('#star-later'); b&&b.click();")
            time.sleep(0.55)
            R["star_closed"] = js(STAR_JS) or {}
            # QQ: the click itself copies the group number, then the dialog shows it
            R["clip_before"] = _clipboard_get()
            js("var b=document.querySelector('#join-qq'); b&&b.click();")
            time.sleep(0.95)
            R["qq"] = js(QQ_JS) or {}
            R["shot_qq"] = _grab("qq")
            R["clip_after"] = _clipboard_get()
            R["clip_dry"] = _copy_over_http(port, "1054243070", dry=1)
            R["clip_dry_bad"] = _copy_over_http(port, "", dry=1)
            # ... and put the user's clipboard back the way we found it
            R["clip_restored"] = None
            if R["clip_before"]:
                _copy_over_http(port, R["clip_before"])
                time.sleep(0.25)
                R["clip_restored"] = _clipboard_get()
            js("var b=document.querySelector('#qq-close'); b&&b.click();")
            time.sleep(0.55)
            R["qq_closed"] = js(QQ_JS) or {}
            js("window.__cala.closeJoin && window.__cala.closeJoin()")
            time.sleep(0.55)
            R["join_closed"] = js(JOIN_JS) or {}

            dlg = {}
            th = threading.Thread(target=_select_folder_async, args=(port, dlg), daemon=True)
            th.start()
            w = {}
            _watch_and_close_dialog(os.getpid(), w)
            th.join(timeout=25)
            dlg.update({k: v for k, v in w.items()} if dlg else {})
            R["dialog"] = dlg

        # 2c) round-6 geometry: the browse button keeps its label on one line and
        #     the left column keeps its inner width when the content overflows
        if R["probe"]:
            R["browse"] = js(BROWSE_JS) or {}
            R["optlab"] = js(OPTLAB_JS) or {}
            R["leftw"] = js(LEFTW_JS) or {}

        # 3) optionally drive a real build from the page
        if a.selftest_ui:
            params = {"paks": a.paks, "srcm": a.srcm, "dryRun": True}
            js("window.__cala.setParams(%s); window.__cala.run();" % json.dumps(params))
            t0 = time.time()
            st = {}
            pseen = []
            while time.time() - t0 < 600:
                st = js("JSON.stringify(window.__cala.state())") or {}
                # watch the progress bar move while the build is running
                pr = js(PROGRESS_JS) or {}
                if pr.get("exists"):
                    pseen.append(pr.get("pct"))
                if st and st.get("running") is False and st.get("ok") is not None:
                    break
                time.sleep(0.5)
            R["ui"] = st
            R["prog_seen"] = pseen
            # after a successful run: the bar is full, the log scrolls, the
            # success modal is up (and it must NOT offer the log export)
            time.sleep(0.8)
            R["log"] = js(LOG_JS) or {}
            R["modal_early"] = js(MODAL_JS) or {}
            R["prog_first"] = js(PROGRESS_JS) or {}
            # sample the modal for a few seconds: it must appear with the right
            # content and stay until it is dismissed.  A real click on the dimmed
            # background legitimately dismisses it (this window pops up on the
            # user's desktop, so we must not depend on them not touching it), so
            # the content assertions use the FIRST sighting and we only report
            # whether it later went away.
            series = []
            ts0 = time.time()
            while time.time() - ts0 < 3.4:
                m = js(MODAL_JS) or {}
                age = time.time() - ts0
                if not m.get("open"):
                    series.append("%.1fs=GONE" % age)
                    if R.get("modal_ok") and not R.get("modal_gone_at"):
                        R["modal_gone_at"] = round(age, 2)
                else:
                    series.append("%.1fs=%s" % (age, m.get("kind")))
                    if not R.get("modal_ok"):
                        R["modal_ok"] = m
                time.sleep(0.3)
            R["modal_series"] = series
            R["shot_ok"] = _grab("ok")
            R["prog"] = js(PROGRESS_JS) or {}
            # ... and closing it must actually work (deterministic, no clicking)
            js("window.__cala.closeModal && window.__cala.closeModal()")
            time.sleep(0.6)
            R["modal_closed"] = js(MODAL_JS) or {}
            # a clean shot of the finished layout (split panes, gates table, the
            # enlarged progress bar) with no modal in the way
            R["shot_layout"] = _grab("layout")
            R["nowin"] = no_window.probe()
            time.sleep(0.4)

            # 3b) a deliberately failing run: empty material folder -> the run
            #     fails early, which is exactly when the failure modal + the
            #     "导出错误日志" button matter.
            bad = os.path.join(tempfile.gettempdir(), "cala_selftest_empty")
            try:
                os.makedirs(bad, exist_ok=True)
                for f in os.listdir(bad):
                    os.remove(os.path.join(bad, f))
            except OSError:
                pass
            js("window.__cala.setParams(%s); window.__cala.run();"
               % json.dumps({"paks": a.paks, "srcm": bad, "dryRun": True}))
            t0 = time.time()
            st2 = {}
            while time.time() - t0 < 300:
                st2 = js("JSON.stringify(window.__cala.state())") or {}
                if st2 and st2.get("running") is False and st2.get("ok") is not None:
                    break
                time.sleep(0.4)
            time.sleep(0.8)
            R["ui_fail"] = st2
            R["modal_fail"] = js(MODAL_JS) or {}
            R["shot_fail"] = _grab("fail")
            R["export"] = _export_log_over_http(port, st2.get("taskId") or "")

        if a.selftest:
            # 4) the SECOND run.  A reload is exactly what the next launch is:
            #    same URL, same durable store, brand new page.  The guide must
            #    stay down -- that is the whole point of the round-6 fix (the
            #    old localStorage flag lived on a per-launch origin and never
            #    survived, so the guide popped up every single time).
            if R["probe"]:
                gen0 = (R["probe"] or {}).get("origin")
                jsq("(function(){setTimeout(function(){location.reload();},60);"
                    "return JSON.stringify({ok:true});})()")
                st2 = {}
                t0 = time.time()
                while time.time() - t0 < 30:
                    time.sleep(0.5)
                    st2 = jsq("(function(){try{var c=window.__cala;"
                              "return JSON.stringify({has:!!c,"
                              "origin:c?c.state().origin:0,"
                              "guide:c?c.state().guide:null,"
                              "lang:c?c.lang():\"\"});}catch(e){"
                              "return JSON.stringify({has:false,err:String(e)});}})()") or {}
                    if st2.get("has") and st2.get("origin") and st2.get("origin") != gen0:
                        break
                R["reload_gen"] = st2
                time.sleep(1.2)                 # let the layout settle
                R["ob_second"] = jsq(ONBOARD_JS) or {}
                R["reload_shot"] = _grab("second")
                R["prefs_second"] = _prefs_http(port)
                say("ui guide 2nd  : gen=%s guide=%s auto=%s stored=%s shot=%s"
                    % (st2.get("origin"), st2.get("guide"),
                       R["ob_second"].get("auto"), R["ob_second"].get("stored"),
                       R["reload_shot"]))
            time.sleep(0.3)
            try:
                window.destroy()
            except Exception:  # noqa: BLE001
                pass

    if a.selftest:
        threading.Thread(target=monitor, daemon=True).start()

    try:
        _icon = _window_icon()
        if _icon:
            say("window icon   : %s" % _icon)
        webview.start(icon=_icon, debug=bool(a.dev))
    except Exception as e:  # noqa: BLE001
        say("FAIL: pywebview could not start: %s: %s" % (type(e).__name__, e))
        server.should_exit = True
        return 1
    finally:
        server.should_exit = True

    # put the user's own settings back exactly as they were (same rule as the
    # clipboard: the self-test must not leave the machine in a different state)
    prefs.clear(list(prefs.ALLOWED))
    if prefs_before:
        prefs.put(prefs_before)
    prefs_restored = prefs.all_prefs()
    R["prefs_restored"] = prefs_restored

    if not a.selftest:
        return 0

    ok = True
    p, ui = R["probe"], R["ui"]
    say("window loaded : %s" % ("yes" if R["loaded"].is_set() else "NO"))
    say("vue mounted   : %s" % ("yes" if p.get("hook") else "NO"))
    say("page->api     : %s" % (p.get("backend") or "<empty>"))
    say("token guard   : %s" % ("OK" if guard_ok else "FAIL"))
    for _tag, _st in (("at startup", R["theme0"]), ("at rest   ", R["bg_a"]),
                      ("toggled   ", R["bg_b"]), ("toggled 2x", R["bg_c"])):
        say("theme %s: theme=%-5s light-layer=%s(%s) dark-layer=%s(%s)"
            % (_tag, _st.get("theme"), _st.get("light"), _st.get("lightImg"),
               _st.get("dark"), _st.get("darkImg")))
    ob0, walk, obe = R["ob0"], R["ob_walk"], R["ob_end"]
    arts = [w.get("art") or "?" for w in walk]
    masked = [w for w in walk if w.get("mask")]
    say("ui guide      : shown=%s steps=%s arts=%s masked=%s stored=%s shot=%s"
          % (ob0.get("open"), len(walk), ">".join(arts), len(masked),
             obe.get("stored"), R.get("ob_shot")))
    say("ui guide walk : %s"
          % " ".join("#%s open=%s vis=%s leaving=%s target=%s op=%s"
                     % (w.get("step"), w.get("open"), w.get("visible"), w.get("leaving"),
                        w.get("target"), (w.get("card") or {}).get("op"))
                     for w in walk))
    _acts = [w.get("acts") for w in walk if w.get("acts")]
    say("ui guide hole : in-view=%s of %s spotlit steps (a hole must never be drawn off-screen)"
          % (len([w for w in walk if w.get("hole") and w.get("holeInView")]),
             len(masked)))
    say("ui guide acts : rows=%s nowrap=%s widest-overflow=%spx card=%spx btnH=%s"
          % (sorted(set(a.get("rows") for a in _acts)),
             sorted(set(a.get("nowrap") for a in _acts)),
             max([a.get("overflow") or 0 for a in _acts] or [0]),
             max([a.get("cardW") or 0 for a in _acts] or [0]),
             sorted(set(tuple(a.get("btnH") or []) for a in _acts))))
    _ob2, _rg = R.get("ob_second") or {}, R.get("reload_gen") or {}
    say("ui guide 2nd  : gen=%s (1st %s) guide=%s auto=%s stored=%s shot=%s"
          % (_rg.get("origin"), (p.get("origin")), _ob2.get("open"), _ob2.get("auto"),
             _ob2.get("stored"), R.get("reload_shot")))
    say("ui prefs      : before=%s after=%s 2nd=%s restored=%s file=%s"
          % (R.get("prefs_before"), (R.get("prefs_after") or {}).get("prefs"),
             (R.get("prefs_second") or {}).get("prefs"), R.get("prefs_restored"),
             prefs.path()))
    _bw = R.get("browse") or {}
    say("ui browse btn : w=%spx h=%spx label=%r labelW=%spx labelH=%spx icon=%s/%spx "
        "clipped=%s flex=%s ws=%s"
          % (_bw.get("w"), _bw.get("h"), _bw.get("label"), _bw.get("labelW"),
             _bw.get("labelH"), _bw.get("hasIcon"), _bw.get("iconW"),
             _bw.get("clipped"), _bw.get("flex"), _bw.get("ws")))
    _lw = R.get("leftw") or {}
    say("ui left width : w0=%spx w1=%spx(after overflow) w2=%spx over=%s>%s gutter=%s "
        "col=%spx client=%spx"
          % (_lw.get("w0"), _lw.get("w1"), _lw.get("w2"), _lw.get("over0"),
             _lw.get("over1"), _lw.get("gutter"), _lw.get("colW"), _lw.get("colClientW")))
    _g1h = R.get("glide_1") or {}
    say("ui glide hit  : value=%s hit-row=%s of %s (row center %s,%s) pos=%s z=%s parent=%s %s"
          % (_g1h.get("selected"), _g1h.get("hit"), (_g1h.get("rows") or 0) - 1,
             _g1h.get("hitX"), _g1h.get("hitY"), _g1h.get("menuPos"),
             _g1h.get("menuZ"), _g1h.get("menuParent"), _g1h.get("trace")))
    _ol = R.get("optlab") or {}
    say("ui opt labels : chip=%spx %r rows=%s trunc=%s/%s"
          % (_ol.get("chipW"), _ol.get("chipText"),
             {k: "%sx%s" % (v.get("w"), v.get("h")) for k, v in (_ol.get("rows") or {}).items()},
             len([v for v in (_ol.get("rows") or {}).values() if v.get("trunc")]),
             len(_ol.get("rows") or {})))
    zh, en, back = R["i18n_zh"], R["i18n_en"], R["i18n_back"]
    say("i18n zh       : lang=%s html=%s run=%r cancel=%r join=%r gates=%r"
          % (zh.get("lang"), zh.get("htmlLang"), zh.get("run"), zh.get("cancel"),
             zh.get("join"), zh.get("gates")))
    say("i18n en       : lang=%s html=%s run=%r cancel=%r join=%r gates=%r"
          % (en.get("lang"), en.get("htmlLang"), en.get("run"), en.get("cancel"),
             en.get("join"), en.get("gates")))
    say("i18n back     : lang=%s run=%r (must equal the zh one)"
          % (back.get("lang"), back.get("run")))
    _zhs, _ens = R["scr_zh"], R["scr_en"]
    #: the in-page series is what actually proves the ripple: at least one sample
    #: must have nodes mid-flight AND the run label showing neither language
    series = (R["scr_series"] or {}).get("samples") or []
    running_max = max([s.get("running") or 0 for s in series] or [0])
    noisy_s = [s for s in series
               if s.get("run") and s.get("run") not in ("开始打包", "Start packing")]
    hov = (R["scr_hover"] or {}).get("samples") or []
    say("ui scramble   : zh=%s/%s settled | series=%s samples, max running=%s, noisy=%s | hover running=%s"
          % (_zhs.get("settled"), _zhs.get("total"), len(series), running_max, len(noisy_s),
             max([s.get("running") or 0 for s in hov] or [0])))
    say("ui scramble t : %s"
          % " ".join("%sms:%s/%s" % (s.get("t"), (s.get("run") or "")[:6], s.get("running"))
                     for s in series[:6]))
    _sq = R["squish"]
    say("ui squish     : samples=%s maxSx=%s minSy=%s last=%s lang=%s"
          % (_sq.get("n"), _sq.get("maxSx"), _sq.get("minSy"), _sq.get("last"), _sq.get("lang")))
    _g1, _g2, _g3 = R["glide_1"], R["glide_2"], R["glide_3"]
    say("ui glide      : state=%s rows=%s labels=%s"
          % (_g1.get("state"), _g1.get("rows"), _g1.get("labels")))
    say("ui glide pill : open=%s hover=%s (selected=%s) after-pick=%s value=%s label=%r"
          % (_g1.get("pillY"), _g2.get("pillY"), _g2.get("selected"), _g3.get("pillY"),
             _g3.get("fit"), _g3.get("trigger")))
    if a.selftest_ui:
        say("ui driven     : running=%s ok=%s deployed=%s lines=%s"
              % (ui.get("running"), ui.get("ok"), ui.get("deployed"), ui.get("lines")))
        say("ui gates      : %s" % (ui.get("gates") or ui.get("error")))
        if ui.get("error"):
            say("ui error      : %s" % ui["error"])
        lg, pr = R["log"], R["prog"]
        say("ui log scroll : overflow-y=%s scrollH=%s clientH=%s scrollTop=%s atBottom=%s lines=%s"
              % (lg.get("overflowY"), lg.get("scrollHeight"), lg.get("clientHeight"),
                 lg.get("scrollTop"), lg.get("atBottom"), lg.get("lines")))
        seen = [p for p in R["prog_seen"] if p is not None]
        say("ui progress   : track=%spx(rail %spx) fill=%spx pct=%s running=%s done=%s "
            "head=%spx@%s railCY=%s headCY=%s barCY=%s src=%s moved=%s"
              % (pr.get("track"), pr.get("trackH"), pr.get("fill"), pr.get("pct"),
                 pr.get("running"), pr.get("done"), pr.get("headW"), pr.get("head"),
                 pr.get("trackCY"), pr.get("headCY"), pr.get("barCY"),
                 (pr.get("headSrc") or "").rsplit("/", 1)[-1],
                 ("%s→%s" % (min(seen), max(seen))) if seen else "-"))
        say("ui progress@t0: pct=%s fill=%s (during the width transition)"
              % (R["prog_first"].get("pct"), R["prog_first"].get("fill")))
        mok, mfail = R["modal_ok"], R["modal_fail"]
        say("ui modal ok   : open=%s kind=%s text=%r art=%s imgOk=%s export=%s anim=%s"
              % (mok.get("open"), mok.get("kind"), mok.get("text"),
                 (mok.get("src") or "").rsplit("/", 1)[-1], mok.get("imgOk"),
                 mok.get("hasExport"), mok.get("anim")))
        say("ui modal@t0  : open=%s kind=%s trace=%s (0.8s after the build ended)"
              % (R["modal_early"].get("open"), R["modal_early"].get("kind"),
                 R["modal_early"].get("trace")))
        say("ui modal ok tr: %s" % mok.get("trace"))
        say("ui modal ok st: %s errors=%s" % (mok.get("state"), mok.get("errors")))
        say("ui modal watch: %s%s" % (" ".join(R.get("modal_series") or []),
                                      ("  (dismissed at %ss)" % R.get("modal_gone_at"))
                                      if R.get("modal_gone_at") else ""))
        say("ui modal close: open=%s kind=%s (after closeModal())"
              % (R["modal_closed"].get("open"), R["modal_closed"].get("kind")))
        say("ui page gen   : origin=%s (started at %s; unchanged = the page never reloaded)"
              % (ui.get("origin"), p.get("origin")))
        say("ui modal fail : open=%s kind=%s text=%r art=%s imgOk=%s export=%s anim=%s"
              % (mfail.get("open"), mfail.get("kind"), mfail.get("text"),
                 (mfail.get("src") or "").rsplit("/", 1)[-1], mfail.get("imgOk"),
                 mfail.get("hasExport"), mfail.get("anim")))
        say("ui fail run   : ok=%s error=%s" % (R["ui_fail"].get("ok"),
                                                 (R["ui_fail"].get("error") or "")[:90]))
        ex = R["export"]
        say("ui export log : ok=%s bytes=%s lines=%s empty_case=%s %s"
              % (ex.get("ok"), ex.get("bytes"), ex.get("lines"),
                 ex.get("empty_case", {}).get("message"), ex.get("err") or ""))
        nw = R["nowin"]
        say("ui no console : installed=%s parent_has_console=%s calls=%s "
            "last_flags_no_window=%s patched_hwnd=%s control_hwnd=%s"
              % (nw.get("installed"), nw.get("parent_has_console"), no_window.CALLS,
                 nw.get("last_flags_no_window"), nw.get("patched_hwnd"),
                 nw.get("control_hwnd")))
        say("ui shots      : ok=%s" % R["shot_ok"])
        say("              : fail=%s" % R["shot_fail"])
        say("              : layout=%s" % R["shot_layout"])
        say("              : layout_min=%s" % R.get("shot_layout_min"))
    if a.selftest_shell:
        for label, key in (("wide", "lay_wide"), ("min ", "lay_min"),
                           ("big ", "lay_big"), ("back", "lay_back")):
            v = R[key]
            say("layout %s    : %sx%s cols=%s left=%spx log=%spx split=%s/%s handle=%spx"
                  % (label, v.get("w"), v.get("h"), v.get("cols"), v.get("left"),
                     v.get("log"), v.get("paneA"), v.get("paneB"), v.get("handle")))
            say("layout %s box: split=%spx@%s(right %s) right=%spx(right %s) paneAL=%s paneBL=%s "
                "log=%spx@%s gates=%spx@%s chips=%spx(right %s) taskid.right=%s disp=%s"
                  % (label, v.get("splitW"), v.get("splitW") and (v.get("splitRight", 0) - v.get("splitW", 0)),
                     v.get("splitRight"), v.get("rightW"),
                     v.get("rightW") and (v.get("rightRight", 0) - v.get("rightW", 0)),
                     v.get("paneAL"), v.get("paneBL"), v.get("logW"), v.get("logLeft"),
                     v.get("gatesW"), v.get("gatesLeft"), v.get("chipsW"),
                     v.get("chipsRight"), v.get("taskRight"), v.get("splitDisp")))
        sd = R["split_drag"]
        say("split drag    : ratio=%s width=%spx a0=%spx a_after_drag=%spx handle=%spx err=%s"
              % (sd.get("ratio"), sd.get("width"), sd.get("a0"), R.get("split_moved"),
                 sd.get("handle"), sd.get("err") or "-"))
        sa = R["split_after"]
        say("split reset   : panes=%s paneA=%spx paneB=%spx handle=%spx"
              % (sa.get("panes"), sa.get("paneA"), sa.get("paneB"), sa.get("handle")))
        lm, lr = R["ls_move"], R["ls_read"]
        say("line sidebar  : rows=%s target=%s cursorY=%s"
              % (lm.get("ids"), lm.get("target"), lm.get("cy")))
        say("line effects  : %s"
              % " ".join("%s(eff=%s tx=%spx %s)" % (k, (v or {}).get("eff"), (v or {}).get("tx"),
                                                    (v or {}).get("color"))
                         for k, v in lr.items() if isinstance(v, dict)))
        jn, jc = R["join"], R["join_closed"]
        say("join modal    : open=%s title=%r art=%s imgOk=%s w=%spx anim=%s"
              % (jn.get("open"), jn.get("title"), (jn.get("src") or "").rsplit("/", 1)[-1],
                 jn.get("imgOk"), jn.get("imgW"), jn.get("anim")))
        say("join buttons  : discord=%s bili=%r" % (jn.get("discord"), jn.get("bili")))
        say("join body     : (%s chars) %r" % (jn.get("bodyLen"), jn.get("bodyHead")))
        say("join bili note: %r" % R["join_bili"].get("note"))
        say("join closed   : open=%s (after closeJoin())" % jc.get("open"))
        hb, st, qq = R["hub"], R["star"], R["qq"]
        say("hub entries   : ids=%s github=%s flies=%s anim=%s"
              % (hb.get("ids"), hb.get("ghHref"), hb.get("flies"), hb.get("flyAnim")))
        _hs = R.get("join_scroll") or {}
        say("hub icon      : d=%r fill=%s box=%spx" % (hb.get("iconD"), hb.get("iconFill"),
                                                        hb.get("iconBox")))
        say("hub grid      : display=%s cols=%s rows=%s w=%s ids=%s"
              % (hb.get("actsDisplay"), hb.get("actCols"), hb.get("btnRows"),
                 hb.get("btnW"), hb.get("btnIds")))
        say("hub scroll    : idle=%s hovered=%s (scrollWidth vs clientWidth)"
              % (hb.get("scroll"), _hs.get("scroll")))
        say("star popup    : open=%s art=%s imgOk=%s %sx%s imgTop=%s textTop=%s anim=%s"
              % (st.get("open"), (st.get("src") or "").rsplit("/", 1)[-1], st.get("imgOk"),
                 st.get("imgW"), st.get("imgH"), st.get("imgTop"), st.get("textTop"), st.get("anim")))
        say("star copy     : title=%r (%s chars) %r"
              % (st.get("title"), st.get("bodyLen"), st.get("bodyHead")))
        say("star buttons  : href=%s later=%s closed=%s"
              % (st.get("href"), st.get("hasLater"), (R["star_closed"] or {}).get("open")))
        say("qq popup      : open=%s art=%s imgOk=%s w=%s no=%s copy=%s"
              % (qq.get("open"), (qq.get("src") or "").rsplit("/", 1)[-1], qq.get("imgOk"),
                 qq.get("imgW"), qq.get("no"), qq.get("hasCopy")))
        say("qq copy       : title=%r (%s chars) %r note=%r"
              % (qq.get("title"), qq.get("bodyLen"), qq.get("bodyHead"), qq.get("note")))
        say("clipboard     : after=%r before=%r dry=%s empty=%s"
              % (R["clip_after"], R["clip_before"], R["clip_dry"], R["clip_dry_bad"]))
        say("open_url gh   : %s" % R["url_gh"])
        say("open_url api  : good=%s bad=%s" % (R["url_ok"], R["url_bad"]))
        say("shots extra   : en=%s ls=%s join=%s"
              % (R.get("shot_en"), R.get("shot_ls"), R.get("shot_join")))
        dl = R["dialog"]
        say("folder dialog : ok=%s path=%s after=%ss %s"
              % (dl.get("ok"), dl.get("path"), dl.get("secs"), dl.get("err") or dl.get("status") or ""))
        say("dialog window : appeared=%s after=%ss" % (dl.get("window_appeared"),
                                                         dl.get("appeared_after")))
        if dl.get("debug"):
            say("dialog debug  : %s" % dl["debug"])

    def bad(cond, why):
        nonlocal ok
        if not cond:
            ok = False
            say("   FAIL: %s" % why)

    bad(R["loaded"].is_set(), "window did not load")
    bad(bool(p.get("hook")), "the Vue app did not mount (window.__cala missing)")
    bad((p.get("backend") or "").startswith("v"), "the page did not read /api/health")
    def _op(st, k):
        try:
            return float(st.get(k))
        except (TypeError, ValueError):
            return -1.0

    def _layers_ok(st, want):
        """`want` theme must be the one visible: its layer ~1, the other ~0.

        Opacities are compared with a tolerance instead of `== 1/0`: the layers
        cross-fade over 620 ms and a sample taken during the fade is not a bug.
        """
        ok_light = _op(st, "light") >= 0.9 if want == "light" else _op(st, "light") <= 0.1
        ok_dark = _op(st, "dark") >= 0.9 if want == "dark" else _op(st, "dark") <= 0.1
        return (st.get("theme") == want and ok_light and ok_dark
                and bool(st.get("lightImg")) and bool(st.get("darkImg")))

    _start = (R["bg_a"] or {}).get("theme")
    _flip = "light" if _start == "dark" else "dark"
    bad(_start in ("dark", "light"),
        "the theme attribute is neither dark nor light at rest: %s" % R["bg_a"])
    bad(_layers_ok(R["bg_a"] or {}, _start),
        "the %s layers are wrong at rest: %s" % (_start, R["bg_a"]))
    bad(_layers_ok(R["bg_b"] or {}, _flip),
        "toggling the theme did not switch to %s: %s" % (_flip, R["bg_b"]))
    bad(_layers_ok(R["bg_c"] or {}, _start),
        "toggling back did not restore %s: %s" % (_start, R["bg_c"]))
    bad((R["theme0"] or {}).get("theme") in ("dark", "light"),
        "the page came up without a theme on <html>: %s" % R["theme0"])
    # ---- the first-run guide (hello -> guide -> end) -------------------------
    bad(ob0.get("exists") is True, "window.__cala.onboard is missing: %s" % ob0)
    # the durable flag was cleared before the window existed: this IS a first run
    bad(ob0.get("auto") is True,
        "the guide did not open by itself on a fresh profile: %s" % ob0)
    bad(ob0.get("open") is True and ob0.get("step") == 0,
        "the guide did not open when restart(0) was called: %s" % ob0)
    bad(ob0.get("art") == "hello.png" and ob0.get("artOk") is True,
        "the welcome step must use hello.png and the image must decode: %s" % ob0)
    bad("欢迎" in (ob0.get("title") or ""),
        "the welcome copy is wrong: %r" % ob0.get("title"))
    bad(ob0.get("hole") is None,
        "the welcome step should not spotlight anything: %s" % ob0)
    bad(len(walk) == (ob0.get("total") or 0) and len(walk) >= 5,
        "walking the guide visited %s of %s steps" % (len(walk), ob0.get("total")))
    bad(arts[:1] == ["hello.png"] and arts[-1:] == ["end.png"],
        "the guide art must run hello.png -> ... -> end.png, got %s" % arts)
    bad(len(arts) >= 4 and all(x == "guide.png" for x in arts[1:-1]),
        "the middle steps must all use guide.png: %s" % arts)
    bad(all(w.get("artOk") for w in walk if w.get("open")),
        "a guide image failed to decode inside the app: %s" % walk)
    bad(len(masked) >= 3, "the guide never spotlighted a real element: %s" % walk)
    # ... and the two steps added in the fourth round are really among them
    walked_targets = [w.get("target") for w in walk]
    bad("#opt-force" in walked_targets and "#opt-adv" in walked_targets,
        "the guide is missing the -Force / Advanced steps: %s" % walked_targets)
    bad(any("Force" in (w.get("text") or "") or "限额" in (w.get("text") or "")
            for w in walk if w.get("target") == "#opt-force"),
        "the -Force step does not talk about the limits: %s"
        % [w.get("text") for w in walk if w.get("target") == "#opt-force"])

    off = []
    for w in masked:
        mk, hl = w.get("mask") or {}, w.get("hole") or {}
        if not hl or any(abs((mk.get(k) or -999) - (hl.get(k) or 0)) > 3
                         for k in ("x", "y", "w", "h")):
            off.append((w.get("target"), mk, hl))
    bad(not off, "the spotlight hole is not over the element it points at: %s" % off[:2])
    bad(len(masked) >= 3 and all(w.get("holeInView") is True for w in masked),
        "a spotlight hole was drawn outside the window: %s"
        % [(w.get("target"), w.get("hole")) for w in masked if w.get("holeInView") is not True])
    bad(all(w.get("activeDot") == 1 for w in walk if w.get("open")),
        "the step dots do not track the current step: %s"
        % [(w.get("step"), w.get("activeDot")) for w in walk])
    # the card must be really painted (in the DOM is not the same as visible)
    seen_open = [w for w in walk if w.get("open")]
    bad(seen_open and all((w.get("card") or {}).get("vis") == "visible"
                          and float((w.get("card") or {}).get("op") or 0) > 0.5
                          and ((w.get("card") or {}).get("w") or 0) > 200
                          and ((w.get("card") or {}).get("h") or 0) > 100
                          and (w.get("card") or {}).get("inView") is True
                          for w in seen_open),
        "the guide card is in the DOM but not really visible/inside the window: %s"
        % [w.get("card") for w in seen_open])
    bad(obe.get("open") is False and obe.get("stored") is True,
        "finishing the guide must close it and remember the choice: %s" % obe)
    # ---- ... and it must be remembered where a restart can still see it ------
    bad((R.get("prefs_after") or {}).get("prefs", {}).get("cala-onboarded") == "1",
        "the onboarding flag never reached the durable store: %s" % R.get("prefs_after"))
    _ob2 = R.get("ob_second") or {}
    _rg = R.get("reload_gen") or {}
    bad(_rg.get("has") is True and _rg.get("origin")
        and _rg.get("origin") != (R["probe"] or {}).get("origin"),
        "the page did not reload for the second-run check: %s" % _rg)
    bad(_ob2.get("exists") is True and _ob2.get("open") is False
        and _ob2.get("auto") is False and _ob2.get("stored") is True,
        "the guide came back on the second run (it must only auto-open once): %s" % _ob2)
    bad((R.get("prefs_restored") or {}) == (R.get("prefs_before") or {}),
        "the self-test did not put the user's own settings back: %s -> %s"
        % (R.get("prefs_before"), R.get("prefs_restored")))
    # the footer of every step stays on one row and never overflows its card
    _acts = [w.get("acts") for w in walk if w.get("acts")]
    bad(_acts and all(a.get("rows") == 1 and (a.get("overflow") or 0) <= 0
                      and a.get("nowrap") == "nowrap" and a.get("btns") >= 2
                      and (a.get("w") or 0) <= (a.get("cardW") or 0)
                      and min(a.get("btnH") or [0]) >= 24
                      for a in _acts),
        "the guide's button row wraps/squeezes/overflows: %s" % _acts[:3])
    # the browse button keeps a readable label next to a long path
    _bw = R.get("browse") or {}
    bad((_bw.get("w") or 0) >= 64 and _bw.get("hasIcon") is True
        and (_bw.get("labelH") or 99) <= 22 and _bw.get("clipped") is False
        and (_bw.get("flex") or "") == "0/0",
        "the browse button squeezes its label: %s" % _bw)
    # the left column must not lose 11px to a scrollbar the moment it overflows
    _lw = R.get("leftw") or {}
    bad(_lw.get("over1") is True and abs((_lw.get("w1") or 0) - (_lw.get("w0") or 0)) <= 1
        and abs((_lw.get("w2") or 0) - (_lw.get("w0") or 0)) <= 1
        and _lw.get("gutter") == "stable",
        "the left column changes width when its content grows: %s" % _lw)
    # ... and the fit dropdown really is on top of the DryRun row, not behind it
    _g1h = R.get("glide_1") or {}
    bad(_g1h.get("hit") == (_g1h.get("rows") or 0) - 1,
        "the open dropdown is painted behind another row (a click on 'contain' "
        "would land elsewhere): %s" % _g1h)
    bad(_g1h.get("menuPos") == "fixed" and _g1h.get("menuParent") == "BODY",
        "the dropdown is not a body-level popup any more: %s" % _g1h)
    # no option row may wrap into two lines or ellipsize its label (the fit chip
    # squeezes the label on its left)
    _ol = R.get("optlab") or {}
    bad(_ol.get("rows") and all((v.get("h") or 99) <= 22 and v.get("trunc") is False
                                for v in _ol["rows"].values()),
        "an option row label wrapped or was truncated: %s" % _ol)
    # the same has to hold at the minimum window size (330 px column)
    _olmin = R.get("optlab_min") or {}
    if _olmin.get("rows"):
        say("ui opt min    : chip=%spx %r rows=%s trunc=%s/%s"
              % (_olmin.get("chipW"), _olmin.get("chipText"),
                 {k: "%sx%s" % (v.get("w"), v.get("h")) for k, v in _olmin["rows"].items()},
                 len([v for v in _olmin["rows"].values() if v.get("trunc")]),
                 len(_olmin["rows"])))
        bad(all((v.get("h") or 99) <= 22 and v.get("trunc") is False
                for v in _olmin["rows"].values()),
            "an option row label wrapped or was truncated at the minimum window "
            "size: %s" % _olmin)
    # ---- i18n: the switch has to rewrite the page, not just flip a variable ----
    def _cjk(s):
        return any("\u4e00" <= c <= "\u9fff" for c in (s or ""))

    def _lat(s):
        return any(("a" <= c.lower() <= "z") for c in (s or ""))

    bad(zh.get("lang") == "zh" and zh.get("htmlLang") == "zh-CN",
        "the page is not in Chinese after setLang('zh'): %s" % zh)
    bad(en.get("lang") == "en" and en.get("htmlLang") == "en",
        "the page is not in English after setLang('en'): %s" % en)
    changed = [k for k in ("run", "cancel", "join", "guide", "inputs", "opts", "gates",
                           "optDry", "optForce", "optAdv", "empty")
               if zh.get(k) and en.get(k) and zh.get(k) != en.get(k)]
    bad(len(changed) >= 10,
        "switching the language did not rewrite the UI (only %s of 11 samples changed): %s"
        % (len(changed), {k: (zh.get(k), en.get(k)) for k in
                          ("run", "cancel", "join", "guide", "inputs", "opts", "gates",
                           "optDry", "optForce", "optAdv", "empty")}))
    bad(not _cjk(en.get("run")) and _lat(en.get("run")) and _cjk(zh.get("run")),
        "the English run button is not English (or the Chinese one is not Chinese): %r / %r"
        % (zh.get("run"), en.get("run")))
    bad(all(_cjk(zh.get(k)) and not _cjk(en.get(k))
            for k in ("cancel", "inputs", "opts", "optForce", "empty")),
        "some strings did not switch to English: %s"
        % {k: (zh.get(k), en.get(k)) for k in ("cancel", "inputs", "opts", "optForce", "empty")})
    bad(back.get("lang") == "zh" and back.get("run") == zh.get("run"),
        "switching back to Chinese did not restore the copy: %s" % back)
    # ---- the one-shot decode ripple fired by the language switch --------------
    bad((_zhs.get("total") or 0) >= 10 and _zhs.get("settled") == _zhs.get("total"),
        "not every ScrambleText node settled in Chinese (%s of %s): %s"
        % (_zhs.get("settled"), _zhs.get("total"), _zhs))
    bad((_zhs.get("run") or {}).get("text") == "开始打包",
        "the settled Chinese run label is wrong: %s" % _zhs.get("run"))
    bad((_ens.get("run") or {}).get("text") == "Start packing"
        and (_ens.get("run") or {}).get("settled") is True,
        "the English run label did not settle to the real text: %s" % _ens.get("run"))
    #: `series` / `running_max` / `noisy_s` / `hov` were computed for the report above
    bad((R["scr_run"] or {}).get("ok") is True,
        "could not fire the language switch for the ripple test: %s" % R["scr_run"])
    bad(running_max > 0 and len(noisy_s) >= 1,
        "no decode ripple happened during the language switch "
        "(max running=%s, noisy samples=%s of %s): %s"
        % (running_max, len(noisy_s), len(series), series[:6]))
    bad(series and (series[-1].get("running") or 0) == 0
        and series[-1].get("run") == "Start packing",
        "the ripple never finished (it must leave the settled English text): %s" % series[-4:])
    bad(hov and all((s.get("running") or 0) == 0 and s.get("run") == "Start packing" for s in hov),
        "hovering the text restarted the scramble -- it must only fire on a switch: %s" % hov[:6])
    bad((R["scr_back"].get("run") or {}).get("text") == "开始打包"
        and (R["scr_back"].get("settled") or 0) == (R["scr_back"].get("total") or -1),
        "switching back did not re-settle the Chinese copy: %s" % R["scr_back"])
    # ---- the Squish Switch ---------------------------------------------------
    bad(not (R["squish_move"] or {}).get("err"),
        "could not press the language switch: %s" % R["squish_move"])
    bad((_sq.get("n") or 0) >= 10, "the squish sampler never ran: %s" % _sq)
    bad(abs((_sq.get("maxSx") or 1) - 1) > 0.02,
        "the knob never stretched while travelling (no squish): %s" % _sq)
    bad((_sq.get("minSy") or 1) < 0.999,
        "the knob never squashed on the other axis: %s" % _sq)
    _sl = _sq.get("last") or {}
    bad(_sl.get("on") is True and (_sl.get("tx") or -1) > 25,
        "the knob did not end up at the English end after the press: %s" % _sl)
    bad((_sq.get("lang") or "") == "en",
        "pressing the Squish Switch did not switch the language: %s" % _sq)
    bad(not _sq.get("errors"), "the page threw while switching: %s" % _sq.get("errors"))
    # ---- the Glide Select ----------------------------------------------------
    bad((R["glide_open"] or {}).get("ok") is True,
        "could not open the Glide Select: %s" % R["glide_open"])
    bad(_g1.get("menu") is True and _g1.get("state") == "open" and (_g1.get("rows") or 0) == 2,
        "the Glide Select menu did not open with two rows: %s" % _g1)
    bad((_g1.get("fit") or "") == "cover" and (len(_g1.get("labels") or []) == 2),
        "the fit select did not start on cover / lost its rows: %s" % _g1)
    bad((_g1.get("pillOpacity") or 0) > 0.5,
        "the highlight pill is not visible on open: %s" % _g1)
    bad(abs((_g2.get("pillY") or 0) - (_g1.get("pillY") or 0)) >= 20,
        "the highlight pill did not glide to the hovered row (%s -> %s)"
        % (_g1.get("pillY"), _g2.get("pillY")))
    bad((_g3.get("fit") or "") == "contain",
        "picking the second row did not change the value: %s" % _g3)
    bad("contain" in (_g3.get("trigger") or ""),
        "the trigger label did not follow the picked value: %r" % _g3.get("trigger"))
    bad(_g3.get("menu") is False or _g3.get("state") == "absent",
        "the menu stayed open after a pick: %s" % _g3)
    if a.selftest_ui:
        bad(ui.get("ok") is True, "the UI-driven build did not succeed")
        gates = ui.get("gates") or {}
        bad(gates and all(gates.values()), "not every gate passed from the UI run: %s" % gates)
        # ---- the log panel scrolls on its own and follows the tail -------------
        lg = R["log"]
        bad(lg.get("overflowY") in ("auto", "scroll"),
            "the log panel must have its own scrollbar (overflow-y: auto), got %s" % lg)
        bad((lg.get("scrollHeight") or 0) > (lg.get("clientHeight") or 0) + 20,
            "the log did not overflow its box (no scrollbar needed) => scroll not proven: %s" % lg)
        bad(lg.get("atBottom") is True,
            "the log did not follow the newest line (not scrolled to the bottom): %s" % lg)
        # ---- the progress bar --------------------------------------------------
        pr, seen = R["prog"], [x for x in R["prog_seen"] if x is not None]
        bad(pr.get("exists") is True, "no progress bar in the page: %s" % pr)
        bad((pr.get("pct") or 0) >= 99,
            "the progress bar is not full after a successful build: %s" % pr)
        bad((pr.get("headSrc") or "").endswith("chongci.gif"),
            "the progress bar head is not chongci.gif: %s" % pr)
        bad((pr.get("headW") or 0) >= 68,
            "the chongci.gif head was not enlarged to >= 2x (68 px): %s" % pr)
        # the rail goes back to the original 12 px, and the big sprite must sit
        # exactly on the bar's centre line (not hang off it)
        bad((pr.get("trackH") or 0) == 12,
            "the progress rail is not back to 12 px: %s" % pr)
        bad(abs((pr.get("headCY") or 0) - (pr.get("trackCY") or 0)) <= 2,
            "the chongci.gif head is not vertically centred on the rail: %s" % pr)
        bad(abs((pr.get("headCY") or 0) - (pr.get("barCY") or 0)) <= 3,
            "the chongci.gif head is not vertically centred in the bar: %s" % pr)
        bad((pr.get("fill") or 0) >= (pr.get("track") or 1) - 8,
            "the progress fill does not reach the end of the track: %s" % pr)
        bad(len(seen) >= 2 and max(seen) > min(seen),
            "the progress bar never moved during the build: %s" % seen)
        # ---- the success modal -------------------------------------------------
        mok = R["modal_ok"]
        bad(mok.get("open") is True and mok.get("kind") == "ok",
            "no success modal after a successful build: %s" % mok)
        bad(R["modal_closed"].get("open") is False,
            "closeModal() did not dismiss the success modal: %s" % R["modal_closed"])
        bad("转换成功喵" in (mok.get("text") or ""),
            "the success modal text is wrong: %r" % mok.get("text"))
        bad((mok.get("src") or "").endswith("success.png") and mok.get("imgOk"),
            "the success modal image is wrong/missing: %s" % mok)
        bad(mok.get("hasExport") is not True,
            "the success modal must NOT offer the error-log export: %s" % mok)
        # ---- the failure modal + 导出错误日志 -----------------------------------
        mf = R["modal_fail"]
        bad(R["ui_fail"].get("ok") is False, "the deliberately bad run did not fail: %s" % R["ui_fail"])
        bad(mf.get("open") is True and mf.get("kind") == "fail",
            "no failure modal after a failed build: %s" % mf)
        bad("洗大锅" in (mf.get("text") or ""),
            "the failure modal text is wrong: %r" % mf.get("text"))
        bad((mf.get("src") or "").endswith("cry.png") and mf.get("imgOk"),
            "the failure modal image is wrong/missing: %s" % mf)
        bad(mf.get("hasExport") is True, "the failure modal has no 导出错误日志 button: %s" % mf)
        ex = R["export"]
        bad(ex.get("ok") is True, "exporting the error log failed: %s" % ex)
        bad((ex.get("size") or 0) > 0 and ex.get("mentions_task"),
            "the exported log file is empty or not about this task: %s" % ex)
        bad((ex.get("lines") or 0) >= 3, "the exported log looks too short: %s" % ex)
        bad((ex.get("empty_case") or {}).get("message") == "暂无日志可导出",
            "the 'nothing to export' case must answer 暂无日志可导出, got %s"
            % ex.get("empty_case"))
        # ---- no CMD black boxes ------------------------------------------------
        nw = R["nowin"]
        bad(nw.get("installed") is True, "the CREATE_NO_WINDOW patch is not installed: %s" % nw)
        bad(nw.get("last_flags_no_window") is True,
            "the last child was spawned WITHOUT CREATE_NO_WINDOW: %s" % nw)
        if nw.get("parent_has_console"):
            say("   NOTE: this parent owns a console, so children inherit it and a")
            say("         window can never pop up -- the property is only real in the")
            say("         console-less frozen exe (tests\\gui_exe_check.py), which")
            say("         asserts patched_hwnd=0 against a non-zero control.")
        else:
            bad(nw.get("patched_hwnd") == 0,
                "a child process DID get a console window: %s" % nw)
            bad(nw.get("control_hwnd") not in (None, 0, -1),
                "the positive control failed: without the patch the child still had "
                "no console window, so this check proves nothing: %s" % nw)
    if a.selftest_shell:
        for label, key in (("wide", "lay_wide"), ("min", "lay_min"),
                           ("big", "lay_big"), ("back", "lay_back")):
            v = R[key]
            bad(not v.get("err"), "layout probe failed at %s: %s" % (label, v))
            bad(v.get("cols") == 2, "expected 2 columns at %s, got %s" % (label, v.get("cols")))
            bad(325 <= (v.get("left") or 0) <= 470,
                "left column width out of range at %s: %s" % (label, v.get("left")))
            bad((v.get("log") or 0) >= 120,
                "log view too short at %s: %s" % (label, v.get("log")))
            # the log and the 判据 panel sit side by side at every size
            bad((v.get("panes") or 0) == 2 and (v.get("paneA") or 0) > 80
                and (v.get("paneB") or 0) > 80,
                "the log/判据 split collapsed at %s: %s" % (label, v))
            bad((v.get("handle") or 0) >= 8 and v.get("cursor") == "col-resize",
                "the divider is missing or not draggable at %s: %s" % (label, v))
            # ---- the right column must be FILLED, not shrunk-to-fit -----------
            # (a stray `.right` rule from the header used to leak in here:
            # align-items:center + flex-wrap:wrap made the split pane
            # shrink-to-fit, so it floated in the middle of the column and the
            # panes never grew with the window)
            bad((v.get("splitW") or 0) >= (v.get("rightW") or 0) - 1,
                "the split pane does not fill the right column at %s (%s of %s px): %s"
                % (label, v.get("splitW"), v.get("rightW"), v))
            bad(abs((v.get("paneAL") or 0) - (v.get("rightRight", 0) - v.get("rightW", 0))) <= 1,
                "the split pane is not flush with the column at %s: %s" % (label, v))
            bad(abs((v.get("paneA") or 0) - (v.get("paneB") or 0)) <= 2,
                "the two panes are not equal at 50/50 (%s/%s) at %s"
                % (v.get("paneA"), v.get("paneB"), label))
            bad((v.get("logW") or 0) > 80 and (v.get("gatesW") or 0) > 80,
                "the log / 判据 cards collapsed at %s: %s" % (label, v))
            bad((v.get("gatesLeft") or 0) + (v.get("gatesW") or 0)
                <= (v.get("rightRight") or 0) + 1,
                "the 判据 card runs past the right edge at %s: %s" % (label, v))
            # the chips row spans the column, so the task pill ends at its edge
            bad((v.get("chipsRight") or 0) >= (v.get("rightRight") or 0) - 1
                and (v.get("taskRight") or 0) >= (v.get("rightRight") or 0) - 1,
                "the stage/task pill row is not stretched to the column at %s: %s"
                % (label, v))
        # ... and the work area really adapts: the panes grow with the window
        _w, _b = R["lay_wide"], R["lay_big"]
        bad((_b.get("paneA") or 0) > (_w.get("paneA") or 0) + 20,
            "the panes do not grow with the window (%s -> %s): %s -> %s"
            % (_w.get("paneA"), _b.get("paneA"), _w, _b))
        # ... and it really moves when dragged (synthetic pointer events)
        sd, sa = R["split_drag"], R["split_after"]
        bad(not sd.get("err"), "could not drag the divider: %s" % sd)
        moved = (R.get("split_moved") or 0) - (sd.get("a0") or 0)
        bad(moved >= 80,
            "dragging the divider did not widen pane A (%+d px, %s -> %s): %s"
            % (moved, sd.get("a0"), R.get("split_moved"), sd))
        bad((sd.get("ratio") or 50) != 50, "the drag did not update the split ratio: %s" % sd)
        bad(abs((sa.get("paneA") or 0) - (sa.get("paneB") or 0)) <= 40,
            "after the reset the two panes are not 50/50: %s" % sa)
        # ---- the ReactBits Line Sidebar ---------------------------------------
        want = ["opt-fit", "opt-dryrun", "opt-combined", "opt-force", "opt-noatlas", "opt-adv"]
        bad(lm.get("ids") == want,
            "the options are not a Line Sidebar list: %s" % lm.get("ids"))
        near = lr.get("opt-force") or {}
        far = lr.get("opt-combined") or {}
        bad((near.get("eff") or 0) > 0.75,
            "the row under the cursor did not light up (--effect): %s" % near)
        bad((far.get("eff") or 1) < 0.25,
            "a row far from the cursor stayed lit: %s" % far)
        bad(abs(near.get("tx") or 0) >= 6,
            "the hovered row did not slide towards the cursor: %s" % near)
        bad(abs(far.get("tx") or 0) < 3, "a far row is still shifted: %s" % far)
        bad(near.get("color") and far.get("color") and near.get("color") != far.get("color"),
            "the colour gradient did not follow the cursor: %s vs %s" % (near, far))
        bad((near.get("marker") is True) and (near.get("eff") or 0) > 0.75,
            "the hovered row lost its marker line: %s" % near)
        bad((lr.get("opt-fit") or {}).get("active") is True
            and (lr.get("opt-dryrun") or {}).get("active") is True,
            "the pinned 'on' rows are not marked active: %s" % lr)
        bad((lr.get("opt-force") or {}).get("active") is False,
            "a row whose toggle is OFF must not read as active: %s" % lr.get("opt-force"))
        bad(all((v or {}).get("marker") is True for v in lr.values() if isinstance(v, dict)),
            "some rows have no marker line: %s" % lr)
        # ---- the "Join us" dialog ---------------------------------------------
        jn, jc = R["join"], R["join_closed"]
        bad(jn.get("open") is True, "the Join-us dialog did not open: %s" % jn)
        bad((jn.get("src") or "").endswith("joinus.png") and jn.get("imgOk") is True
            and (jn.get("imgW") or 0) > 120,
            "the dialog does not show joinus.png: %s" % jn)
        bad((jn.get("discord") or "").startswith("https://discord.com/invite/BGeYfMBwaw"),
            "the Discord button points somewhere else: %r" % jn.get("discord"))
        bad(jn.get("bili") == "#", "the Bilibili button is not a placeholder: %r" % jn.get("bili"))
        bad((jn.get("bodyLen") or 0) > 30 and _cjk(jn.get("bodyHead")),
            "the Join-us copy is missing/too short/not in Chinese: %r" % jn.get("bodyHead"))
        bad("喵" in (jn.get("title") or "") or "meow" in (jn.get("title") or "").lower(),
            "the Join-us title lost the cat voice: %r" % jn.get("title"))
        bad(jn.get("anim") == "uv-modal-in",
            "the dialog has no entrance animation: %s" % jn.get("anim"))
        bad(R["join_bili"].get("note"),
            "clicking the Bilibili placeholder said nothing (dead button): %s"
            % R["join_bili"].get("note"))
        bad(jc.get("open") is False, "closeJoin() did not dismiss the dialog: %s" % jc)
        bad((R["url_ok"] or {}).get("ok") is True and (R["url_ok"] or {}).get("dry") is True,
            "the open_url endpoint refused the Discord link: %s" % R["url_ok"])
        bad((R["url_bad"] or {}).get("ok") is False
            and (R["url_bad"] or {}).get("reason") == "blocked",
            "the open_url allow-list let an unknown url through: %s" % R["url_bad"])
        # ---- the two new community entries -----------------------------------
        bad(hb.get("ids") == ["join-discord", "join-bili", "join-github", "join-qq"],
            "the hub does not carry all four entries: %s" % hb.get("ids"))
        bad((hb.get("ghHref") or "").startswith("https://github.com/killa0132/CalaplayUpper"),
            "the GitHub entry points somewhere else: %r" % hb.get("ghHref"))
        bad((hb.get("flies") or 0) >= 6 and hb.get("flyAnim") == "gh-fly",
            "the GitHub icon has no flying-star field: %s" % hb)
        # the icon must be the Octicon the user pasted, not the old star
        bad((hb.get("iconD") or "").startswith("M10.226 17.284c-2.965-.36-5.054"),
            "the GitHub entry does not use the Octicon mark-github path: %r"
            % hb.get("iconD"))
        # four entries, one 2x2 grid, all the same width
        bad(hb.get("actsDisplay") == "grid" and hb.get("btnRows") == 2
            and len(hb.get("actCols", "").split()) == 2,
            "the four community buttons are not a 2x2 grid: %s" % hb)
        bad(len(set(hb.get("btnW") or [])) == 1 and (hb.get("btnW") or [0])[0] > 100,
            "the four community buttons have different widths: %s" % hb.get("btnW"))
        _sc = hb.get("scroll") or {}
        _sch = (R.get("join_scroll") or {}).get("scroll") or {}
        bad(_sc.get("sw", 1) <= _sc.get("cw", 0) + 1 and _sch.get("sw", 1) <= _sch.get("cw", 0) + 1,
            "the join dialog scrolls sideways -- the flying stars grow it: idle=%s hover=%s"
            % (_sc, _sch))
        bad(_sch.get("sh", 1) <= _sch.get("ch", 0) + 1,
            "hovering GitHub pulled a vertical scrollbar out of the dialog: %s" % _sch)
        bad((R["url_gh"] or {}).get("ok") is True,
            "the open_url allow-list does not accept the GitHub repository: %s" % R["url_gh"])
        bad(st.get("open") is True,
            "clicking GitHub did not pop the star dialog: %s" % st)
        bad((st.get("src") or "").endswith("star.png") and st.get("imgOk") is True
            and (st.get("imgW") or 0) > 120,
            "the star dialog does not show star.png: %s" % st)
        bad((st.get("imgTop") or 0) > 0 and (st.get("imgTop") or 0) < (st.get("textTop") or 0),
            "the star dialog is not a vertical stack (art above the copy): %s" % st)
        bad(abs((st.get("imgW") or 0) / max(1, st.get("imgH") or 1)
                - (st.get("natW") or 0) / max(1, st.get("natH") or 1)) < 0.08,
            "the star art is squashed (aspect ratio changed): %s" % st)
        bad("喵" in (st.get("title") or "") and (st.get("bodyLen") or 0) > 30,
            "the star copy lost the cat voice: %s" % st)
        bad((st.get("href") or "").startswith("https://github.com/killa0132/CalaplayUpper")
            and st.get("hasLater") is True,
            "the star dialog's buttons are wrong: %s" % st)
        bad(st.get("anim") == "uv-modal-in",
            "the star dialog has no entrance animation: %s" % st)
        bad((R["star_closed"] or {}).get("open") is False,
            "the star dialog would not close: %s" % R["star_closed"])
        bad(qq.get("open") is True and (qq.get("src") or "").endswith("joinQQ.png")
            and qq.get("imgOk") is True and (qq.get("imgW") or 0) > 100,
            "the QQ dialog does not show joinQQ.png: %s" % qq)
        bad(abs((qq.get("imgW") or 0) / max(1, qq.get("imgH") or 1)
                - (qq.get("natW") or 0) / max(1, qq.get("natH") or 1)) < 0.08,
            "the QQ art is squashed (aspect ratio changed): %s" % qq)
        bad(qq.get("no") == "1054243070",
            "the QQ dialog shows the wrong group number: %r" % qq.get("no"))
        bad("猫窝" in (qq.get("title") or ""),
            "the QQ title is not the requested line: %r" % qq.get("title"))
        bad("喵" in (qq.get("bodyHead") or "") and (qq.get("bodyLen") or 0) > 20,
            "the QQ copy lost the cat voice: %s" % qq)
        bad(qq.get("hasCopy") is True and qq.get("anim") == "uv-modal-in",
            "the QQ dialog has no copy button / no animation: %s" % qq)
        bad((qq.get("note") or "") != "", "the QQ dialog did not report the copy: %s" % qq)
        bad((R["qq_closed"] or {}).get("open") is False,
            "the QQ dialog would not close: %s" % R["qq_closed"])
        # the clipboard really received the number (read back through Win32)
        bad((R["clip_after"] or "") == "1054243070",
            "clicking the QQ entry did not put the group number on the clipboard: %r"
            % R["clip_after"])
        bad((R["clip_dry"] or {}).get("ok") is True and (R["clip_dry"] or {}).get("dry") is True,
            "the copy endpoint refused a dry run: %s" % R["clip_dry"])
        bad((R["clip_dry_bad"] or {}).get("ok") is False,
            "the copy endpoint accepted empty text: %s" % R["clip_dry_bad"])
        bad(R["clip_restored"] is None or R["clip_restored"] == R["clip_before"],
            "the self-test did not put the user's clipboard back: %r vs %r"
            % (R["clip_restored"], R["clip_before"]))
        # the window really is adaptive: a taller window must give a taller log
        wide, big = R["lay_wide"], R["lay_big"]
        bad((big.get("log") or 0) > (wide.get("log") or 0),
            "the log panel does not grow with the window (%s -> %s)"
            % (wide.get("log"), big.get("log")))
        dl = R["dialog"]
        bad(dl.get("ok") is True,
            "the native folder dialog call did not come back: %s" % dl)
        bad(dl.get("window_appeared") is True,
            "no native folder dialog window (#32770) ever appeared: %s" % dl)
        bad(dl.get("ok") is True and dl.get("path") is None and dl.get("secs", 0) >= 1.5,
            "the folder dialog must open, block and then cancel cleanly: %s" % dl)

    parts = []
    if not (a.selftest_shell or a.selftest_ui):
        parts.append("G2")
    if a.selftest_shell:
        parts.append("SHELL")
    if a.selftest_ui:
        parts.append("UI")
    tag = " ".join(parts) or "G2"
    say("%s SELFTEST: %s" % (tag, "OK" if ok else "FAIL (%s)" % (R["error"] or "see above")))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
