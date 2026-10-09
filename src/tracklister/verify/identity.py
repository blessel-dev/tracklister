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
from typing import Iterable

from rapidfuzz import fuzz

from tracklister.core.model import TrackRow, VersionKind
from tracklister.core.textnorm import (
    classify_version, nfc, norm_key, split_artists, split_title_version, versions_compatible,
)
from tracklister.verify.audioinfo import AudioInfo

# "01 - ", "01. ", "01_", "(01) ", "01) " -- a number followed by a SEPARATOR. "808 State" stays.
_LEADING_NUM = re.compile(r"^\s*\(?\d{1,3}\)?\s*[.\-_)]+\s*(?=\S)|^\s*\(\d{1,3}\)\s+(?=\S)")
_DASH = re.compile(r"\s+[-\u2013\u2014]\s+")
_FULL = (VersionKind.ORIGINAL, VersionKind.EXTENDED)
# A title with other numbers ("Dust 1" / "Dust 2", "Untitled 1" / "Untitled 2", "A1" / "B2") is another
# track, however close the rest of the text is: its score is capped well below every acceptance threshold.
NUMBER_MISMATCH_MAX = 50.0


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
    numbers_ok: bool = True       # False: the titles carry different numbers (another track)


def number_tokens(key: str) -> list[str]:
    """The tokens of a norm_key() text that carry a digit, leading zeros dropped, sorted:
    'dust 01' -> ['1'], 'a1' -> ['a1'], 'part 2 of 3' -> ['2', '3']."""
    return sorted(re.sub(r"\d+", lambda m: str(int(m.group())), t) for t in key.split()
                  if any(c.isdigit() for c in t))


def _without_track_number(key: str) -> str | None:
    """'01 spirit' -> 'spirit': a leading 1-2 digit token of the FILE's text is read as a track number
    glued to the name ('01 Artist - Title.mp3', '01 Title.flac'). '808 State' keeps its 3 digits."""
    toks = key.split()
    if len(toks) >= 2 and len(toks[0]) <= 2 and toks[0].isdigit():
        return " ".join(toks[1:])
    return None


def title_similarity(wanted: str | None, got_base: str | None) -> tuple[float, bool]:
    """(0-100 score, same numbers) of two BASE titles (no version). Different numbers cap the score
    at NUMBER_MISMATCH_MAX."""
    a, b = norm_key(wanted), norm_key(got_base)
    if not a or not b:
        return 0.0, True
    out: list[tuple[float, bool]] = []
    for c in (b, _without_track_number(b)):
        if not c:
            continue
        score = max(float(fuzz.ratio(a, c)), float(fuzz.token_sort_ratio(a, c)))
        same = number_tokens(a) == number_tokens(c)
        out.append((score if same else min(score, NUMBER_MISMATCH_MAX), same))
    return max(out, key=lambda x: x[0])


def _artist_keys(names: Iterable[str | None]) -> set[str]:
    """Each name, its ' - ' parts (a folder 'Artist - Album') and its single artists ('A & B', 'A feat. B')."""
    keys: set[str] = set()
    for name in names:
        for seg in [name or ""] + _DASH.split(nfc(name)):
            keys.add(norm_key(seg))
            keys.update(norm_key(p) for p in split_artists(seg))
    keys.discard("")
    return keys


def artist_similarity(wanted: Iterable[str | None], got: str | None) -> float:
    """Best 0-100 match between the row's artists and the file's, artist by artist.

    A partial or subset match ('Planetary Assault Systems' / 'Systems') only counts when the shorter
    name has 2 words or more; otherwise the plain ratio decides. 'Fjaak' against a tag
    'Fjaak, Chris Liebing' still scores 100 (exact on one of the split artists)."""
    best = 0.0
    gots = _artist_keys([got])
    gots |= {k for k in map(_without_track_number, gots) if k}     # '01 Fjaak - Spirit.mp3' -> 'fjaak'
    for w in _artist_keys(wanted):
        for g in gots:
            s = float(fuzz.ratio(w, g))
            if min(len(w.split()), len(g.split())) >= 2:
                s = max(s, float(fuzz.token_set_ratio(w, g)))
            best = max(best, s)
    return best


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


def row_artists(row: TrackRow) -> list[str]:
    return [row.artist_display] + list(row.artists or [])


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
    artist = artist_similarity(row_artists(row), got_artist)
    # an artist folder with the artist's name helps when the name has no "Artist - " part
    if parent and "nombre" in used:
        artist = max(artist, artist_similarity(row_artists(row), parent))
    title, numbers_ok = title_similarity(row.title, got_base or got_title_full)
    ok, reason = _version_ok(row.version, versions)
    evidence = "tags+nombre" if used == {"tags", "nombre"} else ("tags" if used == {"tags"} else "nombre")
    return IdentityScore(round(artist, 1), round(title, 1), ok, reason, evidence, got_artist, got_title_full,
                         got_version or name_version, numbers_ok)
