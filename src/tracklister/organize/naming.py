"""Final file names in tracklist order: 'NN - Artista - Titulo (Version).ext', Windows-safe.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

NN always comes from TrackRow.pos (the row index), never from download order.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from tracklister.core.model import TrackRow
from tracklister.core.textnorm import nfc

MAX_NAME = 180
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.[^.]*)?$", re.IGNORECASE)


def pad_width(n_rows: int) -> int:
    return 3 if n_rows > 99 else 2


def safe_component(s: str | None, max_len: int = 150, *, reserved: bool = True) -> str:
    """One path component: NFC, reserved characters and control chars -> space, no trailing
    dots/spaces, Windows device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9) prefixed with '_'."""
    s = _INVALID.sub(" ", nfc(s))
    s = re.sub(r"\s+", " ", s).strip().rstrip(". ").lstrip()
    if not s:
        s = "_"
    if reserved and _RESERVED.match(s):
        s = "_" + s
    if len(s) > max_len:
        s = s[:max_len].rstrip(". ") or "_"
    return s


def track_filename(row: TrackRow, ext: str, width: int) -> str:
    ext = (ext or "").lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    num = f"{int(row.pos):0{width}d}"
    artist = safe_component(row.artist_display or row.search_artist, reserved=False) if \
        (row.artist_display or row.search_artist) else ""
    title = safe_component(row.title, reserved=False) if row.title else ""
    version = safe_component(row.version, reserved=False) if row.version else ""

    def build(a: str, t: str) -> str:
        head = f"{num} - {a} - " if a else f"{num} - "
        return f"{head}{t}{f' ({version})' if version else ''}{ext}"

    name = build(artist, title or "_")
    if len(name) > MAX_NAME:     # title first, then the artist
        keep = max(10, len(title) - (len(name) - MAX_NAME))
        title = title[:keep].rstrip(". ")
        name = build(artist, title)
    if len(name) > MAX_NAME:
        keep = max(10, len(artist) - (len(name) - MAX_NAME))
        artist = artist[:keep].rstrip(". ")
        name = build(artist, title)
    if len(name) > MAX_NAME:
        stem_max = MAX_NAME - len(ext)
        name = name[: len(name) - len(ext)][:stem_max].rstrip(". ") + ext
    return name


def win_long(path: Path | str) -> str:
    """Absolute path, with the \\\\?\\ prefix when it is long enough to hit MAX_PATH."""
    p = os.path.abspath(str(path))
    if os.name != "nt" or p.startswith("\\\\?\\") or len(p) < 240:
        return p
    if p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + p[2:]
    return "\\\\?\\" + p


def unique_path(dst: Path) -> Path:
    """dst, or 'name (2).ext', 'name (3).ext'... whichever does not exist yet."""
    dst = Path(dst)
    if not os.path.lexists(win_long(dst)):
        return dst
    stem, suf = dst.stem, dst.suffix
    m = re.match(r"^(.*) \((\d+)\)$", stem)
    base = m.group(1) if m else stem
    n = int(m.group(2)) + 1 if m else 2
    while True:
        cand = dst.with_name(f"{base} ({n}){suf}")
        if not os.path.lexists(win_long(cand)):
            return cand
        n += 1
