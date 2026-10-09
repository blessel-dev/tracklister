"""Clean imported rows before the review table (01 section 6.3 "Reglas de limpieza").

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

- NFC and typographic quotes (' for the curly apostrophe) via core.textnorm.nfc;
- "feat." out of the artist and the title into `feat`;
- base title and version apart ("(Original)" = original, kept as no version);
- the label removed when trackid.net writes it as a co-artist ("Roll Dann, Laster Records");
- `artists` (search/verification) and `artist_display` (file names) kept consistent;
- ID and "revisar" rows unchecked; an empty title is never sent to the engine;
- a repeated track inside the set gets the note "repetida (fila N)";
- `pos` renumbered 1..n in table order.

clean_rows() is idempotent: running it again on its own output changes nothing.
"""
from __future__ import annotations

import copy
import re

from tracklister.core.model import RowStatus, TrackRow, VersionKind
from tracklister.core.textnorm import classify_version, nfc, norm_key, split_artists, split_title_version
from tracklister.inputs.tlparse import FEAT_KW, FEAT_THEN_VERSION, TRAILING_GROUPS, VERSION_KW, is_id_text

DUP_NOTE = "repetida (fila {pos})"
_DUP_PREFIX = "repetida (fila "
_FEAT_TAIL = re.compile(r"\s*[\(\[]?\s*\b(?:feat\.?|ft\.?|featuring)\s+([^()\[\]]+?)\s*[\)\]]?\s*$", re.I)
_TRAILING_GROUP = re.compile(r"\s*[\(\[]\s*([^()\[\]]*?)\s*[\)\]]\s*$")
_EXTENDED_GROUP = re.compile(r"\s*[\(\[]\s*(extended)\s*[\)\]]\s*$", re.I)
_LABEL_SUFFIX = re.compile(r"\s+(?:records|recordings|rec|music|label|digital|records ltd)$")


def renumber(rows: list[TrackRow]) -> list[TrackRow]:
    """pos = 1..n in list order (the row index is the only source of the NN prefix)."""
    for i, r in enumerate(rows, 1):
        r.pos = i
    return rows


def label_keys(label: str | None) -> set[str]:
    k = norm_key(label)
    if not k:
        return set()
    keys = {k}
    short = _LABEL_SUFFIX.sub("", k)
    if short:
        keys.add(short)
    return keys


def _join_artists(names: list[str]) -> str:
    return " & ".join(names)


def drop_label_artists(row: TrackRow) -> bool:
    """trackid.net writes the label as a co-artist: drop it (never the only artist)."""
    keys = label_keys(row.label)
    if not keys or len(row.artists) < 2:
        return False
    removed = [a for a in row.artists if norm_key(a) in keys or _LABEL_SUFFIX.sub("", norm_key(a)) in keys]
    keep = [a for a in row.artists if a not in removed]
    if not removed or not keep:
        return False
    row.artists = keep
    row.artist_display = _join_artists(keep)
    row.notes.append(f"sello quitado del artista: {', '.join(removed)}")
    return True


def _split_feat_from_artist(row: TrackRow) -> None:
    m = _FEAT_TAIL.search(row.artist_display)
    if m and m.start() > 0:
        row.feat = row.feat or m.group(1).strip()
        row.artist_display = row.artist_display[:m.start()].strip(" ,;&")
        row.artists = split_artists(row.artist_display)


def _split_title(row: TrackRow) -> None:
    """Base title and version apart, with core.textnorm.split_title_version (the same rule the
    verifier applies to file tags). Feat values are kept; other dropped groups go to the notes."""
    m = FEAT_THEN_VERSION.match(row.title)             # "Title (feat. X) Y Dub"
    if m:
        tail = TRAILING_GROUPS.match(m.group(3))
        core, groups = tail.group(1).strip(), tail.group(2)
        if core and VERSION_KW.search(core):
            row.feat = row.feat or m.group(2).strip()
            row.version = row.version or core
            row.title = m.group(1).rstrip() + groups
    m = _EXTENDED_GROUP.search(row.title)               # "(Extended)" alone is a version too
    if m and m.start() > 0:
        row.version = row.version or "Extended"
        row.title = row.title[:m.start()]
    t, dropped = row.title, []
    while True:
        g = _TRAILING_GROUP.search(t)
        if not g or g.start() == 0:
            break
        inner, t = g.group(1).strip(), t[:g.start()]
        fm = FEAT_KW.match(inner)
        if fm:
            row.feat = row.feat or fm.group(1).strip()
        elif inner and not VERSION_KW.search(inner) and classify_version(inner) != VersionKind.ORIGINAL \
                and norm_key(inner) != norm_key(row.label):
            dropped.append(inner)
    m = re.search(r"\s+(?:feat\.?|ft\.?|featuring)\s+(.+)$", t, re.I)
    if m and m.start() > 0:
        row.feat = row.feat or m.group(1).strip()
    base, version = split_title_version(row.title)
    if base:
        row.title = base
        if row.version is None and version:
            row.version = version
        for d in reversed(dropped):
            row.notes.append(f"quitado del título: ({d})")


def clean_row(row: TrackRow) -> TrackRow:
    """A cleaned COPY of one row (same uid)."""
    r = copy.deepcopy(row)
    r.title = nfc(r.title)
    r.artist_display = nfc(r.artist_display)
    r.artists = [a for a in (nfc(x) for x in r.artists) if a]
    r.version = nfc(r.version) or None
    r.feat = nfc(r.feat) or None
    r.label = nfc(r.label) or None
    if not r.is_id and r.title and is_id_text(r.title):
        r.is_id = True
    if r.artist_display and is_id_text(r.artist_display):
        r.artist_display = "ID" if r.is_id else ""
        r.artists = []
    _split_feat_from_artist(r)
    if not r.is_id:
        _split_title(r)
    if not r.artists and r.artist_display and not is_id_text(r.artist_display):
        r.artists = split_artists(r.artist_display)
    if not r.artist_display and r.artists:
        r.artist_display = _join_artists(r.artists)
    drop_label_artists(r)
    if not r.title and not r.is_id:
        r.is_id = True
        r.title = "ID"
        r.notes.append("sin título")
    if r.is_id:
        r.status, r.download, r.confidence = RowStatus.ID, False, 0.0
    elif r.status == RowStatus.REVISAR:
        r.download = False
    elif not r.artists:
        r.status, r.download = RowStatus.REVISAR, False
        r.confidence = min(r.confidence, 0.4)
        if "sin artista" not in r.notes:
            r.notes.append("sin artista")
    return r


def duplicate_key(row: TrackRow) -> str:
    kind = classify_version(row.version)
    version = "original" if kind in (VersionKind.ORIGINAL, VersionKind.EXTENDED) else norm_key(row.version)
    return f"{norm_key(row.search_artist)}|{norm_key(row.title)}|{version}"


def mark_duplicates(rows: list[TrackRow]) -> None:
    first: dict[str, int] = {}
    for r in rows:
        r.notes = [n for n in r.notes if not n.startswith(_DUP_PREFIX)]
        if r.is_id or not r.title:
            continue
        k = duplicate_key(r)
        if k in first:
            r.notes.append(DUP_NOTE.format(pos=first[k]))
        else:
            first[k] = r.pos


def clean_rows(rows: list[TrackRow]) -> list[TrackRow]:
    out = renumber([clean_row(r) for r in rows])
    mark_duplicates(out)
    return out
