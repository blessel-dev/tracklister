"""Brand assets (tokens, logos, wordmark, icon, fonts, textures). Owner: BRAND branch.

SPDX-License-Identifier: GPL-3.0-or-later (code); fonts are OFL-1.1 (see fonts/OFL-*.txt).

Contract used by the GUI:
    asset_path("tokens.json") -> Path   works from source and from the PyInstaller bundle
    load_tokens() -> dict               parsed tokens.json
"""
from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path


def assets_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "tracklister" / "assets"
    return Path(__file__).resolve().parent


def asset_path(relative: str) -> Path:
    return assets_dir() / relative


@lru_cache(maxsize=1)
def load_tokens() -> dict:
    with open(asset_path("tokens.json"), encoding="utf-8") as f:
        return json.load(f)
