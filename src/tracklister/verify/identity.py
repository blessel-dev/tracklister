"""Is this file the row's song? Artist/title fuzzy scores and the version rule.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Tags first; a missing or generic tag field falls back to the file name and its parent folder
(the Soulseek path tail). Normalisation and the version rule come from core.textnorm only.

1.0.1 (R3, DECISIONES X): file names as Soulseek users really write them. Site watermarks are taken
out of names and tags (strip_watermarks), and a file name has one or more READINGS (name_readings):
scene names ('04-red_rooms-trip', with a hash or the folder's release group at the end), disc-track
prefixes ('1-04-'), a track number as its own ' - 06 - ' part, a BPM after a version group, an
unbalanced trailing bracket, a tight hyphen between artist and title ('Kwartz-Show me that light').
parse_name() returns the first reading (the Diagnostico judges it); identity_score() and
organize.reorder take the reading that fits the row best, judged with the SAME artist, title and
version rules as before, so every v1.0 rejection still holds ('Dust 1' / 'Dust 2', 'Feel It' /
'Feel It All', 'Adam Port' / 'Adam Beyer', the remixer...). The parent folder is artist evidence
only for the reading where the name has no artist part (plan D10).

Audit v101-1 (DECISIONES X.37): the readings after the first are guesses of where the artist ends,
so they must not move title words into the artist. Such a reading only counts when the artist part
it gives is exactly one of the row's names, word for word (reading_fits): 'Planetary Assault
Systems-Non-Stop' is never 'Planetary Assault Systems-Non' + 'Stop' for the row 'Stop' (B1), while
'x-ray_spex-oh_bondage' is still 'X-Ray Spex' + 'Oh Bondage'. And a title tag never turns the
folder into the artist of a name that says its own artist ('Adam Beyer\\Adam Port - Rush.flac'
tagged 'Rush' is Adam Port's, B2). The review of that fix (B1-R, DECISIONES X.41): every cut at a
glued hyphen or of a scene name is such a guess, the first one too, so 'Adam Beyer Space-Time.flac'
(no dash between artist and title) is never 'Adam Beyer Space' + 'Time'; a credit with a joiner word
('Fjaak & Kai-Spirit') still fits «Fjaak». The Diagnóstico applies it to its first reading.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Iterable

from rapidfuzz import fuzz

from tracklister.core.aliases import artist_aliases
from tracklister.core.model import TrackRow, VersionKind
from tracklister.core.textnorm import (
    VERSION_KW, classify_version, is_version_group, nfc, norm_key, split_artists, split_title_version,
    version_is_original, versions_compatible,
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
# Below these the file is another song (verify.verifier, rule 3). Here they only rank the readings.
ARTIST_MIN, TITLE_MIN = 60.0, 70.0

AUDIO_EXTS = frozenset({".flac", ".wav", ".wave", ".aif", ".aiff", ".aifc", ".mp3", ".m4a", ".mp4", ".aac",
                        ".alac", ".ogg", ".oga", ".opus", ".wma", ".ape", ".wv"})


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


# ---- site watermarks (R3) -----------------------------------------------------------------------------
# Only these endings make a word a web address: never a real word ('St. Germain', 'Vkn.modular', 'D.A.V.E.').
WATERMARK_TLDS = ("com", "net", "org", "ru", "info", "biz", "io", "co", "me", "fm", "to", "cc", "tv", "xyz",
                  "club", "pro", "eu", "de", "es", "uk", "pl", "top", "site", "online")
_TLD = "(?:" + "|".join(WATERMARK_TLDS) + ")"
_URL = re.compile(r"(?i)\bhttps?://[^\s()\[\]{}]+")
_WWW = re.compile(r"(?i)(?<![\w@])www\.[a-z0-9-]+(?:\.[a-z0-9-]+)+")
# a bare domain: lower case, a name of 3+ characters before the ending ('electronicfresh.com'); not
# 'feat.me' or 'vol.de' style abbreviations, and never glued to more letters or dots
_DOMAIN = re.compile(r"(?<![\w.@-])(?!(?:feat|vol)\.)(?:[a-z0-9][a-z0-9-]*\.)*[a-z0-9][a-z0-9-]{2,}\." + _TLD
                     + r"(?![\w.])")
_EMPTY_BRACKETS = re.compile(r"\(\s*\)|\[\s*\]|\{\s*\}")
_SEP_RUN = re.compile(r"(?:\s+[-\u2013\u2014|]){2,}\s+")
_EDGE_SEPS = " -\u2013\u2014|_,;:"


def strip_watermarks(text: str | None) -> str:
    """'Talitha (Original Mix) electronicfresh.com' -> 'Talitha (Original Mix)', 'Trip (Original Mix)
    [www.dj-promo.org]' -> 'Trip (Original Mix)'. URLs (http(s)://..., www.x.y) and bare domains with an
    ending of WATERMARK_TLDS go, with the brackets they leave empty and the separators they leave
    dangling. Text without an address is returned as it is."""
    s = nfc(text)
    out = _DOMAIN.sub(" ", _WWW.sub(" ", _URL.sub(" ", s)))
    if out == s:
        return s
    while True:
        cleaned = _EMPTY_BRACKETS.sub(" ", out)
        if cleaned == out:
            break
        out = cleaned
    out = _SEP_RUN.sub(" - ", out)
    out = re.sub(r"\s+", " ", out).strip(_EDGE_SEPS)
    return out.strip()


# ---- other cleaning of names and titles (R3) ------------------------------------------------------------
_OPEN, _CLOSE = "([{", ")]}"
_PAIR = {"(": ")", "[": "]", "{": "}"}


def _fix_unbalanced(s: str) -> str:
    """An opening bracket that never closes, at the end of a cut name: 'Light (Cleric Remix) [' -> 'Light
    (Cleric Remix)' (nothing inside: dropped); 'Light (Cleric Remix' -> 'Light (Cleric Remix)' (closed)."""
    for _ in range(4):
        stack: list[int] = []
        for i, ch in enumerate(s):
            if ch in _OPEN:
                stack.append(i)
            elif ch in _CLOSE and stack:
                stack.pop()
        if not stack:
            return s
        i = stack[-1]
        if re.search(r"\w", s[i + 1:]):
            s = s.rstrip() + _PAIR[s[i]]
        else:
            s = s[:i].rstrip(" -_")
    return s


def _depths(s: str) -> list[int]:
    """Bracket depth of every character (unmatched closers are ignored)."""
    out, d = [], 0
    for ch in s:
        if ch in _OPEN:
            d += 1
            out.append(d)
        elif ch in _CLOSE:
            out.append(d)
            d = max(0, d - 1)
        else:
            out.append(d)
    return out


def _split_top(s: str, sep: re.Pattern) -> list[str]:
    """Split on `sep` only outside brackets: 'Spirit (Kai Remix - Radio Edit)' is one part (r4-3 N3)."""
    depth = _depths(s)
    parts, last = [], 0
    for m in sep.finditer(s):
        if m.start() < len(depth) and depth[m.start()] == 0 and depth[max(m.end() - 1, m.start())] == 0:
            parts.append(s[last:m.start()])
            last = m.end()
    parts.append(s[last:])
    return parts


_TOP_DASH = re.compile(r"\s+[-\u2013\u2014]\s+")
_TIGHT_HYPHEN = re.compile(r"(?<=\S)-(?=\S)")
_HYPHEN = re.compile(r"-")
_BRACKET = re.compile(r"[()\[\]{}]")
# a track number written as its own ' - 06 - ' part: '06', '6', a vinyl side 'A1', a disc-track '1-06'
_NUM_PART = re.compile(r"^(?:\d{1,2}|[A-Da-d]\d{1,2}|\d{1,2}[-.]\d{1,2})$")
# a disc-track prefix: '1-04-', '1-04 ', '01-06 ', '1.04 - '
_DISC_TRACK = re.compile(r"^\s*\d{1,2}\s*[-.]\s*\d{1,3}(?:\s*[-._)]+\s*|\s+)(?=\S)")
_LEAD_NUM_TOKEN = re.compile(r"^\d{1,3}-")
_HASH = re.compile(r"(?i)^(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{6,10}$")
# release-name tokens of a scene folder: 'WEB', 'FLAC', '16BIT', a year, a catalogue number '(PHORUM004)'
_SCENE_MARK = re.compile(r"(?i)^\(?(?:web|flac|mp3|aiff?|wav|cdm?|cdr|cds|ep|lp|vinyl|vls|promo|"
                         r"\d{2}bit|(?:19|20)\d{2}|[a-z]{1,10}\d{2,6}[a-z]?)\)?$")
_SCENE_NOT_GROUP = re.compile(r"(?i)^(?:web|flac|mp3|aiff?|wav|cdm?|cdr|cds|ep|lp|vinyl|vls|promo|\d{2}bit|"
                              r"(?:19|20)\d{2})$")
# metadata after the title: a BPM (and/or a Camelot key) right after a closing VERSION bracket, or any
# number marked 'bpm' / 'key' -- never a number that belongs to the title words ('Dust 2', 'Lx2', '1982')
_META_TOKEN = r"(?:\d{2,3}(?:[.,]\d)?|\d{1,2}[ABab])"
_AFTER_VERSION = re.compile(r"^(?P<head>.*[)\]])\s+(?P<meta>" + _META_TOKEN + r"(?:\s+" + _META_TOKEN + r")?)\s*$")
_BPM_MARK = re.compile(r"(?i)[\s_-]+(?:\d{2,3}(?:[.,]\d+)?\s*bpm|bpm\s*[:=]?\s*\d{2,3}(?:[.,]\d+)?)\s*$")
# an unbracketed key mark: 'key: Am', 'key=8A', 'key 8A' (Camelot); a bracketed '(Key 8A)' is already left
# out of the base title by split_title_version, like any group that is not a version
_KEY_MARK = re.compile(r"(?i)[\s_-]+key\s*(?:[:=]\s*[0-9a-g][#b]?[0-9a-z]{0,3}|\s\d{1,2}[ab])\s*$")


def _bpm_like(tok: str) -> bool:
    if re.fullmatch(r"\d{1,2}[ABab]", tok):
        return True
    try:
        return 50 <= float(tok.replace(",", ".")) <= 250
    except ValueError:
        return False


def strip_trailing_metadata(title: str | None) -> str:
    """'Trip (Original Mix) 140' -> 'Trip (Original Mix)', 'Seiko 128 BPM' -> 'Seiko', 'Seiko (Key 8A)' ->
    'Seiko'. A number counts as metadata only right after a closing VERSION bracket or with a 'bpm'/'key'
    mark; 'Dust 2', 'Lx2' and '1982' keep their numbers."""
    s = nfc(title)
    for _ in range(3):
        before = s
        s = _BPM_MARK.sub("", s).rstrip()
        s = _KEY_MARK.sub("", s).rstrip()
        m = _AFTER_VERSION.match(s)
        if m and all(_bpm_like(t) for t in m.group("meta").split()):
            head = m.group("head")
            inner = re.search(r"[(\[]([^()\[\]]*)[)\]]\s*$", head)
            if inner and is_version_group(inner.group(1)):
                s = head.rstrip()
        if s == before:
            break
    return s.strip()


def clean_title(text: str | None) -> str:
    """A title as it is compared: watermarks and trailing BPM/key metadata out (tags and file names)."""
    return strip_trailing_metadata(strip_watermarks(text))


def _strip_audio_ext(file_name: str) -> str:
    name = nfc(file_name)
    base, dot, ext = name.rpartition(".")
    if dot and base and ("." + ext.lower()) in AUDIO_EXTS:
        return base
    return name


def clean_name(file_name: str) -> str:
    """The stem of a file name ready to be read: only an audio extension removed, NFC, watermarks out and
    an unbalanced trailing bracket fixed."""
    return _fix_unbalanced(strip_watermarks(_strip_audio_ext(file_name)))


# ---- titles and artists -------------------------------------------------------------------------------
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
    """Each name, its ' - ' parts (a folder 'Artist - Album'), its single artists ('A & B', 'A feat. B')
    and its aliases ('Komplex aka Jeroen Search': 'Komplex' and 'Jeroen Search', 1.0.1)."""
    keys: set[str] = set()
    for name in names:
        for seg in [name or ""] + _DASH.split(nfc(name)):
            for one in [seg] + artist_aliases(seg):
                keys.add(norm_key(one))
                keys.update(norm_key(p) for p in split_artists(one))
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
    the split artists). Either name of an alias ('Komplex aka Jeroen Search') is the same artist, and
    'TR440' / 'TR-440' / 'TR 440' or 'Vkn.modular' / 'Vkn Modular' are one name (1.0.1, R4)."""
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


# ---- folders (plan D10) --------------------------------------------------------------------------------
def _scene_folder_tokens(folder: str) -> list[str] | None:
    """The '-' tokens of a release-style folder ('Red_Rooms-Blind_Spot-(PHORUM004)-16BIT-WEB-FLAC-2026-PTC'):
    no ' - ', 3 tokens or more and at least one release token (WEB, FLAC, 16BIT, a year, a catalogue
    number). None for any other folder ('A-ha', 'Hip-Hop Classics', 'Artist - Album')."""
    if _TOP_DASH.search(folder):
        return None
    toks = [t.strip() for t in _split_top(folder, _HYPHEN)]
    if len(toks) < 3 or not all(toks) or not any(_SCENE_MARK.match(t) for t in toks[1:]):
        return None
    return toks


def parse_folder(parent: str | None) -> str | None:
    """The artist evidence of a parent folder: a scene folder gives only its first '-' token
    ('Red_Rooms-Blind_Spot-(PHORUM004)-...-PTC' -> 'Red Rooms'); any other folder is its own name, watermarks
    out ('Red Rooms - Blind Spot [Phorum Records]': artist_match also tries each ' - ' part). None when
    there is no folder."""
    f = strip_watermarks(parent)
    if not f:
        return None
    toks = _scene_folder_tokens(f)
    if toks:
        return re.sub(r"\s+", " ", toks[0].replace("_", " ")).strip() or None
    return f


def _folder_group(parent: str | None) -> str | None:
    """The release group that ends a scene folder ('...-2026-PTC' -> 'ptc'), lower case; else None."""
    toks = _scene_folder_tokens(strip_watermarks(parent)) if parent else None
    if not toks:
        return None
    last = toks[-1]
    if re.fullmatch(r"[A-Za-z0-9]{2,10}", last) and re.search(r"[A-Za-z]", last) and not _SCENE_NOT_GROUP.match(last):
        return last.lower()
    return None


# ---- readings of a file name (R3) ----------------------------------------------------------------------
@dataclass(frozen=True)
class NameReading:
    artist: str                   # '' when neither the name nor the folder gives one
    title: str                    # title with its version text, cleaned (clean_title)
    from_folder: bool = False     # the artist is the parent folder's: the name has no artist part here
    cut: bool = False             # the artist part comes from cutting the name at a glued hyphen or a scene
                                  # name ('Kwartz-Show me...', '04-red_rooms-trip'), not at ' - ' (B1-R)


def _tidy(s: str | None) -> str:
    return re.sub(r"\s+", " ", nfc(s)).strip(" -\u2013\u2014_,;")


def _components(comps: list[str]) -> tuple[str, str] | None:
    """' - ' parts of a name -> (artist, title). A middle part that is only a track number marks where
    the title starts ('Phil Berg - Darin - 06 - Seiko' -> 'Seiko'); otherwise everything after the
    first part is the title, as in v1.0 ('Artist - Album - Title' is never read as 'Title')."""
    comps = [c.strip() for c in comps if c.strip()]
    if len(comps) < 2:
        return None
    for i in range(1, len(comps) - 1):
        if _NUM_PART.match(comps[i]):
            return comps[0], " - ".join(comps[i + 1:])
    return comps[0], " - ".join(comps[1:])


def _scene_readings(stem: str, group: str | None) -> list[tuple[str, str]]:
    """'04-red_rooms-trip' -> [('red rooms', 'trip')]; '04-kwartz-show_me_that_light_(cleric_remix)-7d94e2e9'
    -> [('kwartz', 'show me that light (cleric remix)')]. Leading track numbers ('04', '1-04') and a
    trailing hash (6-10 hex characters with letters and digits) go; a trailing token equal to the scene
    folder's release group goes. Every split point is a reading, the first one first ('x-ray_spex-...')."""
    tokens = [t for t in _split_top(stem, _HYPHEN)]
    if any(not t for t in tokens):
        return []
    variants: list[list[str]] = []
    t = list(tokens)
    while len(t) > 2 and re.fullmatch(r"\d{1,3}", t[0]):
        t.pop(0)
    variants.append(t)
    if t != tokens:
        variants.append(list(tokens))              # '808-state-pacific_state': the number is the artist's
    out: list[tuple[str, str]] = []
    for v in variants:
        v = list(v)
        if len(v) > 2 and _HASH.match(v[-1]):
            v.pop()
        if group and len(v) > 2 and v[-1].lower() == group:
            v.pop()
        v = [re.sub(r"\s+", " ", x.replace("_", " ")).strip() for x in v]
        if len(v) < 2 or not all(v):
            continue
        for k in range(1, len(v)):
            left, right = "-".join(v[:k]), "-".join(v[k:])
            if _BRACKET.search(left) or left.isdigit():
                continue
            if (left, right) not in out:
                out.append((left, right))
    return out


def _tight_readings(s: str) -> tuple[list[tuple[str, str]], bool]:
    """'Kwartz-Show me that light (Cleric Remix)' -> [('Kwartz', 'Show me that light (Cleric Remix)')], at
    every top-level tight hyphen with 1-4 words and no bracket on its left. The bool says whether the
    first one is a likely artist-title split (2+ words on one side): 'Hip-Hop' or 'X-Ray' alone are one
    word, so the whole name stays the title first."""
    depth = _depths(s)
    out: list[tuple[str, str]] = []
    for m in _TIGHT_HYPHEN.finditer(s):
        if depth[m.start()] != 0:
            continue
        left, right = s[:m.start()].strip(), s[m.end():].strip()
        if not left or not right or _BRACKET.search(left) or left.isdigit() or not 1 <= len(left.split()) <= 4:
            continue
        out.append((left, right))
    if not out:
        return out, False
    left, right = out[0]
    base = split_title_version(right)[0] or right
    return out, len(left.split()) >= 2 or len(base.split()) >= 2


def _split_readings(stem: str, group: str | None) -> tuple[list[tuple[str, str]], bool, str, bool]:
    """(readings with an artist part, whether they come before the folder reading, the whole title, whether
    those readings cut the name at a glued hyphen or a scene name: their artist part is a guess, B1-R)."""
    if " " not in stem and "_-_" in stem:              # old scene style 'artist_-_title-group' (v1.0 rule)
        s = strip_track_number(_drop_scene_group(stem))
        r = _components(_split_top(s, _TOP_DASH))
        return ([r] if r else []), True, s, False
    if " " not in stem and "-" in stem and ("_" in stem or _LEAD_NUM_TOKEN.match(stem)):
        return _scene_readings(stem, group), True, strip_track_number(stem), True
    s = strip_track_number(stem)
    r = _components(_split_top(s, _TOP_DASH))
    if r:
        raw = re.sub(r"\s+", " ", stem.replace("_", " ")).strip()
        alt = _components(_split_top(raw, _TOP_DASH)) if raw != s else None
        return [r] + ([alt] if alt and alt != r else []), True, s, False   # '2-4 Grooves - ...': a name
    tight, likely = _tight_readings(s)
    return tight, likely, s, True


def name_readings(file_name: str, parent: str | None) -> list[NameReading]:
    """Every sensible way to read 'artist' and 'title' out of a file name (and its parent folder), the
    most likely first. Never empty. See the module docstring; parse_name() is the first reading."""
    stem = clean_name(file_name)
    folder = parse_folder(parent) or ""
    group = _folder_group(parent)
    out: list[NameReading] = []

    def add(artist: str, title: str, from_folder: bool = False, cut: bool = False) -> None:
        t = clean_title(title).strip(" -\u2013\u2014_,;")
        if not t:
            return
        r = NameReading(_tidy(artist), t, from_folder, cut)
        if not any((o.artist, o.title, o.from_folder) == (r.artist, r.title, r.from_folder) for o in out):
            out.append(r)

    m = _DISC_TRACK.match(stem)
    stems = [stem[m.end():], stem] if m else [stem]   # '1-04-Kwartz-...': then as written ('2-4 Grooves')
    for s in stems:
        readings, first, whole, cut = _split_readings(s, group)
        if first:
            for a, t in readings:
                add(a, t, cut=cut)
            add(folder, whole, True)
        else:
            add(folder, whole, True)
            for a, t in readings:
                add(a, t, cut=cut)
    if not out:
        out.append(NameReading(folder, stem or nfc(file_name), True))
    return out


def parse_name(file_name: str, parent: str | None) -> tuple[str, str]:
    """(artist, title-with-version) guessed from 'NN - Artist - Title (Mix).ext' + parent folder: the first
    of name_readings()."""
    r = name_readings(file_name, parent)[0]
    return r.artist, r.title


def row_artists(row: TrackRow) -> list[str]:
    """The row's names to match: the display, each artist and the aliases of each ('X aka Y')."""
    names = [row.artist_display] + list(row.artists or [])
    for n in list(names):
        names += artist_aliases(n)
    out: list[str] = []
    for n in names:
        if n and n not in out:
            out.append(n)
    return out or [row.artist_display]


def _version_ok(wanted: str | None, got_versions: list[str]) -> tuple[bool, str]:
    if not got_versions:
        return versions_compatible(wanted, None)
    results = [versions_compatible(wanted, v) for v in got_versions]
    if version_is_original(wanted):
        bad = [r for r in results if not r[0]]
        return (False, bad[0][1]) if bad else results[0]
    good = [r for r in results if r[0]]
    return good[0] if good else results[0]


# ---- what the file says, reading by reading -------------------------------------------------------------
@dataclass(frozen=True)
class FileIdentity:
    """One reading of a file: the tags where they say something, the name (or folder) for the rest."""
    artist: str
    title_full: str               # title with its version text
    base: str                     # title without the version
    version: str | None           # version of title_full
    name_version: str | None      # version written in the file name of this reading
    evidence: str                 # "tags" | "nombre" | "tags+nombre"
    name_artist: str = ""         # the artist part the NAME gives in this reading ('' for the folder reading)
    alternative: bool = False     # not the name's first reading: a later guess of where the artist ends
    cut: bool = False             # name_artist comes from a glued hyphen or a scene name (NameReading.cut)


def clean_artist(text: str | None) -> str | None:
    s = _tidy(strip_watermarks(text))
    return s or None


def _same_base_words(tag_title: str, reading_title: str) -> bool:
    """Does a reading's title (the whole name, for the folder reading) say the same title as the title tag?
    'Spirit - Original Mix' and the tag 'Spirit (Original Mix)' do; 'Adam Port - Rush' and 'Rush' do not."""
    tag_base = split_title_version(tag_title)[0] or tag_title
    got_base = split_title_version(reading_title)[0] or reading_title
    return title_words_match(tag_base, got_base)


def file_identities(file_name: str, parent: str | None, tag_artist: str | None,
                    tag_title: str | None) -> list[FileIdentity]:
    """The readings of a file as FileIdentity, tags first (watermarks and trailing metadata out). The
    folder is only used by a reading without an artist part and only when there is no artist tag (D10).

    Audit v101-1, B2: when the name says its own artist ('Adam Port - Rush.flac' in the folder 'Adam
    Beyer'), the folder reading is never combined with a title tag: the tag 'Rush' would make it 'Adam
    Beyer - Rush'. It stays only when the whole name is that same title ('Spirit - Original Mix.flac'
    tagged 'Spirit (Original Mix)'), i.e. when the name's 'artist part' is in fact the title."""
    ta, tt = clean_artist(tag_artist), (clean_title(tag_title) or None)
    readings = name_readings(file_name, parent)
    own_artist = any(r.artist and not r.from_folder for r in readings)
    out: list[FileIdentity] = []
    for i, r in enumerate(readings):
        if r.from_folder and own_artist and tt and not ta and not _same_base_words(tt, r.title):
            continue
        artist = ta or r.artist
        title_full = tt or r.title
        base, version = split_title_version(title_full)
        name_version = split_title_version(r.title)[1]
        used = {"tags" if ta else "nombre", "tags" if tt else "nombre"}
        evidence = "tags+nombre" if used == {"tags", "nombre"} else used.pop()
        fi = FileIdentity(artist, title_full, base or title_full, version, name_version, evidence,
                          "" if r.from_folder else r.artist, i > 0, r.cut and not r.from_folder)
        if fi not in out:
            out.append(fi)
    return out


# a track number glued to the artist part with a space ('01 Kwartz-Show me that light'); never '04-red rooms'
_GLUED_TRACK_NUMBER = re.compile(r"^\s*\d{1,2}\s+\S")
# any dash: a credit with one in it was cut at a later hyphen ('Fjaak & Kai-Holy' + 'Spirit')
_ANY_DASH = re.compile(r"[-\u2010-\u2015]")
# the words that join the artists of a credit ('Fjaak & Kai', 'fjaak feat kai', 'Adam Beyer with Kai')
_CREDIT_JOIN = re.compile(r"(?i)\s*(?:,|&|\+|\b(?:x|and|vs|feat|ft|featuring|with)\b\.?)\s*")


def name_artist_is_exact(wanted: Iterable[str | None], name_artist: str | None) -> bool:
    """Is the artist part of a reading exactly one of the row's names (an alias, a single artist of a duo,
    or the duo in another order), word for word, with no word more or less? 'Planetary Assault Systems-Non'
    is not 'Planetary Assault Systems', and '04-red rooms' is not 'Red Rooms'; 'x-ray spex' is 'X-Ray Spex'
    and 'TR-440' is 'TR440'. A typo in a long word is allowed (T.1), a word more is not. A track number
    glued with a space is no word of the artist, as in artist_match ('01 Kwartz' is 'Kwartz'; '808 State'
    keeps its 3 digits)."""
    got = norm_key(name_artist)
    if not got:
        return False
    keys = _artist_keys(wanted)

    def exact(g: str) -> bool:
        return any((len(w.split()) == len(g.split()) and _artist_pair(w, g).same)
                   or w.replace(" ", "") == g.replace(" ", "") for w in keys)

    if exact(got):
        return True
    bare = _without_track_number(got) if _GLUED_TRACK_NUMBER.match(nfc(name_artist)) else None
    if bare and exact(bare):
        return True
    parts = [k for k in (norm_key(p) for p in split_artists(name_artist)) if k]
    return len(parts) > 1 and all(exact(p) for p in parts)


def name_artist_fits(wanted: Iterable[str | None], name_artist: str | None) -> bool:
    """Audit v101-1 review, B1-R: is the artist part that a CUT of the name gives (a glued hyphen or a scene
    name) the row's artist? Only when it is exactly one of its names (name_artist_is_exact), or a credit whose
    other artists come with a joiner word ('&', 'and', 'feat', 'ft', 'featuring', 'x', 'vs', 'with', '+' or a
    comma): 'Fjaak & Kai', 'fjaak feat kai' and 'Kai & Fjaak' fit «Fjaak». Words glued with a space to the
    row's name ('Adam Beyer Space' of 'Adam Beyer Space-Time', 'Red Rooms Bad' of 'Red Rooms Bad-Trip') are
    never a co-artist: with no dash between artist and title, the cut was the title's own hyphen. For the
    same reason the credit's last artist, right before the cut, is a row name or ONE word: a joiner needs
    one artist word after it, and more could already be the title's ('Fjaak & Kai Holy' of 'Fjaak & Kai
    Holy-Spirit'). A credit with a dash in it ('Fjaak & Kai-Holy') was cut at a later hyphen, so there only
    the exact rule counts."""
    if name_artist_is_exact(wanted, name_artist):
        return True
    if not name_artist or _ANY_DASH.search(name_artist):
        return False
    parts = [p.strip(" .") for p in _CREDIT_JOIN.split(nfc(name_artist)) if p and p.strip(" .")]
    if len(parts) < 2 or not any(name_artist_is_exact(wanted, p) for p in parts):
        return False
    return name_artist_is_exact(wanted, parts[-1]) or len(parts[-1].split()) == 1


def reading_fits(wanted: Iterable[str | None], fi: FileIdentity) -> bool:
    """Does the artist part that the NAME gives in this reading belong to the row? A reading whose artist is
    the folder's or the tags' only always does.

    Audit v101-1, B1: a reading after the first one (a later split point of the name) only counts when the
    artist part it gives is exactly a row name (name_artist_is_exact). Otherwise it moved title words into
    the artist ('Adam Beyer-Space-Time.flac' read as 'Adam Beyer-Space' + 'Time'), and the shorter title
    would let another track pass for the row. B1-R (the review of that fix): the same holds for the FIRST
    cut at a glued hyphen or of a scene name, when the name has no dash between artist and title ('Adam
    Beyer Space-Time.flac' is never 'Adam Beyer Space' + 'Time' for «Adam Beyer - Time»); there a credit
    with a joiner word also fits (name_artist_fits). A first reading at ' - ' is judged as before."""
    if not fi.name_artist:
        return True
    if fi.cut:
        return name_artist_fits(wanted, fi.name_artist)
    if not fi.alternative:
        return True
    return name_artist_is_exact(wanted, fi.name_artist)


def _score(row: TrackRow, wanted: list[str], fi: FileIdentity) -> tuple[tuple, IdentityScore]:
    versions = [v for v in (fi.version, fi.name_version) if v]
    fits = reading_fits(wanted, fi)
    artist = artist_match(wanted, fi.artist)
    if not fits:                     # B1: never the same artist through a reading that ate title words
        artist = ArtistMatch(artist.score, False)
    title, numbers_ok = title_similarity(row.title, fi.base)
    words_ok = title_words_match(row.title, fi.base)
    ok, reason = _version_ok(row.version, versions)
    ident = IdentityScore(round(artist.score, 1), round(title, 1), ok, reason, fi.evidence, fi.artist,
                          fi.title_full, fi.version or fi.name_version, numbers_ok, artist.same, words_ok)
    same_song = artist.same and artist.score >= ARTIST_MIN and title >= TITLE_MIN
    # a reading that fits ranks before one that does not, so a doubt names the name's own reading
    key = (same_song and ok, same_song, fits, ok, 0.35 * artist.score + 0.45 * title)
    return key, ident


def identity_score(row: TrackRow, info: AudioInfo, source_path_tail: str | None) -> IdentityScore:
    tail_parts = [p for p in PureWindowsPath(source_path_tail.replace("/", "\\")).parts] if source_path_tail else []
    file_name = tail_parts[-1] if tail_parts else info.path.name
    parent = tail_parts[-2] if len(tail_parts) >= 2 else None
    return identity_from_names(row, file_name, parent, info.tag_artist, info.tag_title)


def identity_from_names(row: TrackRow, file_name: str, parent: str | None, tag_artist: str | None = None,
                        tag_title: str | None = None) -> IdentityScore:
    """identity_score() without an audio file: from a file name, its parent folder and the tags if known (a
    search result of the Diagnóstico has no tags). The best reading of the name for the row counts."""
    wanted = row_artists(row)
    idents = file_identities(file_name, parent, tag_artist, tag_title)
    best_key, best = max((_score(row, wanted, fi) for fi in idents), key=lambda kv: kv[0])
    if version_is_original(row.version) and best.version_ok:
        # an original row: a remix written in ANY reading of the name still counts (both sources, v1.0)
        every = [v for fi in idents for v in (fi.version, fi.name_version) if v]
        ok, reason = _version_ok(row.version, every)
        if not ok:
            best = IdentityScore(best.artist, best.title, False, reason, best.evidence, best.got_artist,
                                 best.got_title, best.got_version, best.numbers_ok, best.same_artist,
                                 best.title_words_ok)
    return best
