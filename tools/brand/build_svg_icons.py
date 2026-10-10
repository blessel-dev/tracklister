"""Monochrome SVG icons (state-*.svg and ui-*.svg): one <path>, 24x24 viewBox, fill #000000.

SPDX-License-Identifier: GPL-3.0-or-later

Shapes are built from polygons. Outer contours are clockwise and holes counter-clockwise, so the
default nonzero fill rule gives the right result even where parts overlap. The GUI tints them.
Every state has its own SHAPE (not only its colour), and the GUI always shows the label too.
"""
from __future__ import annotations

import math
import sys

from common import ASSETS

Pt = tuple[float, float]


def _area(pts: list[Pt]) -> float:
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])) / 2


def poly(pts: list[Pt], hole: bool = False) -> list[Pt]:
    """Clockwise on screen (positive area with y down) for outers, counter-clockwise for holes."""
    pts = list(pts)
    if (_area(pts) > 0) == hole:
        pts.reverse()
    return pts


def rect(x0, y0, x1, y1, hole=False):
    return poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], hole)


def circle(cx, cy, r, hole=False, n=48):
    return poly([(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
                 for i in range(n)], hole)


def sector(cx, cy, r_out, r_in, a0_deg, a1_deg, n=40):
    """Annular sector between angles a0..a1 (degrees, y down: increasing = clockwise on screen)."""
    a = [math.radians(a0_deg + (a1_deg - a0_deg) * i / n) for i in range(n + 1)]
    outer = [(cx + r_out * math.cos(t), cy + r_out * math.sin(t)) for t in a]
    inner = [(cx + r_in * math.cos(t), cy + r_in * math.sin(t)) for t in reversed(a)]
    return poly(outer + inner)


def stroke(points: list[Pt], w: float) -> list[list[Pt]]:
    """A polyline of width w as overlapping quads plus round joints (all outer contours)."""
    out = []
    h = w / 2
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy)
        nx, ny = -dy / ln * h, dx / ln * h
        out.append(poly([(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)]))
    for p in points[1:-1]:
        out.append(circle(p[0], p[1], h, n=16))
    return out


def rotate(contours, deg, cx=12.0, cy=12.0):
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    return [[(cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c) for x, y in pts]
            for pts in contours]


def x_mark(cx, cy, half, w, hole=False):
    """An 'x' as a single 12-point contour."""
    k = w / math.sqrt(2) / 1.0
    a = half
    pts = [(cx - a, cy - a + k), (cx - a + k, cy - a), (cx, cy - k), (cx + a - k, cy - a), (cx + a, cy - a + k),
           (cx + k, cy), (cx + a, cy + a - k), (cx + a - k, cy + a), (cx, cy + k), (cx - a + k, cy + a),
           (cx - a, cy + a - k), (cx - k, cy)]
    return poly(pts, hole)


def fmt(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def path_d(contours) -> str:
    parts = []
    for pts in contours:
        parts.append("M" + " ".join(f"{fmt(x)} {fmt(y)}" for x, y in pts) + "Z")
    return "".join(parts)


def icons() -> dict[str, list[list[Pt]]]:
    check = [(6.2, 12.4), (8.3, 10.3), (10.5, 12.5), (15.6, 7.4), (17.7, 9.5), (10.5, 16.7)]
    # 1.0.1 "Verificado · revisar calidad": an open check mark over a small wave (the spectrum)
    wave = [(3.5 + 17.0 * i / 16, 19.2 - 1.7 * math.sin(2 * math.pi * 1.5 * i / 16)) for i in range(17)]
    return {
        # ---- states ---------------------------------------------------------------------
        "state-verificado": [rect(3, 3, 21, 21), poly(check, hole=True)],
        "state-revisar_calidad": stroke([(3.5, 8.5), (8.0, 13.0), (18.5, 2.5)], 2.6) + stroke(wave, 2.0),
        "state-dudoso": [poly([(12, 2), (23, 21.5), (1, 21.5)]),
                         rect(11, 8.5, 13, 15, hole=True), rect(11, 16.5, 13, 18.5, hole=True)],
        "state-no_encontrado": [circle(10, 10, 7.5), circle(10, 10, 5.5, hole=True),
                                *rotate([rect(9.2, 16.8, 10.8, 23)], -45, 10, 10),
                                x_mark(10, 10, 2.6, 1.6)],
        "state-pendiente": [circle(12, 12, 9.5), circle(12, 12, 7.5, hole=True),
                            poly([(11, 6.5), (13, 6.5), (13, 11), (16.5, 11), (16.5, 13), (11, 13)])],
        "state-en_curso": [circle(12, 12, 9.5), circle(12, 12, 7.5, hole=True),
                           sector(12, 12, 5.5, 0.0, -90, 90)],
        "state-no_cumple_formato": [poly([(5, 2), (14, 2), (19, 7), (19, 22), (5, 22)]),
                                    rect(8, 13, 16, 15, hole=True)],
        "state-fallida": [circle(12, 12, 10), x_mark(12, 12, 4.6, 2.2, hole=True)],
        "state-ya_en_biblioteca": [rect(3, 4, 7, 20), rect(9, 4, 13, 20),
                                   *rotate([rect(15, 4.5, 19, 20.5)], -14, 17, 20), rect(2, 21, 22, 22.5)],
        "state-omitida": [poly([(3, 5), (11, 12), (3, 19)]), poly([(11, 5), (19, 12), (11, 19)]),
                          rect(19, 5, 21, 19)],
        # ---- ui -------------------------------------------------------------------------
        "ui-abrir": [poly([(2, 14), (4, 14), (4, 19), (20, 19), (20, 14), (22, 14), (22, 21), (2, 21)]),
                     poly([(12, 2), (18, 8), (16.6, 9.4), (13, 5.8), (13, 16), (11, 16), (11, 5.8),
                           (7.4, 9.4), (6, 8)])],
        "ui-copiar": [rect(3, 3, 15, 15), rect(5, 5, 13, 13, hole=True), rect(9, 9, 21, 21)],
        "ui-reintentar": [sector(12, 13, 8, 6, -30, 270), poly([(12, 0.5), (17, 6), (12, 11.5)])],
        "ui-ajustes": [rect(3, 5, 21, 7), rect(3, 11, 21, 13), rect(3, 17, 21, 19),
                       rect(6, 3, 10, 9), rect(14, 9, 18, 15), rect(8, 15, 12, 21)],
        "ui-pegar": [rect(4, 4, 20, 22), rect(6, 6, 18, 20, hole=True), rect(8, 2, 16, 7),
                     rect(8, 10, 16, 12), rect(8, 14, 14, 16)],
        "ui-enlace": rotate([rect(1, 8, 14, 16), rect(3, 10, 12, 14, hole=True),
                             rect(10, 8, 23, 16), rect(12, 10, 21, 14, hole=True)], -45),
        "ui-carpeta": [poly([(2, 4), (9, 4), (11, 6.5), (22, 6.5), (22, 20), (2, 20)]),
                       rect(4, 9, 20, 18, hole=True)],
        "ui-deshacer": [poly([(2, 10), (8, 4.5), (8, 15.5)]), rect(7.9, 9, 14, 11),
                        sector(14, 14.5, 5.5, 3.5, -90, 90), rect(7, 18, 14.05, 20)],
        "ui-diagnostico": stroke([(2, 12), (7, 12), (9.5, 5.5), (14.5, 18.5), (17, 12), (22, 12)], 2.0),
    }


def svg(d: str) -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
            f'<path fill="#000000" d="{d}"/></svg>\n')


def main() -> int:
    out = ASSETS / "icons"
    out.mkdir(parents=True, exist_ok=True)
    for name, contours in icons().items():
        (out / f"{name}.svg").write_text(svg(path_d(contours)), encoding="utf-8", newline="\n")
    print(len(icons()), "icons")
    return 0


if __name__ == "__main__":
    sys.exit(main())
