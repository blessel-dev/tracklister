"""The .icns of the .app (tools/brand/build_icon.py) is read back by Apple's own iconutil. macOS only.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

from tests.darwin.conftest import REPO, run_tool

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="solo macOS")

ICNS = REPO / "src" / "tracklister" / "assets" / "icon" / "tracklister.icns"
# the ten PNGs of an .iconset and their side in pixels
ICONSET = {"icon_16x16.png": 16, "icon_16x16@2x.png": 32, "icon_32x32.png": 32, "icon_32x32@2x.png": 64,
           "icon_128x128.png": 128, "icon_128x128@2x.png": 256, "icon_256x256.png": 256,
           "icon_256x256@2x.png": 512, "icon_512x512.png": 512, "icon_512x512@2x.png": 1024}


def png_side(path: Path) -> int | None:
    head = path.read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return w if w == h else None


def test_iconutil_reads_the_icns_back(tmp_path):
    out = tmp_path / "tracklister.iconset"
    r = run_tool(["/usr/bin/iconutil", "-c", "iconset", str(ICNS), "-o", str(out)])
    assert r.returncode == 0, r.stdout + r.stderr
    got = {p.name: png_side(p) for p in out.iterdir()}
    assert {name: got.get(name) for name in ICONSET} == ICONSET, got
