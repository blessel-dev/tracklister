"""Entry point: `python -m tracklister` and the PyInstaller exe. Owner: GUI step.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    # One OpenBLAS thread, set before anything imports numpy (barrido AG-22b): otherwise numpy commits about
    # 350 MB for one idle OpenBLAS thread per CPU, and nothing in the app uses BLAS threads. The PyInstaller exe
    # enters here too (packaging/entry.py). On macOS numpy uses Accelerate and the variable does nothing. A value
    # the user set is respected.
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    from tracklister.gui.app import run
    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
