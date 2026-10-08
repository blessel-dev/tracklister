"""Rebuild the Blessel logotype from its JPEG as a signed distance field (SDF).

SPDX-License-Identifier: GPL-3.0-or-later

Adapted from marca/work/sdf_lib.py (same measurements). Source: blessel-logo-source.jpg
(1440x1440, near-black ink on flat grey #afafaf, plus a tiny 'OR' mark after the final 'l').

Method (per region):
1. coverage = projection of each pixel colour onto the background->ink segment (0..1), i.e. the
   antialiasing of the source turned into sub-pixel coverage;
2. binary mask = coverage > 0.5, small spurious holes (JPEG noise) closed with
   binary_fill_holes (real counters are far larger than the threshold);
3. for EACH connected component (letter) its own SDF: Euclidean distance away from the edge,
   and, only in the 1-px boundary ring, the exact sub-pixel distance coverage - 0.5;
   a light gaussian (0.35 px) stitches the ring to the EDT;
4. the letters are united with max(); the 'OR' components are dropped by default.
Fallback (method="binario"): binary SDF + gaussian_filter(sdf, 0.9).
Convention: sdf > 0 inside the ink, in source pixels; array cell [i, j] is the value at the
pixel centre (j + 0.5, i + 0.5).
"""
from __future__ import annotations

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

from common import SOURCE

SRC = SOURCE / "blessel-logo-source.jpg"
CROP = (215, 567, 1255, 853)  # x0, y0, x1, y1 in the source (the whole logotype + 40 px margin)
OR_MIN_X = 1188               # components starting right of this (after the final 'l') = 'OR'
CAP_TOP_Y = 607 - CROP[1]     # top of 'B' and 'l' in crop coordinates
BASELINE_Y = 810 - CROP[1]    # bottom edge of 'B' (pixel row 809 is its last ink row)


def load_source():
    img = np.asarray(Image.open(SRC).convert("RGB"), dtype=np.float64)
    bw = 48
    border = np.concatenate([img[:bw].reshape(-1, 3), img[-bw:].reshape(-1, 3),
                             img[bw:-bw, :bw].reshape(-1, 3), img[bw:-bw, -bw:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    lum = img.mean(axis=2)
    thr = (bg.mean() + np.percentile(lum, 0.5)) / 2
    core = ndi.binary_erosion(lum < thr, iterations=6)
    ink = np.median(img[core], axis=0)
    x0, y0, x1, y1 = CROP
    return img[y0:y1, x0:x1], bg, ink


def coverage(crop, bg, ink):
    v = ink - bg
    return np.clip(((crop - bg) @ v) / (v @ v), 0.0, 1.0)


def clean_components(cob, keep="no_or", min_speck=30, max_hole=30):
    """Return a list of per-letter boolean masks (crop coordinates)."""
    mask = cob > 0.5
    holes = ndi.binary_fill_holes(mask) & ~mask
    hl, nh = ndi.label(holes)
    if nh:
        sizes = ndi.sum(holes, hl, range(1, nh + 1))
        mask |= np.isin(hl, np.where(sizes < max_hole)[0] + 1)
    lab, n = ndi.label(mask)
    out = []
    for i, sl in enumerate(ndi.find_objects(lab), start=1):
        m = lab == i
        area = int(m.sum())
        if area < min_speck:
            continue
        is_or = sl[1].start + CROP[0] >= OR_MIN_X
        if keep == "no_or" and is_or:
            continue
        out.append(m)
    return out


def region_sdf(m, cob, others, method):
    d_in = ndi.distance_transform_edt(m)
    d_out = ndi.distance_transform_edt(~m)
    sdf = np.where(m, d_in - 0.5, -(d_out - 0.5))
    if method == "subpixel":
        ring = ndi.binary_dilation(m) & ~ndi.binary_erosion(m) & ~others
        sdf[ring] = cob[ring] - 0.5
        sdf = ndi.gaussian_filter(sdf, 0.35)
    else:
        sdf = ndi.gaussian_filter(sdf, 0.9)
    return sdf


def build_sdf(keep="no_or", method="subpixel"):
    crop, bg, ink = load_source()
    cob = coverage(crop, bg, ink)
    comps = clean_components(cob, keep=keep)
    union = np.zeros_like(comps[0])
    for m in comps:
        union |= m
    sdf = np.full(cob.shape, -1e3)
    for m in comps:
        others = union & ~m
        near = ndi.binary_dilation(m, iterations=3)
        cob_i = np.where(near & ~ndi.binary_dilation(others, iterations=1), cob, 0.0)
        sdf = np.maximum(sdf, region_sdf(m, cob_i, others, method))
    return sdf.astype(np.float64), union, cob


def ink_bbox(mask):
    ys, xs = np.where(mask)
    return float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)


def render_alpha(sdf, origin, scale, out_w, out_h, ss=4):
    """Alpha (0..1) of an out_w x out_h image whose pixel (0,0) top-left corner sits at the crop
    point `origin` (x, y), with `scale` output px per source px. Supersampled ss x ss with point
    samples of the (bilinear) SDF, then box-averaged: true area coverage at any size."""
    ox, oy = origin
    n = ss
    xs = (np.arange(out_w * n) + 0.5) / n / scale + ox - 0.5
    ys = (np.arange(out_h * n) + 0.5) / n / scale + oy - 0.5
    gy, gx = np.meshgrid(ys, xs, indexing="ij")
    d = ndi.map_coordinates(sdf, [gy, gx], order=1, mode="constant", cval=-1e3)
    # 1 output px of antialiasing per sub-sample cell: distances in sub-sample px
    a = np.clip(d * scale * n + 0.5, 0.0, 1.0)
    return a.reshape(out_h, n, out_w, n).mean(axis=(1, 3))


def to_rgba(alpha, hex_colour):
    h = hex_colour.lstrip("#")
    rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    out = np.zeros(alpha.shape + (4,), np.uint8)
    out[..., 0], out[..., 1], out[..., 2] = rgb
    out[..., 3] = np.round(np.clip(alpha, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def holes_count(mask):
    filled = ndi.binary_fill_holes(mask)
    _, n = ndi.label(filled & ~mask)
    return int(n)
