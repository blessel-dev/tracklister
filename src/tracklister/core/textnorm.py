"""Shared text normalisation and version logic. Owner: core (frozen during the parallel phase).

Used by inputs (parsing/cleaning), enrich (candidate picking), verify (identity check),
library (duplicate keys) and organize (reorder). Rules come from the prototypes in
.agents/tasks/tracklister-v2/fuentes/tlparse.py and enrich_probe.py.
"""
from __future__ import annotations

import re
import unicodedata
from itertools import permutations
from typing import Iterable

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
_FULL = (VersionKind.ORIGINAL, VersionKind.EXTENDED)
_BARE_EXTENDED = re.compile(r"^extended$", re.I)
_FEAT_GROUP = re.compile(r"(?i)feat|ft\b")
_BRACKET_TAIL = re.compile(r"\s*([\(\[])\s*([^()\[\]]*?)\s*[\)\]]\s*$")
_DASH_TAIL = re.compile(r"\s+[-\u2013\u2014]\s+([^-\u2013\u2014]*\b(?:remix|rmx|edit|mix|dub|version|rework)\b[^-]*)$",
                        re.I)
_SUFFIX = re.compile(r"\s+((?:original|extended|radio|club|dub|vocal|instrumental)\s+(?:mix|edit|version))$", re.I)
# 'Title (feat. X) Y Dub' once the trailing groups are gone: 'Y Dub' is a version group (02 section 3.B)
_FEAT_THEN_CORE = re.compile(r"[\(\[]\s*(?:feat\.?|ft\.?|featuring)\s+[^()\[\]]+?\s*[\)\]]\s+([^()\[\]]+?)\s*$", re.I)
_FEAT_TAIL = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s+.+$", re.I)
_GROUP_SEP = re.compile(r"\s+[-\u2013\u2014]\s+|\s*[()\[\]]+\s*")
_GROUP_EDGE = " -\u2013\u2014,;"
# The words that say which cut of a track a version group is (versions_compatible): the same cut needs
# the same words. Synonyms share one word; 'mix', 'version', 'original', 'extended'... say nothing.
_FACET_WORDS = {
    "remix": "remix", "rmx": "remix", "rework": "remix", "reshape": "remix", "interpretation": "remix",
    "remake": "remix", "bootleg": "remix", "flip": "remix", "edit": "edit", "reedit": "edit", "radio": "radio",
    "dub": "dub", "live": "live", "instrumental": "instrumental", "acapella": "acapella", "acappella": "acapella",
    "remaster": "remaster", "remastered": "remaster", "vip": "vip", "reprise": "reprise", "tool": "tool",
    "jam": "jam", "cut": "cut",
}
_NOISE_WORDS = frozenset({"mix", "version", "original", "extended", "club", "short", "single", "album", "s", "by"})


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


def is_version_group(text: str | None) -> bool:
    """Is a bracket group (or a ' - ' part) of a title a version group? A version word ('Kai Remix',
    'Radio Edit', 'Live', 'Original Mix') or a bare 'Extended'; never a 'feat.' group. Labels are not."""
    s = nfc(text)
    if not s or _FEAT_GROUP.match(s):
        return False
    return bool(VERSION_KW.search(s) or _BARE_EXTENDED.match(s))


def version_groups(version: str | None) -> list[str]:
    """A version's groups in written order, split at ' - ' and at brackets:
    'Kai Remix - Radio Edit' and '(Kai Remix) [Radio Edit]' -> ['Kai Remix', 'Radio Edit']."""
    out = []
    for part in _GROUP_SEP.split(nfc(version)):
        part = part.strip(_GROUP_EDGE)
        if part:
            out.append(part)
    return out


def merge_versions(groups: Iterable[str | None]) -> str | None:
    """THE version rule of every path: pasted text, tables, the trackid.net CSV, the table editor, file
    tags and names, the stores, the library, Reordenar and the Diagnostico (audit round 4, second review;
    DECISIONES V.1). `groups` are a title's version groups in written order, plus the other places that
    say the version: the text after a feat group comes first, a table's Version/Mix column last. Each one
    may hold several groups itself ('Kai Remix - Radio Edit').

    - Original/extended groups are dropped when any other group remains. When all of them are original
      or extended, the rightmost one is the version: '(Original Mix) (Extended Mix)' -> 'Extended Mix'.
    - Every other group is kept, in written order, without repeats (a group whose words are all in
      another kept group is a repeat: 'Remix' next to 'Kai Remix'), joined with ' - '.

    So '(Kai Remix) (Extended Mix)', '(Extended Mix) (Kai Remix)' and '(Kai Remix) (Extended)' are 'Kai
    Remix', and '(Kai Remix) (Radio Edit)' and '(Kai Remix - Radio Edit)' are 'Kai Remix - Radio Edit': no
    group hides another. merge_versions([merge_versions(x)]) == merge_versions(x)."""
    parts: list[str] = []
    for g in groups:
        parts.extend(version_groups(g))
    kept = [p for p in parts if classify_version(p) not in _FULL] or parts[-1:]
    uniq: list[tuple[str, frozenset[str]]] = []
    for p in kept:
        words = frozenset(norm_key(p, drop_original=False).split())
        if words and all(words != w for _, w in uniq):
            uniq.append((p, words))
    final = [p for p, words in uniq if not any(words < w for _, w in uniq)]
    return " - ".join(final) or None


def version_is_original(version: str | None) -> bool:
    """No version, or only original/extended groups: the original track (brief §8 groups Original and
    Extended). 'Kai Remix (Extended Mix)' is not."""
    return not _kept_groups(version)


def version_key(version: str | None) -> str:
    """THE comparison key of a version (1.0.1): 'original' for the original/extended track, otherwise the
    kept groups (merge_versions without original/extended), each normalised, SORTED and joined by spaces.
    So '(Kai Remix) (Radio Edit)' and '(Radio Edit) (Kai Remix)' are one key, 'kai remix radio edit'
    (audit r4-3 N1), while 'Kai Remix', 'Radio Edit' and 'Kai Remix - Radio Edit' stay three keys. For a
    single group it is the same text the 1.0.0 library keys had."""
    if version_is_original(version):
        return "original"
    return " ".join(sorted(norm_key(g, drop_original=False) for g in _kept_groups(version)))


def split_title_version(title: str | None) -> tuple[str, str | None]:
    """'Higher Things (FJAAK Remix) [Label]' -> ('Higher Things', 'FJAAK Remix').

    The version groups of the title, merged with merge_versions() (the shared rule): the trailing bracket
    groups that are versions (is_version_group; labels and feat groups are dropped from the base title),
    trailing ' - Xyz Remix' parts, a bare 'Original Mix'-style suffix and the version written after a
    feat group ('Title (feat. X) Y Dub'), in any order and mix: 'Spirit (Kai Remix) - Extended Mix' is
    ('Spirit', 'Kai Remix'), 'Spirit (Kai Remix) (Radio Edit)' is ('Spirit', 'Kai Remix - Radio Edit').
    The version keeps its written text (e.g. 'Original Mix'); use classify_version() to interpret it.
    """
    base, groups, _ = _split_title(title)
    return base, merge_versions(groups)


def title_dropped_groups(title: str | None) -> list[str]:
    """The trailing bracket groups that split_title_version() takes out of the base title WITHOUT making them
    the version, in written order: a label, a catalogue number, a feat group, '(Part 2)', '(Nuxx)'...
    'Born Slippy (Nuxx) [Junior]' -> ['Nuxx', 'Junior']. 1.0.1, Addendum 10: verify.identity asks for a
    confirmation when a file name only fits its row once such a group is gone (DECISIONES X.42)."""
    return _split_title(title)[2]


def _split_title(title: str | None) -> tuple[str, list[str], list[str]]:
    """(base title, version groups in written order, dropped non-version bracket groups in written order)."""
    t = nfc(title)
    groups: list[str] = []              # version groups, right to left
    dropped: list[str] = []             # bracket groups that are not versions, right to left
    while True:
        m = _BRACKET_TAIL.search(t)
        if m and m.start() > 0:
            inner = m.group(2).strip()
            t = t[:m.start()].rstrip()
            if is_version_group(inner):
                groups.append(inner)
            elif inner:
                dropped.append(inner)
            continue
        m = _DASH_TAIL.search(t) or _SUFFIX.search(t)
        if m and m.start() > 0:         # ' - Kai Remix' or ' Original Mix': one more group, to the left
            groups.append(m.group(1).strip())
            t = t[:m.start()]
            continue
        m = _FEAT_THEN_CORE.search(t)
        if m and m.start() > 0 and VERSION_KW.search(m.group(1)):
            groups.append(m.group(1).strip())
            t = t[:m.start(1)].rstrip()
            continue
        break
    m = _FEAT_TAIL.search(t)
    if m:
        t = t[:m.start()]
    return t.strip(" -,;\"'"), groups[::-1], dropped[::-1]


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


def _kept_groups(version: str | None) -> list[str]:
    """The groups of a version that say which track it is: merge_versions(), original/extended out."""
    return [g for g in version_groups(merge_versions([version])) if classify_version(g) not in _FULL]


def _facets(group: str) -> tuple[frozenset[str], str]:
    """(version words, other words) of one group: 'Kai Remix Radio Edit' -> ({'remix', 'radio'}, 'kai').
    'Radio Edit'/'Radio Mix' are one word ('radio'), 'Re-Edit' is 'edit'; 'mix', 'version', 'original'...
    are neither."""
    toks = norm_key(group, drop_original=False).split()
    facets: set[str] = set()
    names: list[str] = []
    i = 0
    while i < len(toks):
        t, nxt = toks[i], (toks[i + 1] if i + 1 < len(toks) else "")
        if t == "radio":
            facets.add("radio")
            i += 1 if nxt in ("edit", "mix", "version", "cut") else 0
        elif t == "re" and nxt == "edit":
            facets.add("edit")
            i += 1
        elif t == "a" and nxt in ("cappella", "capella"):
            facets.add("acapella")
            i += 1
        elif t in _FACET_WORDS:
            facets.add(_FACET_WORDS[t])
        elif t not in _NOISE_WORDS:
            names.append(t)
        i += 1
    return frozenset(facets), " ".join(names)


def _group_pair_ok(wanted: str, got: str) -> bool:
    """One wanted group against one file group: the same kind and version words, then the same remixer
    (partial_ratio >= 85, as before), the same people for a radio edit, or a close text otherwise."""
    kind = classify_version(wanted)
    if classify_version(got) != kind:
        return False
    (wf, wn), (gf, gn) = _facets(wanted), _facets(got)
    if wf != gf:
        return False
    rmx = remixer_of(wanted)
    if rmx:
        return fuzz.partial_ratio(rmx, norm_key(got)) >= 85
    if kind == VersionKind.RADIO_EDIT:
        return wn == gn if not (wn and gn) else fuzz.partial_ratio(wn, gn) >= 85
    return fuzz.ratio(norm_key(wanted), norm_key(got)) >= 85


def _groups_match(wanted: list[str], got: list[str]) -> bool:
    """Every wanted group has its own partner among the file's groups, and the other way round."""
    if len(wanted) != len(got):
        return False
    if len(got) > 6:                    # never in practice: a greedy pass instead of every order
        pool = list(got)
        for w in wanted:
            hit = next((g for g in pool if _group_pair_ok(w, g)), None)
            if hit is None:
                return False
            pool.remove(hit)
        return True
    return any(all(_group_pair_ok(w, g) for w, g in zip(wanted, order)) for order in permutations(got))


def versions_compatible(wanted: str | None, got: str | None) -> tuple[bool, str]:
    """Version-aware identity rule (brief §8, 02 §3.E), group by group (audit round 4, second review).

    Each version is split into its groups (merge_versions, then version_groups), without the
    original/extended ones.
    - No group wanted (original/extended/None): the file must have none either (no remix, no radio edit).
    - Otherwise every wanted group needs its own partner in the file, and the other way round, with no
      group more or less. A partner has the same kind (REMIX, RADIO_EDIT, EDIT, DUB, LIVE, OTHER) and the
      same version words ('Kai Remix Edit' is not 'Kai Remix'), and:
        a group that names a remixer -> the same remixer (partial_ratio >= 85, as before);
        a radio edit                 -> the same people, or nobody ('Kai Radio Edit' is not 'Radio Edit');
        anything else                -> fuzzy match of the normalised text >= 85.
    'Kai Remix' against 'Kai Remix - Radio Edit', or 'Radio Edit' against 'Kai Remix - Radio Edit', never
    match; 'Kai Remix' still takes 'Kai Remix (Extended Mix)'. Returns (ok, reason_es).
    """
    wg, gg = _kept_groups(wanted), _kept_groups(got)
    want_txt, got_txt = merge_versions([wanted]) or nfc(wanted), merge_versions([got]) or nfc(got)
    radio = len(wg) == 1 and classify_version(wg[0]) == VersionKind.RADIO_EDIT
    if not wg:
        if not gg:
            return True, "versión original"
        return False, f"se pedía la original y el archivo es '{got_txt}'"
    if not gg:
        if radio:
            return False, f"se pedía radio edit y el archivo es '{got_txt or 'original'}'"
        return False, f"se pedía '{want_txt}' y el archivo es la original"
    if _groups_match(wg, gg):
        if len(wg) > 1:
            return True, f"versión '{want_txt}' presente"
        if radio:
            return True, "radio edit"
        return True, (f"remixer '{want_txt}' presente" if remixer_of(wg[0]) else "versión coincide")
    if radio:
        return False, f"se pedía radio edit y el archivo es '{got_txt}'"
    if len(wg) == 1 and len(gg) == 1 and not remixer_of(wg[0]):
        return False, f"versión distinta: '{got_txt}'"
    return False, f"se pedía '{want_txt}' y el archivo es '{got_txt}'"
