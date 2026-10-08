"""Header textures from the grooved concrete wall of his Mixcloud cover.

SPDX-License-Identifier: GPL-3.0-or-later

Crop: the lower-right panels (even grooves, no plants, no lamp, no strong tree shadows).
Treatment: greyscale (desaturated), large-scale illumination flattened (divide by a wide
gaussian), then remapped to a narrow tonal band around each theme's header colour so the
header ink keeps its contrast. Output 1600x200 JPEG, < 500 KB.
"""
from __future__ import annotations

import sys

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

from common import ASSETS, SOURCE, contrast, load_tokens, rgb_to_hex

CROP = (3120, 2290, 4971, 2521)  # x0, y0, x1, y1 in the 4971x3131 source (8:1)
OUT = (1600, 200)
# (centre grey 0..255, half-range) per theme
TONE = {"hormigon": (176.0, 13.0), "noche": (30.0, 9.0)}


def base_strip() -> np.ndarray:
    im = Image.open(SOURCE / "hormigon-source.jpg").convert("L").crop(CROP)
    im = im.resize(OUT, Image.LANCZOS)
    a = np.asarray(im, dtype=np.float64)
    illum = ndi.gaussian_filter(a, 40.0) + 1.0
    flat = a / illum
    lo, hi = np.percentile(flat, [1, 99])
    return np.clip((flat - lo) / (hi - lo), 0.0, 1.0) * 2.0 - 1.0  # -1..1


def main() -> int:
    tok = load_tokens()
    strip = base_strip()
    report = {}
    for theme, (centre, half) in TONE.items():
        g = np.clip(centre + strip * half, 0, 255).astype(np.uint8)
        path = ASSETS / tok["themes"][theme]["header_texture"]
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(g, "L").convert("RGB").save(path, "JPEG", quality=85, optimize=True,
                                                     progressive=True)
        ink = tok["themes"][theme]["colors"]["ink"]
        muted = tok["themes"][theme]["colors"]["ink_muted"]
        p1, p99 = np.percentile(g, [0.5, 99.5])
        worst = min(contrast(ink, rgb_to_hex((p1,) * 3)), contrast(ink, rgb_to_hex((p99,) * 3)))
        worst_m = min(contrast(muted, rgb_to_hex((p1,) * 3)), contrast(muted, rgb_to_hex((p99,) * 3)))
        report[theme] = (path.stat().st_size, round(worst, 2), round(worst_m, 2))
        print(theme, path.name, path.stat().st_size, "bytes; ink worst", round(worst, 2),
              "muted worst", round(worst_m, 2))
        if path.stat().st_size >= 500_000:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
