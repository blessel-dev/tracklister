"""The user's own Excel/CSV: guess which column is which (Spanish and English names).

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

v1 needed exact "Artist"/"Title" headers and broke on a missing Pos (01 section 3, P3.4).
Here a missing Pos means table order, an empty title becomes an ID row that is never sent to
the engine, and one "Artista - Titulo" column is parsed like pasted text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from tracklister.core.model import RowStatus, TrackRow
from tracklister.core.textnorm import merge_versions, nfc, split_artists, strip_accents
from tracklister.inputs.tabular import RawTable
from tracklister.inputs.tlparse import is_id_text, needs_review, parse_line
from tracklister.inputs.trackid import length_of, order_by_pos, parse_hms, parse_int, raw_line


@dataclass
class ColumnMapping:
    artist: int | None
    title: int | None
    version: int | None = None
    label: int | None = None
    start: int | None = None
    pos: int | None = None
    length: int | None = None
    combined: int | None = None   # "Artist - Title" in one column

    def is_usable(self) -> bool:
        return self.combined is not None or self.title is not None


ALIASES: dict[str, tuple[str, ...]] = {
    "pos": ("pos", "#", "no", "n", "no.", "n.", "nº", "n°", "num", "num.", "numero", "number", "position",
            "posicion", "orden", "order", "track no", "track number", "track #", "pista #"),
    "artist": ("artist", "artists", "artista", "artistas", "interprete", "interpretes", "autor", "autores",
               "performer", "artist name", "artist(s)", "artista(s)", "artiste", "kunstler", "interpret"),
    "title": ("title", "titulo", "track title", "track name", "song", "song title", "cancion", "tema",
              "pista", "name", "nombre", "track", "titulo de la pista", "titre", "titel", "titolo"),
    "version": ("version", "mix", "remix", "mix name", "mezcla", "version / remix"),
    "label": ("label", "sello", "discografica", "record label", "publisher", "editorial"),
    "start": ("start", "start time", "inicio", "time", "tiempo", "timestamp", "minuto", "cue", "hora",
              "empieza"),
    "length": ("length", "duration", "duracion", "len", "dur", "track length", "tiempo total"),
    "combined": ("artist - title", "artista - titulo", "tracklist", "track list", "canciones", "pistas",
                 "artist / title", "artista / titulo"),
}
_ORDER = ("pos", "artist", "title", "version", "label", "start", "length", "combined")


def header_norm(h: str) -> str:
    s = strip_accents(nfc(h)).lower().strip().rstrip(":")
    return re.sub(r"[\s_]+", " ", s).strip()


def guess_mapping(headers: list[str]) -> ColumnMapping:
    """Exact alias match first, then a word match for artist/title ("Main Artist", "Song Name")."""
    norm = [header_norm(h) for h in headers]
    used: set[int] = set()
    found: dict[str, int] = {}
    for fld in _ORDER:
        aliases = {header_norm(a) for a in ALIASES[fld]}
        for i, h in enumerate(norm):
            if i not in used and h in aliases:
                found[fld] = i
                used.add(i)
                break
    for fld, words in (("artist", ("artist", "artista", "interprete")), ("title", ("title", "titulo", "song"))):
        if fld in found:
            continue
        for i, h in enumerate(norm):
            if i not in used and any(w in h.split() for w in words):
                found[fld] = i
                used.add(i)
                break
    m = ColumnMapping(artist=found.get("artist"), title=found.get("title"), version=found.get("version"),
                      label=found.get("label"), start=found.get("start"), pos=found.get("pos"),
                      length=found.get("length"), combined=found.get("combined"))
    if m.artist is None and m.combined is None and m.title is not None:
        m.combined, m.title = m.title, None      # one "Track" column: "Artist - Title" per cell
    return m


_AMBIGUOUS_TIME = {"time", "tiempo", "hora"}


def refine_mapping(t: RawTable, m: ColumnMapping) -> ColumnMapping:
    """A column called just "Time"/"Tiempo" is the start in the set when its values grow past
    20 minutes, and the track length otherwise (DJ software exports "Time" = length)."""
    if m.start is None or m.length is not None or header_norm(t.headers[m.start]) not in _AMBIGUOUS_TIME:
        return m
    values = [v for v in (parse_hms(r[m.start]) for r in t.rows if m.start < len(r)) if v is not None]
    rising = all(b >= a for a, b in zip(values, values[1:]))
    if values and not (rising and max(values) > 20 * 60):
        m.length, m.start = m.start, None
    return m


def _row_from_text(text: str, source: str) -> list[TrackRow]:
    lines = parse_line(text)
    if not lines:
        return [TrackRow(pos=0, title=text, source=source, confidence=0.4, status=RowStatus.REVISAR,
                         download=False, notes=["sin separador artista-titulo"], raw=text)]
    out = []
    for ln in lines:
        review = needs_review(ln)
        out.append(TrackRow(
            pos=0, title=ln.title, artists=list(ln.artists), artist_display=ln.artist, version=ln.version,
            feat=ln.feat, label=ln.label, ts_start=ln.ts, source=source, is_id=ln.is_id,
            confidence=0.0 if ln.is_id else (0.4 if review else 0.7),
            status=RowStatus.ID if ln.is_id else (RowStatus.REVISAR if review else RowStatus.OK),
            download=not (ln.is_id or review), notes=list(ln.notes), raw=text))
    return out


def rows_from_table(t: RawTable, m: ColumnMapping, source: str = "tabla") -> list[TrackRow]:
    """Missing or partial Pos -> table order. Empty title -> ID row (never sent to the engine)."""

    def cell(cells: list[str], i: int | None) -> str:
        return nfc(cells[i]) if i is not None and i < len(cells) else ""

    items = order_by_pos(t.rows, lambda c: parse_int(cell(c, m.pos))) if m.pos is not None else list(t.rows)
    rows: list[TrackRow] = []
    for cells in items:
        raw = raw_line(cells, t.delimiter)
        start = parse_hms(cell(cells, m.start))
        length, length_note = length_of(cell(cells, m.length))
        version, label = cell(cells, m.version) or None, cell(cells, m.label) or None
        if m.combined is not None:
            text = cell(cells, m.combined)
            if not text:
                continue
            new = _row_from_text(text, source)
        else:
            artist, title = cell(cells, m.artist), cell(cells, m.title)
            if not artist and not title:
                if not any(c.strip() for c in cells):
                    continue
                artist, title = "", ""
            is_id = not title or is_id_text(title)
            new = [TrackRow(pos=0, title=title or "ID", artists=split_artists(artist), artist_display=artist,
                            source=source, is_id=is_id, confidence=0.0 if is_id else 0.7,
                            status=RowStatus.ID if is_id else RowStatus.OK, download=not is_id,
                            notes=["sin título"] if not title else [])]
        for r in new:
            r.raw = raw
            # the Version/Mix column is one more version group, right of the title's (round 4, 2nd review)
            r.version = merge_versions([r.version, version])
            r.label = r.label or label
            if r.ts_start is None:
                r.ts_start = start
            if length and not r.is_id:
                r.expected_duration_s = length
                if length_note:
                    r.notes.append(length_note)
        rows.extend(new)
    for i, r in enumerate(rows, 1):
        r.pos = i
    return rows
