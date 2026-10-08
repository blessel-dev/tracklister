"""Is this file the row's song? Artist/title fuzzy scores and the version rule.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Tags first; a missing or generic tag field falls back to the file name and its parent folder
(the Soulseek path tail). Normalisation and the version rule come from core.textnorm only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from rapidfuzz import fuzz

from tracklister.core.model import TrackRow, VersionKind
from tracklister.core.textnorm import classify_version, nfc, norm_key, split_title_version, versions_compatible
from tracklister.verify.audioinfo import AudioInfo

# "01 - ", "01. ", "01_", "(01) ", "01) " -- a number followed by a SEPARATOR. "808 State" stays.
_LEADING_NUM = re.compile(r"^\s*\(?\d{1,3}\)?\s*[.\-_)]+\s*(?=\S)|^\s*\(\d{1,3}\)\s+(?=\S)")
_FULL = (VersionKind.ORIGINAL, VersionKind.EXTENDED)


@dataclass(frozen=True)
class IdentityScore:
    artist: float
    title: float
    version_ok: bool
    version_reason_es: str
    evidence: str                 # "tags" | "nombre" | "tags+nombre"
    got_artist: str = ""
    got_title: str = ""
    got_version: str | None = None


def strip_track_number(stem: str) -> str:
    """'01 - Artist - Title' / '01. Title' / '01_Title' -> without the number; never '808 State'."""
    m = _LEADING_NUM.match(stem)
    s = stem[m.end():] if m else stem
    return re.sub(r"\s+", " ", s.replace("_", " ")).strip()


def parse_name(file_name: str, parent: str | None) -> tuple[str, str]:
    """(artist, title-with-version) guessed from 'NN - Artist - Title (Mix).ext' + parent folder."""
    stem = Path(file_name).stem if "." in file_name else file_name
    stem = strip_track_number(nfc(stem))
    parts = re.split(r"\s+[-\u2013\u2014]\s+", stem, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return parts[0].strip(), parts[1].strip()
    return nfc(parent or ""), stem.strip()


def _artist_score(row: TrackRow, got: str) -> float:
    g = norm_key(got)
    if not g:
        return 0.0
    cands = [row.artist_display] + list(row.artists or [])
    best = 0.0
    for c in cands:
        k = norm_key(c)
        if k:
            best = max(best, float(fuzz.token_set_ratio(k, g)), float(fuzz.ratio(k, g)))
    return best


def _title_score(row: TrackRow, got_base: str) -> float:
    a, b = norm_key(row.title), norm_key(got_base)
    if not a or not b:
        return 0.0
    return max(float(fuzz.ratio(a, b)), float(fuzz.token_sort_ratio(a, b)))


def _version_ok(wanted: str | None, got_versions: list[str]) -> tuple[bool, str]:
    wk = classify_version(wanted)
    if not got_versions:
        return versions_compatible(wanted, None)
    results = [versions_compatible(wanted, v) for v in got_versions]
    if wk in _FULL:
        bad = [r for r in results if not r[0]]
        return (False, bad[0][1]) if bad else results[0]
    good = [r for r in results if r[0]]
    return good[0] if good else results[0]


def identity_score(row: TrackRow, info: AudioInfo, source_path_tail: str | None) -> IdentityScore:
    tail_parts = [p for p in PureWindowsPath(source_path_tail.replace("/", "\\")).parts] if source_path_tail else []
    file_name = tail_parts[-1] if tail_parts else info.path.name
    parent = tail_parts[-2] if len(tail_parts) >= 2 else None
    name_artist, name_title = parse_name(file_name, parent)
    used: set[str] = set()
    got_artist = info.tag_artist or ""
    if got_artist:
        used.add("tags")
    else:
        got_artist = name_artist
        used.add("nombre")
    got_title_full = info.tag_title or ""
    if got_title_full:
        used.add("tags")
    else:
        got_title_full = name_title
        used.add("nombre")
    got_base, got_version = split_title_version(got_title_full)
    # the version can also be written only in the file name: both sources count
    _, name_version = split_title_version(name_title)
    versions = [v for v in (got_version, name_version) if v]
    artist = _artist_score(row, got_artist)
    # an artist folder with the artist's name helps when the name has no "Artist - " part
    if parent and "nombre" in used:
        artist = max(artist, _artist_score(row, parent))
    title = _title_score(row, got_base or got_title_full)
    ok, reason = _version_ok(row.version, versions)
    evidence = "tags+nombre" if used == {"tags", "nombre"} else ("tags" if used == {"tags"} else "nombre")
    return IdentityScore(round(artist, 1), round(title, 1), ok, reason, evidence, got_artist, got_title_full,
                         got_version or name_version)
