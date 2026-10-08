"""Rebuild every brand asset in order (tokens -> textures -> logo -> icon -> svg -> manifest).

SPDX-License-Identifier: GPL-3.0-or-later

Run: .\\.venv\\Scripts\\python.exe tools\\brand\\build_all.py   (dev venv: needs pillow + scipy)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_icon  # noqa: E402
import build_logo  # noqa: E402
import build_manifest  # noqa: E402
import build_svg_icons  # noqa: E402
import build_texture  # noqa: E402
import build_tokens  # noqa: E402


def main() -> int:
    for step in (build_tokens, build_texture, build_logo, build_icon, build_svg_icons, build_manifest):
        rc = step.main()
        if rc:
            print(f"{step.__name__} failed ({rc})")
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
