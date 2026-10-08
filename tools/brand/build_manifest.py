"""Write src/tracklister/assets/manifest.json: size and SHA-256 of every shipped asset.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import hashlib
import sys

from common import ASSETS, write_json

SKIP_NAMES = {"manifest.json", "__init__.py", ".gitattributes"}


def collect() -> dict:
    files = {}
    for p in sorted(ASSETS.rglob("*")):
        if not p.is_file() or p.name in SKIP_NAMES or "__pycache__" in p.parts:
            continue
        data = p.read_bytes()
        files[p.relative_to(ASSETS).as_posix()] = {"bytes": len(data),
                                                   "sha256": hashlib.sha256(data).hexdigest()}
    return files


def main() -> int:
    files = collect()
    write_json(ASSETS / "manifest.json", {"schema": "tracklister.assets/1", "files": files})
    print(len(files), "files in manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
