"""Artist aliases and other search spellings for the rows Soulseek finds nothing for (1.0.1, R4).

Owner: ENGINE branch (C), item C-0. Pure: stdlib + tracklister.core.textnorm only.
SPDX-License-Identifier: GPL-3.0-or-later

Soulseek returns a file only when every word of the query is in its path, and the engines'
--strict-artist needs the artist as a literal part of the path (3.x Sockseek.Core/Matching/Conditions/
FileConditions.cs:277-283, 392-404). Three spellings of the user's first real set found nothing that way:

- 'Komplex aka Jeroen Search': two names of one artist. Few files carry both, or the word 'aka'.
- 'Vkn.modular': the engines keep the '.' in the query (it is not one of their special characters,
  3.x Sockseek.Core/Common/Utils.cs:439-449, 2.x Utilities/Utils.cs:382), so it is sent as 'vkn.modular'.
- 'TR440': a file named 'TR-440' or 'TR 440' has the words 'tr' and '440', never 'tr440'; and
  --strict-artist keeps the '-' literal, so 'TR 440' never passes for a 'TR-440' file, or the other way round.

search_variants() lists the other spellings to try, never the original one, at most MAX_VARIANTS.
artist_aliases() is also what the verification accepts as the artist: either name is the same artist.
"""
from __future__ import annotations

import re

from tracklister.core.textnorm import nfc

MAX_VARIANTS = 2            # extra engine passes per format pass at most (plan D4)

_AKA = r"a\.?k\.?a\.?"      # aka, a.k.a., AKA, a.k.a
ALIAS_SEP = re.compile(r"\s+" + _AKA + r"\s+", re.I)
_ALIAS_BRACKET = re.compile(r"^(.+?)\s*[\(\[]\s*" + _AKA + r"\s+([^()\[\]]+?)\s*[\)\]]\s*$", re.I)
_ONLY_AKA = re.compile(r"^" + _AKA + r"$", re.I)
_EDGE = " ,;&+-\u2013\u2014"
_LETTER = r"[^\W\d_]"       # a letter in any script
_DOT = re.compile(r"(?<=" + _LETTER + _LETTER + r")\.(?=" + _LETTER + _LETTER + r")")
_END = r"(?=$|[^\w])"
_LD_GLUED = re.compile(r"^(" + _LETTER + r"{2,})(\d{2,})" + _END)
_LD_SPLIT = re.compile(r"^(" + _LETTER + r"{2,})(\s+|-)(\d{2,})" + _END)


def artist_aliases(artist: str | None) -> list[str]:
    """The names of an artist written 'X aka Y' (also 'a.k.a.', 'AKA' and 'X (aka Y)').

    'Komplex aka Jeroen Search' -> ['Komplex', 'Jeroen Search']; 'A aka B aka C' -> ['A', 'B', 'C'].
    No alias -> []. 'AKA AKA & Thalstroem' is a name, not an alias ('AKA' alone is never a name), and a
    word that only contains the letters ('Akasha', 'Sakamoto') never splits anything."""
    s = nfc(artist)
    m = _ALIAS_BRACKET.match(s)
    parts = [m.group(1), m.group(2)] if m else ALIAS_SEP.split(s)
    if len(parts) < 2:
        return []
    names = [p.strip(_EDGE) for p in parts]
    if any(not re.search(r"\w", n) or _ONLY_AKA.match(n) for n in names):
        return []
    out: list[str] = []
    for n in names:
        if all(n.casefold() != o.casefold() for o in out):
            out.append(n)
    return out if len(out) > 1 else []


def dotted_variant(text: str | None) -> str | None:
    """A '.' between two runs of 2 or more letters becomes a space: 'Vkn.modular' -> 'Vkn modular'.

    Never 'D.A.V.E.' (single letters) or 'St. Germain' (a space after the dot). None when nothing changes."""
    s = nfc(text)
    out = _DOT.sub(" ", s)
    return out if out != s else None


def letter_digit_variant(text: str | None, sep: str = " ") -> str | None:
    """A name that STARTS with 2 or more letters glued to 2 or more digits, split with `sep`:
    'TR440' -> 'TR 440' ('TR-440' with sep='-'). 'Lx2', 'DVS1' (one digit) and '1982' stay: None."""
    s = nfc(text)
    m = _LD_GLUED.match(s)
    if not m:
        return None
    return s[:m.end(1)] + sep + s[m.start(2):]


def letter_digit_forms(name: str | None) -> list[str]:
    """The other two spellings of a letter-digit artist name: 'TR440' -> ['TR 440', 'TR-440'],
    'TR-440' -> ['TR440', 'TR 440'], 'TR 440' -> ['TR440', 'TR-440']. Anything else -> []."""
    s = nfc(name)
    if _LD_GLUED.match(s):
        return [letter_digit_variant(s, " "), letter_digit_variant(s, "-")]
    m = _LD_SPLIT.match(s)
    if not m:
        return []
    head, tail = s[:m.end(1)], s[m.start(3):]
    other = " " if m.group(2) == "-" else "-"
    return [head + tail, head + other + tail]


def search_variants(artist: str | None, title: str | None) -> list[tuple[str, str]]:
    """Other (artist, title) spellings to search when the row as written found nothing, in this order:

    1. each alias alone ('Komplex', then 'Jeroen Search'), with the same title;
    2. the dotted form ('Vkn modular'), of the artist (or of each alias) and of the title;
    3. the letter-digit forms: the other two spellings of the artist (or of each alias), 'TR 440' then
       'TR-440'; for an artist that has none, a title that starts glued ('TB303 Acid') split the same way.

    Deduplicated (case-insensitively), never the original pair, at most MAX_VARIANTS."""
    a0, t0 = nfc(artist), nfc(title)
    seen = {(a0.casefold(), t0.casefold())}
    out: list[tuple[str, str]] = []

    def add(a: str | None, t: str | None) -> None:
        a, t = nfc(a), nfc(t)
        key = (a.casefold(), t.casefold())
        if a and t and key not in seen:
            seen.add(key)
            out.append((a, t))

    aliases = artist_aliases(a0)
    names = aliases or [a0]
    for a in aliases:
        add(a, t0)
    for a in names:
        add(dotted_variant(a) or a, dotted_variant(t0) or t0)
    for a in names:
        forms = letter_digit_forms(a)
        for form in forms:
            add(form, t0)
        if not forms:
            for sep in (" ", "-"):
                add(a, letter_digit_variant(t0, sep) or t0)
    return out[:MAX_VARIANTS]
