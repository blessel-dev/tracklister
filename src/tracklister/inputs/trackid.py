"""The CSV exported by trackid.net: Pos,Start,End,Artist,Title,Label.

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

trackid.net has no duration and no version column (the remix is inside Title), sometimes writes
the label as a co-artist ("Roll Dann, Laster Records") and leaves undetected stretches as plain
gaps. Gaps longer than the threshold (90 s, 02 section 5.7) become unchecked "ID (hueco)" rows.
"""
from __future__ import annotations

import csv
import io
import re

from tracklister.core.model import RowStatus, TrackRow
from tracklister.core.textnorm import nfc, split_artists, split_title_version
from tracklister.inputs.clean import drop_label_artists, renumber
from tracklister.inputs.tabular import RawTable

TRACKID_HEADERS = ("Pos", "Start", "End", "Artist", "Title", "Label")
REQUIRED = ("start", "end", "artist", "title")
GAP_TITLE = "ID (hueco)"
SOURCE = "trackid_csv"
_HMS = re.compile(r"^(\d{1,3}):(\d{1,2})(?::(\d{1,2}))?(?:[.,]\d+)?$")


def header_key(h: str) -> str:
    return re.sub(r"[\s_]+", "", h or "").lower()


def is_trackid_table(t: RawTable) -> bool:
    """By column names, case- and space-insensitive (Pos and Label are optional)."""
    keys = {header_key(h) for h in t.headers}
    return all(k in keys for k in REQUIRED)


def parse_hms(s: str | None) -> int | None:
    """'00:01:17' -> 77, '1:17' -> 77, '77' -> 77; anything else -> None."""
    s = (s or "").strip()
    if not s:
        return None
    m = _HMS.match(s)
    if m:
        a, b, c = int(m.group(1)), int(m.group(2)), m.group(3)
        return a * 3600 + b * 60 + int(c) if c is not None else a * 60 + b
    return int(s) if s.isdigit() else None


def parse_int(s: str | None) -> int | None:
    s = (s or "").strip()
    try:
        f = float(s.replace(",", "."))
    except ValueError:
        return None
    return int(f) if f.is_integer() else None


def raw_line(cells: list[str], delimiter: str | None) -> str:
    buf = io.StringIO()
    csv.writer(buf, delimiter=delimiter or ",", lineterminator="").writerow(cells)
    return buf.getvalue()


def order_by_pos(items: list, pos_of) -> list:
    """Sort by the Pos column only when every row has a valid, unique Pos; else table order."""
    pos = [pos_of(it) for it in items]
    if items and all(p is not None for p in pos) and len(set(pos)) == len(pos):
        return [it for _, it in sorted(zip(pos, items), key=lambda x: x[0])]
    return list(items)


ESTIMATED_NOTE = "estimado: la pista anterior no tiene hora de fin en el CSV"


def gap_row(start: int, end: int, *, estimated: bool = False) -> TrackRow:
    notes = [f"hueco de {end - start} s sin identificar en trackid.net"]
    if estimated:
        notes.append(ESTIMATED_NOTE)
    return TrackRow(pos=0, title=GAP_TITLE, artists=[], artist_display="", ts_start=start, ts_end=end,
                    source=SOURCE, confidence=0.0, is_id=True, status=RowStatus.ID, download=False,
                    notes=notes)


def typical_play_s(spans: list[tuple[int | None, int | None]]) -> int | None:
    """Median time a track of THIS set plays (End - Start of the rows that have both)."""
    plays = sorted(e - s for s, e in spans if s is not None and e is not None and e > s)
    return plays[len(plays) // 2] if plays else None


def parse_trackid(t: RawTable, *, gap_threshold_s: int = 90) -> list[TrackRow]:
    """Gaps longer than the threshold become "ID (hueco)" rows, also before the first track (the set
    starts at 0:00). A row without an End time is taken to play for the set's typical (median) track
    time, so the gap after it is still found; that gap row says it is an estimate."""
    idx: dict[str, int] = {}
    for i, h in enumerate(t.headers):
        idx.setdefault(header_key(h), i)

    def cell(cells: list[str], name: str) -> str:
        i = idx.get(name)
        return cells[i].strip() if i is not None and i < len(cells) else ""

    items = order_by_pos(t.rows, lambda c: parse_int(cell(c, "pos")))
    typical = typical_play_s([(parse_hms(cell(c, "start")), parse_hms(cell(c, "end"))) for c in items])
    rows: list[TrackRow] = []
    covered: int | None = 0          # the set is accounted for up to here (it starts at 0:00)
    estimated = False
    for cells in items:
        artist, title, label = nfc(cell(cells, "artist")), nfc(cell(cells, "title")), nfc(cell(cells, "label"))
        if not artist and not title:
            continue
        start, end = parse_hms(cell(cells, "start")), parse_hms(cell(cells, "end"))
        if covered is not None and start is not None and start - covered > gap_threshold_s:
            rows.append(gap_row(covered, start, estimated=estimated))
        base, version = split_title_version(title)
        row = TrackRow(pos=0, title=base or title, artists=split_artists(artist), artist_display=artist,
                       version=version, label=label or None, ts_start=start, ts_end=end, source=SOURCE,
                       confidence=0.7, raw=raw_line(cells, t.delimiter))
        drop_label_artists(row)
        rows.append(row)
        if end is not None:
            if covered is None or end >= covered:
                covered, estimated = end, False
        elif start is not None and typical is not None:
            # no End: assume the set's typical play time, so the next gap is still measured
            covered, estimated = max(covered or 0, start + typical), True
        else:
            covered, estimated = None, False     # nothing to measure the next gap from
    return renumber(rows)
