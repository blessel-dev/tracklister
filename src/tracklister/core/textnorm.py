"""Shared text normalisation and version logic. Owner: core (frozen during the parallel phase).

Used by inputs (parsing/cleaning), enrich (candidate picking), verify (identity check),
library (duplicate keys) and organize (reorder). Rules come from the prototypes in
.agents/tasks/tracklister-v2/fuentes/tlparse.py and enrich_probe.py.
"""
from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz

from tracklister.core.model import VersionKind

_QUOTES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u00b4": "'", "`": "'",
                         "\u201c": '"', "\u201d": '"'})

VERSION_KW = re.compile(
    r"\b(remix|rmx|mix|edit|dub|version|rework|re-?edit|vip|bootleg|flip|reprise|instrumental|"
    r"acapella|a cappella|remaster(?:ed)?|interpretation|reshape|tool|jam|cut|live)\b", re.I)
_ORIGINAL = re.compile(r"^(?:original|original mix|original version|extended|extended mix|"
                       r"extended version|club mix)$", re.I)
_REMIX_WORDS = re.compile(r"\b(remix|rmx|rework|re-?edit|reshape|interpretation|bootleg|flip|vip|remake)\b", re.I)
_STRIP_FOR_REMIXER = re.compile(
    r"\b(remix|rmx|edit|dub|mix|version|rework|re-?edit|reshape|interpretation|bootleg|flip|vip|"
    r"remake|'s)\b", re.I)


def nfc(s: str | None) -> str:
    """NFC + typographic quotes to ASCII + collapsed whitespace. Keeps accents and case."""
    s = unicodedata.normalize("NFC", s or "").translate(_QUOTES)
    return re.sub(r"\s+", " ", s).strip()


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm_key(s: str | None, *, drop_original: bool = True) -> str:
    """Comparison key: lower case, no accents, alnum tokens only.

    drop_original=True also removes 'original mix'/'original'/'feat.' words (prototype `norm`).
    """
    s = strip_accents(nfc(s)).lower()
    s = s.replace("\u00f8", "o").replace("\u00e6", "ae").replace("\u00df", "ss").replace("\u0111", "d")
    s = s.replace("\u00f0", "d").replace("\u00fe", "th")
    if drop_original:
        s = re.sub(r"\b(original mix|original|feat\.?|ft\.?|featuring)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def split_artists(a: str | None) -> list[str]:
    """'Blasha & Allatt' -> ['Blasha', 'Allatt'] (also , + x and vs feat ft featuring)."""
    parts = re.split(r"\s*(?:,|&|\+|\bx\b|\band\b|\bvs\.?\b|\bfeat\.?\b|\bft\.?\b|\bfeaturing\b)\s*",
                     nfc(a), flags=re.I)
    return [p.strip(" .") for p in parts if p and p.strip(" .")]


def pick_version(groups: list[str]) -> str | None:
    """The version among a title's version groups, given from right to left: the rightmost one that is
    not the original or extended mix, so a remix, a live, a radio edit or a dub is never lost behind an
    '(Extended Mix)': 'Spirit (Kai Remix) (Extended Mix)' is the Kai Remix (audit round 4, B3). When every
    group is original or extended, the rightmost one."""
    for g in groups:
        if classify_version(g) not in (VersionKind.ORIGINAL, VersionKind.EXTENDED):
            return g
    return groups[0] if groups else None


def split_title_version(title: str | None) -> tuple[str, str | None]:
    """'Higher Things (FJAAK Remix) [Label]' -> ('Higher Things', 'FJAAK Remix').

    Only trailing bracket groups that contain a version keyword count as the version;
    other trailing groups (labels, feat.) are dropped from the base title. Also handles
    a trailing ' - Xyz Remix' and bare 'Original Mix' suffixes. With several version groups,
    pick_version() chooses ('(Kai Remix) (Extended Mix)' -> 'Kai Remix'). The returned version
    keeps its original text (e.g. 'Original Mix'); use classify_version() to interpret it.
    """
    t = nfc(title)
    groups: list[str] = []              # version groups, right to left
    while True:
        m = re.search(r"\s*([\(\[])\s*([^()\[\]]*?)\s*[\)\]]\s*$", t)
        if not m or m.start() == 0:
            break
        inner = m.group(2).strip()
        t = t[:m.start()].rstrip()
        if inner and VERSION_KW.search(inner) and not re.match(r"(?i)feat|ft\b", inner):
            groups.append(inner)
    m = re.search(r"\s+[-\u2013\u2014]\s+([^-\u2013\u2014]*\b(?:remix|rmx|edit|mix|dub|version|rework)\b[^-]*)$",
                  t, re.I)
    if m:                               # ' - Kai Remix' is one more group, left of the brackets
        groups.append(m.group(1).strip())
        t = t[:m.start()]
    version = pick_version(groups)
    m = re.search(r"\s+((?:original|extended|radio|club|dub|vocal|instrumental)\s+(?:mix|edit|version))$", t, re.I)
    if m and version is None:
        version = m.group(1)
        t = t[:m.start()]
    m = re.search(r"\s+(?:feat\.?|ft\.?|featuring)\s+.+$", t, re.I)
    if m:
        t = t[:m.start()]
    return t.strip(" -,;\"'"), version


def classify_version(version: str | None) -> VersionKind:
    v = nfc(version)
    if not v or _ORIGINAL.match(v):
        return VersionKind.EXTENDED if re.match(r"(?i)extended", v or "") else VersionKind.ORIGINAL
    low = v.lower()
    if re.search(r"\bradio\b", low):
        return VersionKind.RADIO_EDIT
    if _REMIX_WORDS.search(low):
        return VersionKind.REMIX
    if re.search(r"\blive\b", low):
        return VersionKind.LIVE
    if re.search(r"\bdub\b", low):
        return VersionKind.DUB
    if re.search(r"\bedit\b", low):
        return VersionKind.EDIT
    return VersionKind.OTHER


def remixer_of(version: str | None) -> str | None:
    """'Kai Van Dongen Remix' -> 'kai van dongen'; None if not a remix-like version."""
    if classify_version(version) not in (VersionKind.REMIX, VersionKind.EDIT, VersionKind.DUB):
        return None
    k = norm_key(_STRIP_FOR_REMIXER.sub(" ", nfc(version)))
    return k or None


def versions_compatible(wanted: str | None, got: str | None) -> tuple[bool, str]:
    """Version-aware identity rule (brief §8, 02 §3.E).

    - wanted original/extended/None -> got must be original/extended/None (no remix, no radio edit)
    - wanted remix/edit/dub          -> got must name the same remixer (partial_ratio >= 85)
    - wanted radio edit              -> got must be a radio edit
    - anything else                  -> fuzzy match of the normalised version >= 85
    Returns (ok, reason_es).
    """
    wk, gk = classify_version(wanted), classify_version(got)
    full = (VersionKind.ORIGINAL, VersionKind.EXTENDED)
    if wk in full:
        if gk in full:
            return True, "versión original"
        return False, f"se pedía la original y el archivo es '{nfc(got)}'"
    if wk == VersionKind.RADIO_EDIT:
        return (gk == VersionKind.RADIO_EDIT,
                "radio edit" if gk == VersionKind.RADIO_EDIT else f"se pedía radio edit y el archivo es '{nfc(got) or 'original'}'")
    want_rmx = remixer_of(wanted)
    if want_rmx:
        if got is None or gk in full:
            return False, f"se pedía '{nfc(wanted)}' y el archivo es la original"
        if fuzz.partial_ratio(want_rmx, norm_key(got)) >= 85:
            return True, f"remixer '{nfc(wanted)}' presente"
        return False, f"se pedía '{nfc(wanted)}' y el archivo es '{nfc(got)}'"
    ok = fuzz.ratio(norm_key(wanted), norm_key(got)) >= 85
    return ok, ("versión coincide" if ok else f"versión distinta: '{nfc(got)}'")
