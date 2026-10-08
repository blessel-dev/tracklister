"""Build src/tracklister/assets/tokens.json and copy the OFL fonts.

SPDX-License-Identifier: GPL-3.0-or-later

Palette rationale (see construccion/identidad-visual.md):
- Hormigon: the logo's own flat grey (#afafaf, measured in marca/work/medidas.json) as the
  window background, lighter concrete greys for the work surfaces, near-black ink (#161616,
  the logo ink is #1c1c1c).
- Noche: near-black surfaces, warm off-white ink; the concrete texture only in the header.
- One muted accent: the blue-grey of the wall lamp in his Mixcloud cover (median #3d697e),
  the only colour in that photo. MavelPoint's acid green #c8f542 is NOT his colour.
- States are desaturated hues solved for contrast (body-text grade, >= 4.5:1, against bg,
  surface and surface_alt; >= 3:1 against the selection colour). They always ship with an
  icon and a label; colour is never the only signal.
"""
from __future__ import annotations

import shutil
import sys

from common import ASSETS, FONT_SRC, contrast, solve_lightness, write_json

STATE_ORDER = ["pendiente", "en_curso", "verificado", "dudoso", "no_encontrado",
               "no_cumple_formato", "fallida", "ya_en_biblioteca", "omitida"]
STATE_LABELS = {
    "verificado": "Verificado", "dudoso": "Dudoso", "no_encontrado": "No encontrado",
    "ya_en_biblioteca": "Ya en biblioteca", "en_curso": "En curso", "pendiente": "Pendiente",
    "no_cumple_formato": "No cumple formato", "fallida": "Fallida", "omitida": "Omitida",
}
# hue (deg), HLS saturation. Neutral states use saturation 0.
STATE_HUES = {
    "pendiente": (0, 0.0),
    "en_curso": (199, 0.34),          # accent hue
    "verificado": (140, 0.24),        # sage
    "dudoso": (40, 0.42),             # ochre
    "no_encontrado": (14, 0.30),      # brick
    "no_cumple_formato": (318, 0.18), # plum
    "fallida": (356, 0.42),           # red
    "ya_en_biblioteca": (222, 0.24),  # slate
    "omitida": (30, 0.04),            # warm grey
}
ACCENT_HUE = (199, 0.34)

BASE = {
    "hormigon": {
        "label_es": "Hormigon",
        "darker": True,
        "colors": {
            "bg": "#afafaf", "surface": "#cdcdcb", "surface_alt": "#c3c3c1",
            "ink": "#161616", "ink_muted": "#383838",
            "line": "#959593", "line_strong": "#1c1c1c",
            "selection": "#a9bcc4", "on_selection": "#111111",
            "disabled_ink": "#7a7a78", "on_accent": "#f2f2f0",
        },
        "start_l": 0.42,
        "logo": "logo/blessel-ink.png", "logo_2x": "logo/blessel-ink@2x.png",
        "lockup": "lockup/header-ink.png", "lockup_2x": "lockup/header-ink@2x.png",
        "wordmark": "wordmark/tracklister-ink.png", "wordmark_2x": "wordmark/tracklister-ink@2x.png",
        "header_texture": "textures/header-hormigon.jpg",
    },
    "noche": {
        "label_es": "Noche",
        "darker": False,
        "colors": {
            "bg": "#111111", "surface": "#1a1a1a", "surface_alt": "#222222",
            "ink": "#e6e6e3", "ink_muted": "#a3a3a0",
            "line": "#383838", "line_strong": "#afafaf",
            "selection": "#2b3a41", "on_selection": "#f0f0ee",
            "disabled_ink": "#5e5e5c", "on_accent": "#0e0e0e",
        },
        "start_l": 0.45,
        "logo": "logo/blessel-light.png", "logo_2x": "logo/blessel-light@2x.png",
        "lockup": "lockup/header-light.png", "lockup_2x": "lockup/header-light@2x.png",
        "wordmark": "wordmark/tracklister-light.png", "wordmark_2x": "wordmark/tracklister-light@2x.png",
        "header_texture": "textures/header-noche.jpg",
    },
}

FONTS = {
    "inter": ["Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf"],
    "jetbrainsmono": ["JetBrainsMono-Regular.ttf", "JetBrainsMono-Medium.ttf"],
}
LICENCES = {"inter": ("LICENSE.txt", "OFL-Inter.txt"), "jetbrainsmono": ("OFL.txt", "OFL-JetBrainsMono.txt")}

# Thresholds checked here and again in tests/brand/test_assets.py
TEXT_MIN = 4.5
LARGE_MIN = 3.0


def build_theme(name: str, spec: dict) -> dict:
    c = dict(spec["colors"])
    darker = spec["darker"]
    text_bgs = [(c["bg"], TEXT_MIN + 0.05), (c["surface"], TEXT_MIN + 0.05),
                (c["surface_alt"], TEXT_MIN + 0.05)]
    c["accent"] = solve_lightness(*ACCENT_HUE, against=text_bgs + [(c["on_accent"], TEXT_MIN + 0.05)],
                                  darker=darker, start_l=spec["start_l"])
    c["focus"] = c["accent"]
    for st in STATE_ORDER:
        h, s = STATE_HUES[st]
        c[f"state_{st}"] = solve_lightness(h, s, against=text_bgs + [(c["selection"], LARGE_MIN + 0.05)],
                                           darker=darker, start_l=spec["start_l"])
    pairs = {
        "ink/bg": ("ink", "bg"), "ink/surface": ("ink", "surface"), "ink/surface_alt": ("ink", "surface_alt"),
        "ink_muted/bg": ("ink_muted", "bg"), "ink_muted/surface": ("ink_muted", "surface"),
        "ink_muted/surface_alt": ("ink_muted", "surface_alt"),
        "on_accent/accent": ("on_accent", "accent"), "accent/bg": ("accent", "bg"),
        "accent/surface": ("accent", "surface"), "on_selection/selection": ("on_selection", "selection"),
        "line_strong/bg": ("line_strong", "bg"), "line_strong/surface": ("line_strong", "surface"),
        "focus/bg": ("focus", "bg"), "focus/surface": ("focus", "surface"),
        "disabled_ink/surface": ("disabled_ink", "surface"),
    }
    con = {k: round(contrast(c[a], c[b]), 2) for k, (a, b) in pairs.items()}
    worst_bg = 99.0
    for st in STATE_ORDER:
        for bgk in ("bg", "surface", "surface_alt", "selection"):
            v = round(contrast(c[f"state_{st}"], c[bgk]), 2)
            con[f"state_{st}/{bgk}"] = v
        worst_bg = min(worst_bg, con[f"state_{st}/bg"], con[f"state_{st}/surface"])
    con["state_*/bg"] = worst_bg
    out = {"label_es": spec["label_es"], "colors": c}
    for k in ("logo", "logo_2x", "lockup", "lockup_2x", "wordmark", "wordmark_2x", "header_texture"):
        out[k] = spec[k]
    out["contrast"] = con
    return out


def check(theme: dict, name: str) -> list[str]:
    errs = []
    con = theme["contrast"]
    for k, v in con.items():
        if k.startswith("disabled_ink"):
            continue
        need = LARGE_MIN if (k.startswith("line_strong") or k.startswith("focus")
                             or k.endswith("/selection") and k.startswith("state_")) else TEXT_MIN
        if v < need:
            errs.append(f"{name}: {k} = {v} < {need}")
    return errs


def copy_fonts() -> None:
    dst = ASSETS / "fonts"
    dst.mkdir(parents=True, exist_ok=True)
    for fam, files in FONTS.items():
        for f in files:
            shutil.copyfile(FONT_SRC / fam / f, dst / f)
        lic_src, lic_dst = LICENCES[fam]
        shutil.copyfile(FONT_SRC / fam / lic_src, dst / lic_dst)


def main() -> int:
    themes = {name: build_theme(name, spec) for name, spec in BASE.items()}
    errs = [e for n, t in themes.items() for e in check(t, n)]
    if errs:
        print("\n".join(errs))
        return 1
    tokens = {
        "schema": "tracklister.tokens/1",
        "default_theme": "hormigon",
        "fonts": {
            "ui": {"family": "Inter", "files": [f"fonts/{f}" for f in FONTS["inter"]],
                   "licence": "fonts/OFL-Inter.txt"},
            "mono": {"family": "JetBrains Mono", "files": [f"fonts/{f}" for f in FONTS["jetbrainsmono"]],
                     "licence": "fonts/OFL-JetBrainsMono.txt"},
        },
        "type_scale_px": {"xs": 11, "sm": 12, "base": 13, "md": 15, "lg": 18, "xl": 24, "xxl": 32},
        "spacing_px": [0, 4, 8, 12, 16, 24, 32, 48],
        "radius_px": 0, "border_px": 1, "border_strong_px": 2,
        "themes": themes,
        "states": {st: {"label_es": STATE_LABELS[st], "icon": f"icons/state-{st}.svg"}
                   for st in ["verificado", "dudoso", "no_encontrado", "ya_en_biblioteca", "en_curso",
                              "pendiente", "no_cumple_formato", "fallida", "omitida"]},
        "ui_icons": {n: f"icons/ui-{n}.svg" for n in
                     ["abrir", "copiar", "reintentar", "ajustes", "pegar", "enlace", "carpeta",
                      "deshacer", "diagnostico"]},
        "app_icon": "icon/tracklister.ico",
        "app_icon_concept": "monograma-t",
    }
    write_json(ASSETS / "tokens.json", tokens)
    copy_fonts()
    for n, t in themes.items():
        print(n, {k: v for k, v in t["colors"].items() if k.startswith(("accent", "state_"))})
        print(n, "min state/bg|surface", t["contrast"]["state_*/bg"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
