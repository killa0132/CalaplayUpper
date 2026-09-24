# -*- coding: utf-8 -*-
"""CalaPlayerSrcmBuilder GUI (Vue 3 + FastAPI + PyWebView).

Hard rule for this whole package: `core/`, `cli/`, `main.py` and the two
`build_*.ps1` scripts are NOT touched.  The GUI reuses the very same
`core.builder.Builder` that the CLI uses, so every gate (A0~A7), the deploy
path, the rollback path and `build.log` / `build_report.json` are identical.
"""
