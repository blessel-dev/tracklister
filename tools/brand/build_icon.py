"""App icon: multi-frame .ico, every frame drawn directly at its own size and pixel-snapped.

SPDX-License-Identifier: GPL-3.0-or-later

Chosen concept (icon/tracklister.ico): a 'T' monogram with the proportions of the Inter Bold
'T' of the wordmark (stem and bar thickness measured from the font outline), ink on the
logo's flat grey. Alternative (icon/alt/tracklister-alt.ico): vertical grooves, the concrete
wall of his cover, ink on grey. Both are drawn as integer rectangles per size, so every edge
lands on the pixel grid; nothing is ever downscaled from a bigger image.
The .ico stores PNG-compressed 32-bit frames (supported by Windows Vista and later).
"""
from __future__ import annotations

import io
import struct
import sys

import numpy as np
from PIL import Image

import qtext
from common import ASSETS, hex_to_rgb, load_tokens

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def t_proportions() -> dict:
    """Measure the Inter Bold 'T': bar width, stem width and bar thickness relative to cap height."""
    path = qtext.text_path("Inter-Bold.ttf", 1000.0, "T")
    polys = path.toFillPolygons()
    pts = [(p.x(), p.y()) for poly in polys for p in poly]
    xs = sorted({round(x, 2) for x, _ in pts})
    ys = sorted({round(y, 2) for _, y in pts})
    # a 'T' outline has 4 distinct x (bar l, stem l, stem r, bar r) and 3 distinct y
    # (top, bar bottom, baseline)
    if len(xs) != 4 or len(ys) != 3:
        raise RuntimeError(f"unexpected T outline: {xs} {ys}")
    cap = ys[2] - ys[0]
    return {"bar_w": (xs[3] - xs[0]) / cap, "stem_w": (xs[2] - xs[1]) / cap,
            "bar_h": (ys[1] - ys[0]) / cap}


def _parity(v: float, like: int, minimum: int) -> int:
    """Nearest integer >= minimum to v with the same parity as `like` (so it centres exactly)."""
    lo = int(np.floor(v))
    cands = [c for c in (lo - 1, lo, lo + 1, lo + 2) if c >= minimum and c % 2 == like % 2]
    return min(cands, key=lambda c: abs(c - v))


def draw_t(n: int, prop: dict, bg: str, ink: str) -> Image.Image:
    a = np.zeros((n, n, 4), np.uint8)
    a[..., :3] = hex_to_rgb(bg)
    a[..., 3] = 255
    cap = max(6, round(n * 0.625))
    bar_w = _parity(cap * prop["bar_w"], n, 5)
    stem = _parity(max(2.0, cap * prop["stem_w"]), bar_w, 2)
    bar_h = max(2, round(cap * prop["bar_h"]))
    top = (n - cap) // 2 + ((n - cap) % 2)  # optical: odd remainder goes to the top margin
    left = (n - bar_w) // 2
    sl = left + (bar_w - stem) // 2
    ink_rgb = hex_to_rgb(ink)
    a[top:top + bar_h, left:left + bar_w, :3] = ink_rgb
    a[top:top + cap, sl:sl + stem, :3] = ink_rgb
    return Image.fromarray(a, "RGBA")


def draw_grooves(n: int, bg: str, ink: str) -> Image.Image:
    a = np.zeros((n, n, 4), np.uint8)
    a[..., :3] = hex_to_rgb(bg)
    a[..., 3] = 255
    count = 4                          # always four grooves, like the wall panels
    g = max(1, round(n / 16))          # groove width
    gap = max(2, round(n * 0.09))
    margin = max(3, round(n * 0.1875))
    total = count * g + (count - 1) * gap
    x = (n - total) // 2
    ink_rgb = hex_to_rgb(ink)
    for i in range(count):
        x0 = x + i * (g + gap)
        a[margin:n - margin, x0:x0 + g, :3] = ink_rgb
    return Image.fromarray(a, "RGBA")


def write_ico(path, frames: list[Image.Image]) -> None:
    blobs = []
    for im in frames:
        b = io.BytesIO()
        im.save(b, "PNG", optimize=True)
        blobs.append(b.getvalue())
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = b""
    for im, blob in zip(frames, blobs):
        w, h = im.size
        entries += struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + b"".join(blobs))


def read_ico_sizes(path) -> list[tuple[int, int, int]]:
    """Read back the ICONDIR: [(width, height, bitcount)], decoding each PNG frame to check it."""
    data = path.read_bytes()
    reserved, typ, count = struct.unpack_from("<HHH", data, 0)
    assert reserved == 0 and typ == 1
    out = []
    for i in range(count):
        w, h, _, _, planes, bpp, size, off = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        w, h = w or 256, h or 256
        im = Image.open(io.BytesIO(data[off:off + size]))
        assert im.size == (w, h), (im.size, w, h)
        out.append((w, h, bpp))
    return out


def main() -> int:
    tok = load_tokens()
    c = tok["themes"]["hormigon"]["colors"]
    bg, ink = c["bg"], c["ink"]
    prop = t_proportions()
    print("Inter Bold T proportions", {k: round(v, 3) for k, v in prop.items()})
    t_frames = [draw_t(n, prop, bg, ink) for n in SIZES]
    g_frames = [draw_grooves(n, bg, ink) for n in SIZES]
    for n, im in zip(SIZES, t_frames):
        p = ASSETS / "icon" / "png" / f"tracklister-{n}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        im.save(p, optimize=True)
    for n, im in zip(SIZES, g_frames):
        p = ASSETS / "icon" / "alt" / "png" / f"tracklister-alt-{n}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        im.save(p, optimize=True)
    main_ico = ASSETS / "icon" / "tracklister.ico"
    alt_ico = ASSETS / "icon" / "alt" / "tracklister-alt.ico"
    write_ico(main_ico, t_frames)
    write_ico(alt_ico, g_frames)
    for p in (main_ico, alt_ico):
        sizes = read_ico_sizes(p)
        print(p.name, sizes)
        if [s[0] for s in sizes] != SIZES:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
