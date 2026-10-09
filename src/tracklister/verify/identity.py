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
    VERSION_KW, classify_version, nfc, norm_key, split_artists, split_title_version, version_is_original,
    versions_compatible,
)
from tracklister.verify.audioinfo import AudioInfo

# "01 - ", "01. ", "01_", "(01) ", "01) " -- a number followed by a SEPARATOR. "808 State" stays.
_LEADING_NUM = re.compile(r"^\s*\(?\d{1,3}\)?\s*[.\-_)]+\s*(?=\S)|^\s*\(\d{1,3}\)\s+(?=\S)")
_SCENE_GROUP = re.compile(r"(?<=[A-Za-z0-9)\]])-([A-Za-z0-9]{2,8})$")
_DASH = re.compile(r"\s+[-\u2013\u2014]\s+")
# A title with other numbers ("Dust 1" / "Dust 2", "Untitled 1" / "Untitled 2", "A1" / "B2") is another
# track, however close the rest of the text is: its score is capped well below every acceptance threshold.
NUMBER_MISMATCH_MAX = 50.0
# Two artist names are the same artist only when they match word by word, not just in most letters
# (audit round 3, B1): 'Adam Beyer' / 'Adam Port' (63 %), 'Chris Liebing' / 'Chris Lake' (70 %) and
# 'Len Faki' / 'Ken Faki' (88 %) are other artists. A whole-name similarity under SAME_ARTIST_MIN is
# never the same artist either.
SAME_ARTIST_MIN = 85.0
TOKEN_MIN = 85.0          # a word of 5+ letters may differ by a typo ('Liebing' / 'Leibing')
SHORT_TOKEN = 4           # words of up to 4 letters must be equal ('Len' / 'Ken', 'Duff' / 'Duffy')


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
    same_artist: bool = True      # False: a different artist, even with a similar name (round 3, B1)
    title_words_ok: bool = True   # False: a word more or less in the title ('Feel It All'): another track (round 4, B2)


@dataclass(frozen=True)
class ArtistMatch:
    score: float                  # 0-100, best whole-name similarity
    same: bool                    # the names match word by word: the same artist


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
    """(0-100 score, same numbers) of two BASE titles (no version). Different numbers, or titles that
    do not have the same words (title_words_match: 'Feel It' / 'Feel It All'), cap the score at
    NUMBER_MISMATCH_MAX."""
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
    score, same = max(out, key=lambda x: x[0])
    if not title_words_match(wanted, got_base):
        score = min(score, NUMBER_MISMATCH_MAX)
    return score, same


_TITLE_SKIP = frozenset({"and"})          # 'Rock & Roll' / 'Rock and Roll' (norm_key already drops '&')
_TITLE_ALIAS = {"pt": "part"}             # 'Pt. 2' / 'Part 2'


def _title_words(key: str) -> list[str]:
    return [re.sub(r"\d+", lambda m: str(int(m.group())), _TITLE_ALIAS.get(w, w))     # '01' is '1'
            for w in key.split() if w not in _TITLE_SKIP]


def _same_title_words(a: list[str], b: list[str]) -> bool:
    """One to one: every word of each title has its own partner in the other, with the word rule of
    the artists (_word_close: equal, or a typo in a word of 5+ letters). Equal words pair first, so a
    typo never takes another word's partner."""
    if len(a) != len(b):
        return False
    pool, rest = list(b), []
    for w in a:
        if w in pool:
            pool.remove(w)
        else:
            rest.append(w)
    for w in rest:
        hit = next((p for p in pool if _word_close(w, p)), None)
        if hit is None:
            return False
        pool.remove(hit)
    return True


def title_words_match(wanted: str | None, got_base: str | None) -> bool:
    """Do two BASE titles (no version) have the same words? Audit round 4, B2: 'Feel It' / 'Feel It All'
    (78 %), 'Higher' / 'Higher Love' (71 %), 'Feel It' / 'Feel Me' and 'Sin' / 'Original Sin' were
    close enough to pass, and Sockseek's --strict-title lets such files through (the wanted title is
    a whole-word part of theirs). No word may be missing or extra; 'original' counts as a word here
    (split_title_version already took '(Original Mix)' and its kind away). 'and' is ignored, 'pt' is
    'part', '01' is '1', titles equal without their spaces are the same ('Dont Stop' / 'Don t Stop'),
    and a track number glued to the file's name is tried away ('01 Feel It')."""
    a, b = norm_key(wanted, drop_original=False), norm_key(got_base, drop_original=False)
    if not a or not b:
        return True
    wa = _title_words(a)
    for c in (b, _without_track_number(b)):
        if not c:
            continue
        wc = _title_words(c)
        if a.replace(" ", "") == c.replace(" ", "") or "".join(wa) == "".join(wc) or _same_title_words(wa, wc):
            return True
    return False


def _artist_keys(names: Iterable[str | None]) -> set[str]:
    """Each name, its ' - ' parts (a folder 'Artist - Album') and its single artists ('A & B', 'A feat. B')."""
    keys: set[str] = set()
    for name in names:
        for seg in [name or ""] + _DASH.split(nfc(name)):
            keys.add(norm_key(seg))
            keys.update(norm_key(p) for p in split_artists(seg))
    keys.discard("")
    return keys


def _fold(word: str) -> str:
    """German transliterations: 'vaeth' -> 'vath', like 'Väth' once its accent is gone."""
    return word.replace("ae", "a").replace("oe", "o").replace("ue", "u")


def _word_close(a: str, b: str) -> bool:
    """Two words of norm_key() texts: equal (also as 'ae'/'a'), or, for words of 5+ letters with the
    same digits, a typo away (ratio >= TOKEN_MIN). Short words must be equal: 'len' is not 'ken'."""
    if a == b or _fold(a) == _fold(b):
        return True
    if min(len(a), len(b)) <= SHORT_TOKEN:
        return False
    if re.sub(r"\D", "", a) != re.sub(r"\D", "", b):
        return False
    return fuzz.ratio(a, b) >= TOKEN_MIN


def _same_words(w: str, g: str) -> bool:
    """Word-by-word rule of two single-artist keys: every word of the shorter name has its own close
    word in the other one, the surname included. A shorter name of 1 word must be the whole other
    name ('Systems' is not 'Planetary Assault Systems'); 'DVS 1' / 'DVS1' are the same."""
    if w.replace(" ", "") == g.replace(" ", ""):
        return True
    tw, tg = w.split(), g.split()
    short, other = (tw, tg) if len(tw) <= len(tg) else (tg, tw)
    if len(short) < len(other) and len(short) < 2:
        return False
    pool = list(other)
    for word in short:
        hit = next((p for p in pool if _word_close(word, p)), None)
        if hit is None:
            return False
        pool.remove(hit)
    return True


def _artist_pair(w: str, g: str) -> ArtistMatch:
    if w.replace(" ", "") == g.replace(" ", ""):
        return ArtistMatch(100.0, True)
    s = float(fuzz.ratio(w, g))
    if min(len(w.split()), len(g.split())) >= 2:
        s = max(s, float(fuzz.token_set_ratio(w, g)))
    return ArtistMatch(s, s >= SAME_ARTIST_MIN and _same_words(w, g))


def better_artist(a: ArtistMatch, b: ArtistMatch) -> ArtistMatch:
    """A same-artist match always wins over a merely similar name; then the higher score."""
    return max(a, b, key=lambda m: (m.same, m.score))


def artist_match(wanted: Iterable[str | None], got: str | None) -> ArtistMatch:
    """Best match between the row's artists and the file's, artist by artist.

    The same artist needs the names to match word by word (round 3, B1): 'Adam Port' is not 'Adam
    Beyer' and 'Ken Faki' is not 'Len Faki', even with similar letters; case, accents, 'Ø'/'O',
    'A & B'/'B & A' and an extra co-artist or label ('Roll Dann & Laster Records') do not matter.
    A partial or subset match ('Planetary Assault Systems' / 'Systems') only counts when the shorter
    name has 2 words or more. 'Fjaak' against a tag 'Fjaak, Chris Liebing' is 100 (exact on one of
    the split artists)."""
    best = ArtistMatch(0.0, False)
    gots = _artist_keys([got])
    gots |= {k for k in map(_without_track_number, gots) if k}     # '01 Fjaak - Spirit.mp3' -> 'fjaak'
    for w in _artist_keys(wanted):
        for g in gots:
            best = better_artist(best, _artist_pair(w, g))
    return best


def artist_similarity(wanted: Iterable[str | None], got: str | None) -> float:
    """0-100 score of artist_match() (whether it is the same artist is in artist_match().same)."""
    return artist_match(wanted, got).score


def strip_track_number(stem: str) -> str:
    """'01 - Artist - Title' / '01. Title' / '01_Title' -> without the number; never '808 State'."""
    m = _LEADING_NUM.match(stem)
    s = stem[m.end():] if m else stem
    return re.sub(r"\s+", " ", s.replace("_", " ")).strip()


def _drop_scene_group(stem: str) -> str:
    """'plug_trax_-_zoned_out-psy' -> 'plug_trax_-_zoned_out': a scene-style name (underscores for
    spaces) ends with its release group glued by a hyphen. It is not a word of the title, which now
    must match word by word (audit round 4, B2). A version word ('-remix', '-live', '-radio') stays."""
    if "_" not in stem or " " in stem:
        return stem
    m = _SCENE_GROUP.search(stem)
    if not m or not re.search(r"[A-Za-z]", m.group(1)) or VERSION_KW.search(m.group(1)) \
            or classify_version(m.group(1)) != VersionKind.OTHER:
        return stem
    return stem[:m.start()]


def parse_name(file_name: str, parent: str | None) -> tuple[str, str]:
    """(artist, title-with-version) guessed from 'NN - Artist - Title (Mix).ext' + parent folder."""
    stem = Path(file_name).stem if "." in file_name else file_name
    stem = strip_track_number(_drop_scene_group(nfc(stem)))
    parts = re.split(r"\s+[-\u2013\u2014]\s+", stem, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return parts[0].strip(), parts[1].strip()
    return nfc(parent or ""), stem.strip()


def row_artists(row: TrackRow) -> list[str]:
    return [row.artist_display] + list(row.artists or [])


def _version_ok(wanted: str | None, got_versions: list[str]) -> tuple[bool, str]:
    if not got_versions:
        return versions_compatible(wanted, None)
    results = [versions_compatible(wanted, v) for v in got_versions]
    if version_is_original(wanted):
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
    artist = artist_match(row_artists(row), got_artist)
    # an artist folder with the artist's name helps when the name has no "Artist - " part
    if parent and "nombre" in used:
        artist = better_artist(artist, artist_match(row_artists(row), parent))
    title, numbers_ok = title_similarity(row.title, got_base or got_title_full)
    words_ok = title_words_match(row.title, got_base or got_title_full)
    ok, reason = _version_ok(row.version, versions)
    evidence = "tags+nombre" if used == {"tags", "nombre"} else ("tags" if used == {"tags"} else "nombre")
    return IdentityScore(round(artist.score, 1), round(title, 1), ok, reason, evidence, got_artist, got_title_full,
                         got_version or name_version, numbers_ok, artist.same, words_ok)
