"""Tools that ship inside the app: the yt-dlp pin per platform, and where the frozen app keeps its data.

Owner: platform layer (1.1, macOS).
SPDX-License-Identifier: GPL-3.0-or-later

YTDLP_PINS is the single source of the yt-dlp pin: packaging/fetch_ytdlp.py downloads and checks the
release asset `asset_name`, the build puts it in the bundle under that name, and the app copies it to
<tools_dir>/<exe_name> and only ever runs that copy (gui.services.Services.ensure_ytdlp).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from tracklister.core import osplatform


@dataclass(frozen=True)
class YtdlpPin:
    version: str      # the yt-dlp release tag
    asset_name: str   # the upstream release asset, and the file name inside the bundle
    sha256: str       # GitHub Releases API digest, cross-checked with the release's SHA2-256SUMS
    size: int         # bytes
    exe_name: str     # the per-user copy the app runs (<tools_dir>/<exe_name>)


YTDLP_PINS: dict[str, YtdlpPin] = {
    osplatform.WINDOWS: YtdlpPin("2026.08.19", "yt-dlp.exe",
                                 "66674953fe251b89f4d08c5f0e35e0728679bd67ab3d7d05c0562af101dd3e7a", 17840399,
                                 "yt-dlp.exe"),
    # universal2, ad-hoc signed upstream (report 3.4); the app runs its copy, so no quarantine reaches it
    osplatform.MACOS: YtdlpPin("2026.08.19", "yt-dlp_macos",
                               "0f192b7ec147ab6288885d6351d9ab67367640029b4377576ef46dd79cf7b202", 37146048,
                               "yt-dlp"),
}


def ytdlp_pin(platform: str | None = None) -> YtdlpPin:
    """The pin of `platform` (default: the current one): darwin's on macOS, the Windows one anywhere else."""
    p = osplatform.current() if platform is None else platform
    return YTDLP_PINS[osplatform.MACOS] if p == osplatform.MACOS else YTDLP_PINS[osplatform.WINDOWS]


def bundled_dir() -> Path | None:
    """Folder of the frozen app's bundled data (PyInstaller); None when running from source.

    Windows: the folder of Tracklister.exe. macOS: Tracklister.app/Contents/Resources (the executable is
    Contents/MacOS/Tracklister, and a signed bundle keeps its data in Resources, not next to it)."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    if osplatform.is_macos():
        return exe.parents[1] / "Resources"
    return exe.parent
