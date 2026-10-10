"""The CSV exported by trackid.net: Pos,Start,End,Artist,Title,Label.

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

trackid.net has no duration and no version column (the remix is inside Title), sometimes writes
the label as a co-artist ("Roll Dann, Laster Records") and leaves undetected stretches as plain
gaps. Stretches that no track can cover for more than the threshold (90 s, 02 section 5.7) become
unchecked "ID (hueco)" rows: see inputs/gaps.py. Start/End are when trackid.net heard each track, not
how long it lasts; an optional Duración column (h:mm:ss or m:ss) gives the real length.
"""
from __future__ import annotations

import csv
import io
import re

from tracklister.core.model import TrackRow
from tracklister.core.textnorm import nfc, split_artists, split_title_version
from tracklister.inputs.clean import drop_label_artists, renumber
from tracklister.inputs.gaps import (  # noqa: F401  (re-exported: the v1.0 names)
    ESTIMATED_NOTE, GAP_TITLE, SOURCE, gap_row, insert_gaps, typical_play_s,
)
from tracklister.inputs.tabular import RawTable

TRACKID_HEADERS = ("Pos", "Start", "End", "Artist", "Title", "Label")
REQUIRED = ("start", "end", "artist", "title")
DURATION_KEYS = ("duracion", "duración", "duration", "length")
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


def parse_trackid(t: RawTable, *, gap_threshold_s: int = 90) -> list[TrackRow]:
    """The track rows in Pos order, then the "ID (hueco)" rows of inputs/gaps.insert_gaps (also before
    the first track: the set starts at 0:00). Without durations that is the v1.0 rule: a gap is measured
    from the previous End, or from the set's median play time when a row has no End (that gap row says
    it is an estimate). A Duración column gives the real length (kept as the user's own duration, E.23),
    and then the gap is what the track cannot cover even if it played in full."""
    idx: dict[str, int] = {}
    for i, h in enumerate(t.headers):
        idx.setdefault(header_key(h), i)

    def cell(cells: list[str], name: str) -> str:
        i = idx.get(name)
        return cells[i].strip() if i is not None and i < len(cells) else ""

    dur_key = next((k for k in DURATION_KEYS if k in idx), None)
    items = order_by_pos(t.rows, lambda c: parse_int(cell(c, "pos")))
    rows: list[TrackRow] = []
    for cells in items:
        artist, title, label = nfc(cell(cells, "artist")), nfc(cell(cells, "title")), nfc(cell(cells, "label"))
        if not artist and not title:
            continue
        start, end = parse_hms(cell(cells, "start")), parse_hms(cell(cells, "end"))
        dur = parse_hms(cell(cells, dur_key)) if dur_key else None
        base, version = split_title_version(title)
        row = TrackRow(pos=0, title=base or title, artists=split_artists(artist), artist_display=artist,
                       version=version, label=label or None, ts_start=start, ts_end=end, source=SOURCE,
                       expected_duration_s=dur or None, confidence=0.7, raw=raw_line(cells, t.delimiter))
        drop_label_artists(row)
        rows.append(row)
    return renumber(insert_gaps(rows, threshold_s=gap_threshold_s))
