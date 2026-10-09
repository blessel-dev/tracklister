"""Entry point: `python -m tracklister` and the PyInstaller exe. Owner: GUI step.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import sys


def main() -> int:
    from tracklister.gui.app import run
    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
