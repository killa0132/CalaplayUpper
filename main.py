# -*- coding: utf-8 -*-
"""Frozen entry point for CalaPlayerSrcmBuilder.exe (PyInstaller)."""
import os
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cli.build_srcm import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
