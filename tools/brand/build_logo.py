"""Blessel logo (SDF rebuild), "Tracklister" wordmark and the header lockup.

SPDX-License-Identifier: GPL-3.0-or-later

Outputs (transparent PNG, every size rendered directly from vectors/SDF, never resized):
  logo/blessel-{ink,light}.png (240 px wide) and @2x (480 px)    default, WITHOUT 'OR'
  logo/alt/blessel-{ink,light}-or.png and @2x                     alternative WITH 'OR'
  wordmark/tracklister-{ink,light}.png and @2x                    Inter Bold
  lockup/header-{ink,light}.png and @2x                           40 px high @1x
"""
from __future__ import annotations

import math
import sys

import numpy as np
from PIL import Image

import qtext
import sdf_lib as L
from common import ASSETS, hex_to_rgb, load_tokens

LOGO_W = 240
WORDMARK_PX = 28.0
WORDMARK_FILE = "Inter-Bold.ttf"
WORDMARK_TRACKING = 98.5  # percent; a touch tighter, like the Blessel grotesque
LOCKUP_H = 40
LOCKUP_WM_PX = 26.0
LOCKUP_BY_PX = 11.0
LOCKUP_LOGO_CAP = 12.0     # cap height of the Blessel signature @1x
LOCKUP_GAP_BY = 9.0
LOCKUP_GAP_LOGO = 4.0
CAP_SRC = L.BASELINE_Y - L.CAP_TOP_Y


def compose(size, layers) -> Image.Image:
    """layers: [(alpha HxW 0..1, '#rrggbb')] painted in order with 'over'; returns straight RGBA."""
    w, h = size
    rgb = np.zeros((h, w, 3))
    a = np.zeros((h, w))
    for al, colour in layers:
        c = np.array(hex_to_rgb(colour), float)
        out_a = al + a * (1 - al)
        with np.errstate(invalid="ignore", divide="ignore"):
            rgb = np.where(out_a[..., None] > 0,
                           (c * al[..., None] + rgb * (a * (1 - al))[..., None]) / out_a[..., None], 0)
        a = out_a
    px = np.zeros((h, w, 4), np.uint8)
    px[..., :3] = np.round(rgb).astype(np.uint8)
    px[..., 3] = np.round(a * 255).astype(np.uint8)
    return Image.fromarray(px, "RGBA")


def build_logos(colours: dict[str, str]) -> None:
    for keep, sub, suffix in (("no_or", "logo", ""), ("all", "logo/alt", "-or")):
        sdf, union, _ = L.build_sdf(keep, "subpixel")
        x0, y0, x1, y1 = L.ink_bbox(union)
        for k, tag in ((1, ""), (2, "@2x")):
            w = LOGO_W * k
            pad = 4 * k
            s = (w - 2 * pad) / (x1 - x0)
            h = int(math.ceil((y1 - y0) * s + 2 * pad))
            alpha = L.render_alpha(sdf, (x0 - pad / s, y0 - pad / s), s, w, h)
            for variant, colour in colours.items():
                out = ASSETS / sub / f"blessel-{variant}{suffix}{tag}.png"
                out.parent.mkdir(parents=True, exist_ok=True)
                compose((w, h), [(alpha, colour)]).save(out, optimize=True)


def build_wordmarks(colours: dict[str, str]) -> None:
    for k, tag in ((1, ""), (2, "@2x")):
        path = qtext.text_path(WORDMARK_FILE, WORDMARK_PX * k, "Tracklister", WORDMARK_TRACKING)
        r = path.boundingRect()
        pad = 2 * k
        baseline = math.ceil(pad - r.top())
        w = int(math.ceil(r.width() + 2 * pad))
        h = int(baseline + pad)
        alpha = qtext.path_alpha(path, w, h, pad - r.left(), baseline)
        for variant, colour in colours.items():
            out = ASSETS / "wordmark" / f"tracklister-{variant}{tag}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            compose((w, h), [(alpha, colour)]).save(out, optimize=True)


def build_lockups(themes: dict[str, dict]) -> dict:
    sdf, union, _ = L.build_sdf("no_or", "subpixel")
    lx0, _, lx1, _ = L.ink_bbox(union)
    info = {}
    for k, tag in ((1, ""), (2, "@2x")):
        wm = qtext.text_path(WORDMARK_FILE, LOCKUP_WM_PX * k, "Tracklister", WORDMARK_TRACKING)
        by = qtext.text_path("Inter-Medium.ttf", LOCKUP_BY_PX * k, "by")
        rw, rb = wm.boundingRect(), by.boundingRect()
        h = LOCKUP_H * k
        asc = -rw.top()
        baseline = int(round(h / 2 + asc / 2))
        x_wm = 1 * k - rw.left()
        x_by = x_wm + rw.right() + LOCKUP_GAP_BY * k - rb.left()
        s = LOCKUP_LOGO_CAP * k / CAP_SRC
        x_logo = x_by + rb.right() + LOCKUP_GAP_LOGO * k
        w = int(math.ceil(x_logo + (lx1 - lx0) * s + 1 * k))
        a_wm = qtext.path_alpha(wm, w, h, x_wm, baseline)
        a_by = qtext.path_alpha(by, w, h, x_by, baseline)
        a_logo = L.render_alpha(sdf, (lx0 - x_logo / s, L.BASELINE_Y - baseline / s), s, w, h)
        for theme, variant in (("hormigon", "ink"), ("noche", "light")):
            c = themes[theme]["colors"]
            img = compose((w, h), [(a_wm, c["ink"]), (a_by, c["ink_muted"]), (a_logo, c["ink"])])
            out = ASSETS / "lockup" / f"header-{variant}{tag}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            img.save(out, optimize=True)
        info[tag or "@1x"] = {"size": [w, h], "baseline": baseline}
    return info


def main() -> int:
    tok = load_tokens()
    themes = tok["themes"]
    colours = {"ink": themes["hormigon"]["colors"]["ink"], "light": themes["noche"]["colors"]["ink"]}
    build_logos(colours)
    build_wordmarks(colours)
    print("lockup", build_lockups(themes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
