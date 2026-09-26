"""A handful of settings that must survive a restart.

`localStorage` cannot do this job here, and that was a real bug: the page is
served from ``http://127.0.0.1:<random port>/`` (the port is picked fresh on
every launch so nothing else on the machine can guess it), and a WebView2
profile keys ``localStorage`` by *origin* -- scheme + host + **port**.  So every
launch saw a brand new, empty origin, and "只在首次打开时自动弹出" could never
hold: the onboarding flag, the language choice, the theme and the split ratio
all silently fell back to their defaults.

The values therefore live in a tiny JSON file in per-user app data (next to the
working directory ``desktop.py`` already uses).  Only an allow-list of keys is
persisted -- this is not a general-purpose store, and nothing from the page may
wander into it.

The frontend mirrors the same keys into ``localStorage`` as well, so the dev
server (``vite`` on its own origin) and a plain browser still work; the backend
copy is what makes a packaged launch remember anything.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading

#: the only keys we accept (the page may POST anything; everything else is
#: dropped rather than stored)
ALLOWED = ("cala-onboarded", "cala-lang", "cala-theme", "cala-split")

#: values are short strings -- a hard cap so a buggy page cannot grow the file
MAX_VALUE = 64

_lock = threading.Lock()


def app_dir() -> str:
    """``%LOCALAPPDATA%\\CalaPlayerSrcmBuilder`` (same folder desktop.py cd's to).

    ``CALA_PREFS_DIR`` overrides it.  The packaged self-test points that at a temp folder, because
    it has to clear the onboarding flag to reproduce a genuine first run: restoring "what was there
    before" is lossy when the user had no other settings yet, and the restore then DELETED the real
    store -- so the next launch popped the guide again (reported 2026-09-26).
    """
    override = os.environ.get("CALA_PREFS_DIR")
    if override:
        return override
    base = os.path.join(os.environ.get("LOCALAPPDATA")
                        or os.path.expanduser("~"), "CalaPlayerSrcmBuilder")
    return base


def path() -> str:
    return os.path.join(app_dir(), "prefs.json")


def _clean(pairs) -> dict:
    out = {}
    if isinstance(pairs, dict):
        for k, v in pairs.items():
            if k in ALLOWED and isinstance(v, (str, int, float, bool)):
                out[str(k)] = str(v)[:MAX_VALUE]
    return out


def all_prefs() -> dict:
    """Everything we remember.  A missing/corrupt file is simply "nothing yet"."""
    try:
        with open(path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return _clean(data)


def put(pairs) -> dict:
    """Merge `pairs` in and return the full (sanitised) store.

    Written atomically (tmp + ``os.replace``) so a crash mid-write cannot leave a
    half-written file behind -- the next launch would then forget the guide had
    been seen and pop it again.
    """
    clean = _clean(pairs)
    with _lock:
        data = all_prefs()
        data.update(clean)
        try:
            os.makedirs(app_dir(), exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=app_dir(), prefix=".prefs-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, path())
        except OSError:
            try:
                os.remove(tmp)          # type: ignore[name-defined]
            except (OSError, NameError, UnboundLocalError):
                pass
        return data


def clear(keys=None) -> dict:
    """Drop the given keys (all of them by default) -- used by the self-test to
    reproduce a genuine first run, and to put the user's own settings back."""
    with _lock:
        data = all_prefs()
        for k in (ALLOWED if keys is None else keys):
            data.pop(k, None)
        try:
            if data:
                os.makedirs(app_dir(), exist_ok=True)
                with open(path(), "w", encoding="utf-8") as fh:
                    json.dump(data, fh, ensure_ascii=False, indent=1)
            elif os.path.exists(path()):
                os.remove(path())
        except OSError:
            pass
        return data
