"""Brand assets contract: manifest, tokens, contrast, icon frames, logos, textures, fonts.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tracklister.assets import asset_path, assets_dir, load_tokens  # noqa: E402
from tracklister.core.model import ResultState  # noqa: E402

ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
COLOR_KEYS = {"bg", "surface", "surface_alt", "ink", "ink_muted", "line", "line_strong", "accent",
              "on_accent", "focus", "selection", "on_selection", "disabled_ink"} | {
    f"state_{s.value}" for s in ResultState}
HEX = re.compile(r"^#[0-9a-f]{6}$")


def _lum(h: str) -> float:
    def lin(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def png_header(data: bytes) -> tuple[int, int, int, int]:
    """(width, height, bit depth, colour type) from the IHDR chunk."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    length, ctype = struct.unpack(">I4s", data[8:16])
    assert ctype == b"IHDR" and length == 13
    w, h, depth, colour = struct.unpack(">IIBB", data[16:26])
    return w, h, depth, colour


@pytest.fixture(scope="module")
def tokens() -> dict:
    return load_tokens()


def test_manifest_hashes_match():
    man = json.loads(asset_path("manifest.json").read_text(encoding="utf-8"))
    assert man["schema"] == "tracklister.assets/1"
    assert len(man["files"]) > 50
    for rel, meta in man["files"].items():
        data = asset_path(rel).read_bytes()
        assert len(data) == meta["bytes"], rel
        assert hashlib.sha256(data).hexdigest() == meta["sha256"], rel
    # nothing shipped outside the manifest
    shipped = {p.relative_to(assets_dir()).as_posix() for p in assets_dir().rglob("*")
               if p.is_file() and "__pycache__" not in p.parts
               and p.name not in {"manifest.json", "__init__.py", ".gitattributes"}}
    assert shipped == set(man["files"])


def test_tokens_shape(tokens):
    assert tokens["schema"] == "tracklister.tokens/1"
    assert tokens["default_theme"] in tokens["themes"]
    assert set(tokens["themes"]) == {"hormigon", "noche"}
    assert set(tokens["states"]) == {s.value for s in ResultState}
    assert tokens["radius_px"] == 0
    for theme in tokens["themes"].values():
        assert set(theme["colors"]) == COLOR_KEYS
        assert all(HEX.match(v) for v in theme["colors"].values())
        for key in ("logo", "logo_2x", "lockup", "lockup_2x", "wordmark", "wordmark_2x", "header_texture"):
            assert asset_path(theme[key]).is_file(), theme[key]
    for st in tokens["states"].values():
        assert st["label_es"] and asset_path(st["icon"]).is_file()
    for rel in tokens["ui_icons"].values():
        assert asset_path(rel).is_file()
    for fam in tokens["fonts"].values():
        assert asset_path(fam["licence"]).is_file()
        for rel in fam["files"]:
            assert asset_path(rel).is_file()
    assert "blessel" not in tokens["app_icon"].lower()


@pytest.mark.parametrize("theme", ["hormigon", "noche"])
def test_contrast_thresholds(tokens, theme):
    c = tokens["themes"][theme]["colors"]
    stored = tokens["themes"][theme]["contrast"]
    text_pairs = [("ink", "bg"), ("ink", "surface"), ("ink", "surface_alt"), ("ink_muted", "bg"),
                  ("ink_muted", "surface"), ("ink_muted", "surface_alt"), ("on_accent", "accent"),
                  ("on_selection", "selection"), ("accent", "bg"), ("accent", "surface")]
    for a, b in text_pairs:
        assert contrast(c[a], c[b]) >= 4.5, (a, b)
        assert abs(stored[f"{a}/{b}"] - contrast(c[a], c[b])) < 0.01
    for a, b in [("line_strong", "bg"), ("line_strong", "surface"), ("focus", "bg"), ("focus", "surface")]:
        assert contrast(c[a], c[b]) >= 3.0, (a, b)
    for s in ResultState:
        col = c[f"state_{s.value}"]
        for b in ("bg", "surface", "surface_alt"):
            assert contrast(col, c[b]) >= 4.5, (s, b)  # text grade: labels may use the colour
        assert contrast(col, c["selection"]) >= 3.0, s
    assert stored["state_*/bg"] >= 4.5


def test_state_icons_single_path_monochrome():
    for s in ResultState:
        svg = asset_path(f"icons/state-{s.value}.svg").read_text(encoding="utf-8")
        assert 'viewBox="0 0 24 24"' in svg
        assert svg.count("<path") == 1
        assert set(re.findall(r'fill="([^"]+)"', svg)) == {"#000000"}


def test_icondir_frames_read_back():
    for rel in ("icon/tracklister.ico", "icon/alt/tracklister-alt.ico"):
        data = asset_path(rel).read_bytes()
        reserved, typ, count = struct.unpack_from("<HHH", data, 0)
        assert (reserved, typ) == (0, 1)
        sizes = []
        for i in range(count):
            w, h, _, _, planes, bpp, size, off = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
            w, h = w or 256, h or 256
            assert off + size <= len(data)
            pw, ph, depth, colour = png_header(data[off:off + size])
            assert (pw, ph) == (w, h) and depth == 8 and colour == 6 and bpp == 32 and planes == 1
            sizes.append(w)
        assert sizes == ICO_SIZES, rel
        # frames are distinct renders, not one image repeated
        assert len({data[o:o + s] for o, s in _frames(data)}) == count


def _frames(data: bytes):
    count = struct.unpack_from("<H", data, 4)[0]
    for i in range(count):
        size, off = struct.unpack_from("<II", data, 6 + 16 * i + 8)
        yield off, size


# macOS 1.1: the .app icon (tools/brand/build_icon.py), OSType -> side in px; ic11-ic14 are the @2x entries
ICNS_TYPES = {"icp4": 16, "icp5": 32, "icp6": 64, "ic07": 128, "ic08": 256, "ic09": 512, "ic10": 1024,
              "ic11": 32, "ic12": 64, "ic13": 256, "ic14": 512}


def _icns_entries(data: bytes) -> dict[str, bytes]:
    assert data[:4] == b"icns" and struct.unpack(">I", data[4:8])[0] == len(data)
    entries: dict[str, bytes] = {}
    off = 8
    while off < len(data):
        typ = data[off:off + 4].decode("ascii")
        length = struct.unpack(">I", data[off + 4:off + 8])[0]
        assert length > 8 and off + length <= len(data), typ
        assert typ not in entries, typ
        entries[typ] = data[off + 8:off + length]
        off += length
    return entries


def test_icns_frames_read_back():
    entries = _icns_entries(asset_path("icon/tracklister.icns").read_bytes())
    assert list(entries) == list(ICNS_TYPES)
    for typ, n in ICNS_TYPES.items():
        assert png_header(entries[typ]) == (n, n, 8, 6), typ           # a PNG of its own size, RGBA
    # every pixel size is its own render (the @2x entries reuse the frame of the same pixel size)
    by_size = {}
    for typ, n in ICNS_TYPES.items():
        by_size.setdefault(n, set()).add(entries[typ])
    assert all(len(v) == 1 for v in by_size.values()) and len({next(iter(v)) for v in by_size.values()}) == 7


@pytest.mark.gui
def test_icns_1024_frame_is_the_rounded_plate(qapp):
    from PySide6.QtGui import QImage

    img = QImage.fromData(_icns_entries(asset_path("icon/tracklister.icns").read_bytes())["ic10"])
    assert (img.width(), img.height()) == (1024, 1024) and img.hasAlphaChannel()
    for x, y in ((0, 0), (1023, 0), (0, 1023), (1023, 1023), (100, 100), (923, 923)):
        assert img.pixelColor(x, y).alpha() == 0, (x, y)                # transparent margin, rounded corners
    for x, y in ((512, 512), (512, 101), (101, 512), (300, 700)):
        assert img.pixelColor(x, y).alpha() == 255, (x, y)              # the plate is opaque
    assert img.pixelColor(512, 512).name() == load_tokens()["themes"]["hormigon"]["colors"]["ink"]   # the T stem
    assert img.pixelColor(300, 700).name() == load_tokens()["themes"]["hormigon"]["colors"]["bg"]


def test_png_assets_have_alpha():
    rels = [p.relative_to(assets_dir()).as_posix() for p in assets_dir().rglob("*.png")]
    assert any(r.startswith("logo/") for r in rels)
    for rel in rels:
        _, _, depth, colour = png_header(asset_path(rel).read_bytes())
        assert colour == 6 and depth == 8, rel  # RGBA
    w, _, _, _ = png_header(asset_path("logo/blessel-ink.png").read_bytes())
    w2, _, _, _ = png_header(asset_path("logo/blessel-ink@2x.png").read_bytes())
    assert (w, w2) == (240, 480)
    _, h, _, _ = png_header(asset_path("lockup/header-ink.png").read_bytes())
    _, h2, _, _ = png_header(asset_path("lockup/header-ink@2x.png").read_bytes())
    assert (h, h2) == (40, 80)


def test_textures_small():
    for theme in ("hormigon", "noche"):
        assert asset_path(f"textures/header-{theme}.jpg").stat().st_size < 500_000


@pytest.mark.gui
def test_qt_loads_fonts_logo_and_textures(qapp):
    from PySide6.QtGui import QFontDatabase, QImage

    tok = load_tokens()
    families = set()
    for fam in tok["fonts"].values():
        for rel in fam["files"]:
            fid = QFontDatabase.addApplicationFont(str(asset_path(rel)))
            assert fid >= 0, rel
            families.update(QFontDatabase.applicationFontFamilies(fid))
    assert {"Inter", "JetBrains Mono"} <= families
    for theme in ("hormigon", "noche"):
        img = QImage(str(asset_path(f"textures/header-{theme}.jpg")))
        assert (img.width(), img.height()) == (1600, 200)
    # default logo has NO 'OR' mark: its right-most ink column is the tall final 'l'
    for rel, expect_tall in (("logo/blessel-ink@2x.png", True), ("logo/alt/blessel-ink-or@2x.png", False)):
        img = QImage(str(asset_path(rel)))
        assert img.hasAlphaChannel()
        col = _rightmost_ink_column(img)
        tall = sum(1 for y in range(img.height()) if img.pixelColor(col, y).alpha() > 128)
        assert (tall > img.height() * 0.5) == expect_tall, rel


def _rightmost_ink_column(img) -> int:
    for x in range(img.width() - 1, -1, -1):
        if any(img.pixelColor(x, y).alpha() > 128 for y in range(img.height())):
            return x
    raise AssertionError("empty logo")
