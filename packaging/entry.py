"""PyInstaller entry point of Tracklister.exe (windowed, no console).

SPDX-License-Identifier: GPL-3.0-or-later

Same as `python -m tracklister`. Kept outside src/ so that PyInstaller analyses the package
through its normal import path (pathex = src/).
"""
import sys

from tracklister.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
