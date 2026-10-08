"""Shared helpers for the brand build scripts (colour maths, paths, JSON).

SPDX-License-Identifier: GPL-3.0-or-later

Only tools/brand/ uses pillow/scipy; the app itself never imports this module.
"""
from __future__ import annotations

import colorsys
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOLS = Path(__file__).resolve().parent
SOURCE = TOOLS / "source"
ASSETS = REPO / "src" / "tracklister" / "assets"
FONT_SRC = Path(r"c:\projects\ABLETON\.agents\tasks\tracklister-v2\marca\work\fuentes-candidatas")


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, int(round(c)))):02x}" for c in rgb)


def _lin(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rel_lum(h: str) -> float:
    r, g, b = hex_to_rgb(h)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = rel_lum(a), rel_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def hls_hex(h_deg: float, l: float, s: float) -> str:
    r, g, b = colorsys.hls_to_rgb((h_deg % 360) / 360.0, l, s)
    return rgb_to_hex((r * 255, g * 255, b * 255))


def solve_lightness(h_deg: float, s: float, against: list[tuple[str, float]], darker: bool,
                    start_l: float) -> str:
    """Return the colour of hue/saturation closest to start_l (in HLS lightness) that meets every
    (background, min_ratio) pair. darker=True walks down from start_l, else up."""
    steps = [i / 1000.0 for i in range(1001)]
    if darker:
        cands = [l for l in reversed(steps) if l <= start_l]
    else:
        cands = [l for l in steps if l >= start_l]
    for l in cands:
        c = hls_hex(h_deg, l, s)
        if all(contrast(c, bg) >= need for bg, need in against):
            return c
    raise ValueError(f"no lightness meets {against} for hue {h_deg}")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def load_tokens() -> dict:
    return json.loads((ASSETS / "tokens.json").read_text(encoding="utf-8"))
