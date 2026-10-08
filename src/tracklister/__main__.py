"""Entry point: `python -m tracklister` and the PyInstaller exe. Owner: GUI step.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import sys


def main() -> int:
    try:
        from tracklister.gui.app import run  # created by the GUI step
    except ImportError:
        print("Tracklister 1.0.0: la interfaz aun no esta construida (tracklister.gui.app.run).")
        return 1
    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
