from __future__ import annotations

import os
import sys


def resource_path(*parts: str) -> str:
    """Return an absolute path to a bundled resource.

    Works both when running from source and when frozen with PyInstaller.
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)
