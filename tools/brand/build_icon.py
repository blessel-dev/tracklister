"""App icon: multi-frame .ico, every frame drawn directly at its own size and pixel-snapped.

SPDX-License-Identifier: GPL-3.0-or-later

Chosen concept (icon/tracklister.ico): a 'T' monogram with the proportions of the Inter Bold
'T' of the wordmark (stem and bar thickness measured from the font outline), ink on the
logo's flat grey. Alternative (icon/alt/tracklister-alt.ico): vertical grooves, the concrete
wall of his cover, ink on grey. Both are drawn as integer rectangles per size, so every edge
lands on the pixel grid; nothing is ever downscaled from a bigger image.
The .ico stores PNG-compressed 32-bit frames (supported by Windows Vista and later).

macOS (1.1, icon/tracklister.icns): the same 'T' on Apple's app icon template, a rounded plate with
a transparent margin, because macOS 26 frames icons without that shape in a grey square. Each frame
(16 to 1024 px) is drawn at its own size too: the plate's edge gets the exact area of each pixel that
it covers (an integral, never a downscale), the 'T' stays whole pixels. Flat: no shadow or gradient.
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

# macOS app icon grid (macOS 11 and later): on a 1024 px canvas the plate is an 824 px rounded square,
# centred (100 px margins), with a 185.4 px corner radius; the rest of the canvas is transparent.
MAC_SIZES = [16, 32, 64, 128, 256, 512, 1024]
MAC_PLATE = 824 / 1024
MAC_RADIUS = 185.4 / 1024
# .icns entries (OSType, side in px), every payload a PNG (macOS 10.7 and later). ic11-ic14 are the
# @2x (Retina) versions of 16, 32, 128 and 256 pt.
ICNS_TYPES = [("icp4", 16), ("icp5", 32), ("icp6", 64), ("ic07", 128), ("ic08", 256), ("ic09", 512),
              ("ic10", 1024), ("ic11", 32), ("ic12", 64), ("ic13", 256), ("ic14", 512)]


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


def _quarter_disc_area(x: np.ndarray, y: np.ndarray, r: float) -> np.ndarray:
    """Area of {0 <= u <= x, 0 <= v <= y, u^2 + v^2 <= r^2} for x, y >= 0, exactly."""
    x = np.minimum(x, r)
    y = np.minimum(y, r)
    xc = np.sqrt(np.maximum(r * r - y * y, 0.0))      # where the arc crosses v = y

    def prim(u):                                      # integral of sqrt(r^2 - u^2) from 0 to u
        return 0.5 * (u * np.sqrt(np.maximum(r * r - u * u, 0.0)) + r * r * np.arcsin(np.clip(u / r, -1.0, 1.0)))

    return np.where(x <= xc, x * y, y * xc + prim(x) - prim(xc))


def _disc_box_area(x0, x1, y0, y1, r: float) -> np.ndarray:
    """Area of the disc of radius r centred at the origin inside the box [x0, x1] x [y0, y1]."""
    def h(x, y):                                      # oriented area from the origin to (x, y)
        return np.sign(x) * np.sign(y) * _quarter_disc_area(np.abs(x), np.abs(y), r)

    return h(x1, y1) - h(x0, y1) - h(x1, y0) + h(x0, y0)


def rounded_square_coverage(n: int, side: float, radius: float) -> np.ndarray:
    """Fraction (0..1) of each pixel of an n x n canvas covered by a centred rounded square of `side` px
    with corner radius `radius` px: the exact area of the pixel inside the shape (pixel (i, j) is the
    unit square [j, j+1] x [i, i+1])."""
    lo, hi = (n - side) / 2.0, (n + side) / 2.0
    p0 = np.arange(n, dtype=np.float64)
    p1 = p0 + 1.0

    def overlap(a, b):                                # 1-D overlap of every pixel with [a, b]
        return np.clip(np.minimum(p1, b) - np.maximum(p0, a), 0.0, 1.0)

    cover = np.outer(overlap(lo, hi), overlap(lo, hi))
    for cx, bx in ((lo + radius, (lo, lo + radius)), (hi - radius, (hi - radius, hi))):
        for cy, by in ((lo + radius, (lo, lo + radius)), (hi - radius, (hi - radius, hi))):
            # the corner box minus its quarter disc is outside the shape
            box = np.outer(overlap(*by), overlap(*bx))
            gx0, gx1 = np.maximum(p0, bx[0]), np.minimum(p1, bx[1])
            gy0, gy1 = np.maximum(p0, by[0]), np.minimum(p1, by[1])
            X0, Y0 = np.meshgrid(gx0 - cx, gy0 - cy)
            X1, Y1 = np.meshgrid(gx1 - cx, gy1 - cy)
            inside = (X1 > X0) & (Y1 > Y0)
            disc = np.where(inside, _disc_box_area(X0, X1, Y0, Y1, radius), 0.0)
            cover -= np.clip(box - disc, 0.0, None)
    return np.clip(cover, 0.0, 1.0)


def draw_t_macos(n: int, prop: dict, bg: str, ink: str) -> Image.Image:
    """The 'T' of draw_t on Apple's rounded plate (MAC_PLATE, MAC_RADIUS), with a transparent margin.
    The 'T' keeps its proportions, scaled to the plate, and whole pixels, centred like on Windows."""
    plate = n * MAC_PLATE
    alpha = rounded_square_coverage(n, plate, n * MAC_RADIUS)
    a = np.zeros((n, n, 4), np.uint8)
    a[..., :3] = hex_to_rgb(bg)
    a[..., 3] = np.round(alpha * 255.0).astype(np.uint8)
    cap = max(6, round(plate * 0.625))
    bar_w = _parity(cap * prop["bar_w"], n, 5)
    stem = _parity(max(2.0, cap * prop["stem_w"]), bar_w, 2)
    bar_h = max(2, round(cap * prop["bar_h"]))
    top = (n - cap) // 2 + ((n - cap) % 2)  # optical: odd remainder goes to the top margin
    left = (n - bar_w) // 2
    sl = left + (bar_w - stem) // 2
    ink_rgb = hex_to_rgb(ink)
    a[top:top + bar_h, left:left + bar_w, :3] = ink_rgb
    a[top:top + cap, sl:sl + stem, :3] = ink_rgb
    a[top:top + bar_h, left:left + bar_w, 3] = 255
    a[top:top + cap, sl:sl + stem, 3] = 255
    return Image.fromarray(a, "RGBA")


def write_icns(path, frames: list[Image.Image]) -> None:
    """Apple icon family: b'icns', the total length, then one (OSType, length, PNG) entry per
    ICNS_TYPES; `frames` are the MAC_SIZES renders (a @2x entry reuses the frame of its pixel size)."""
    pngs = {}
    for im in frames:
        b = io.BytesIO()
        im.save(b, "PNG", optimize=True)
        pngs[im.size[0]] = b.getvalue()
    body = b"".join(t.encode("ascii") + struct.pack(">I", 8 + len(pngs[n])) + pngs[n] for t, n in ICNS_TYPES)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"icns" + struct.pack(">I", 8 + len(body)) + body)


def read_icns(path) -> list[tuple[str, int, int]]:
    """Read back the entries: [(OSType, width, height)], decoding each PNG to check it."""
    data = path.read_bytes()
    assert data[:4] == b"icns" and struct.unpack(">I", data[4:8])[0] == len(data)
    out, off = [], 8
    while off < len(data):
        typ = data[off:off + 4].decode("ascii")
        length = struct.unpack(">I", data[off + 4:off + 8])[0]
        im = Image.open(io.BytesIO(data[off + 8:off + length]))
        out.append((typ, *im.size))
        off += length
    return out


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
    icns = ASSETS / "icon" / "tracklister.icns"
    write_icns(icns, [draw_t_macos(n, prop, bg, ink) for n in MAC_SIZES])
    entries = read_icns(icns)
    print(icns.name, entries)
    if entries != [(t, n, n) for t, n in ICNS_TYPES]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
