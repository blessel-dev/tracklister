"""'ID (hueco)' rows: the stretches of a trackid.net set that no row can cover (06 R1, plan §11.1).

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

trackid.net's End is when it STOPPED RECOGNISING a track, not when the DJ took it out (the user, 10
Oct). So a track row covers the set up to `start + expected duration` (the duration comes from the
enrichment or from a Duración column). For a trackid row with a real End it is `max(start + duration,
End)`: a store duration shorter than what trackid heard (a radio edit picked by mistake) must not invent
a gap. Without a duration the v1.0 fallbacks apply: the End, then the set's median play time.

    unexplained = next.start - covered          -> an "ID (hueco)" row only when it is over 90 s

The set starts at 0:00, so a gap before the first track counts too. Gaps are only computed for tables
that hold trackid.net rows: a pure YouTube or pasted list has no gap rows.

recompute_gaps() runs after the enrichment is applied (DECISIONES X): it drops the automatic gap rows
the new durations no longer support, adds the new ones and renumbers. It never touches a gap or ID row
the user has edited or checked (is_auto_gap() is False for those). The caller makes sure the set has
never been downloaded: once the set folder holds files, the numbers are the file names (decision B).
"""
from __future__ import annotations

import copy
from collections.abc import Collection
from dataclasses import dataclass

from tracklister.core.model import RowStatus, TrackRow
from tracklister.inputs.clean import renumber

GAP_TITLE = "ID (hueco)"
SOURCE = "trackid_csv"
ESTIMATED_NOTE = "estimado: la pista anterior no tiene hora de fin en el CSV"
DEFAULT_THRESHOLD_S = 90


def clock(s: int) -> str:
    """253 -> '4:13'; 3880 -> '1:04:40'."""
    s = max(0, int(s))
    if s >= 3600:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def is_auto_gap(row: TrackRow) -> bool:
    """A gap row exactly as the importer made it. Anything else (an artist or title typed in, the box
    checked, another source) is the user's or a real track's row and is never touched."""
    return (row.is_id and row.title == GAP_TITLE and not row.artist_display and not row.artists
            and not row.download and row.source == SOURCE)


def typical_play_s(spans: list[tuple[int | None, int | None]]) -> int | None:
    """Median time a track of THIS set plays (End - Start of the rows that have both)."""
    plays = sorted(e - s for s, e in spans if s is not None and e is not None and e > s)
    return plays[len(plays) // 2] if plays else None


def set_median_play_s(rows: list[TrackRow]) -> int | None:
    """The v1.0 median: trackid.net rows (real Start/End pairs) only."""
    return typical_play_s([(r.ts_start, r.ts_end) for r in rows if r.source == SOURCE and not is_auto_gap(r)])


def covered_until(row: TrackRow, median_s: int | None = None) -> tuple[int | None, str]:
    """(second up to which the row accounts for the set, how) with how in
    {"duracion", "fin", "mediana", ""}. Rows of other sources carry a synthetic End (the next start),
    so only a trackid.net End is weighed against the duration."""
    start, end, dur = row.ts_start, row.ts_end, row.expected_duration_s
    if start is not None and dur:
        covered = start + int(dur)
        if row.source == SOURCE and end is not None and end > covered:
            covered = end
        return covered, "duracion"
    if end is not None:
        return end, "fin"
    if start is not None and median_s:
        return start + median_s, "mediana"
    return None, ""


def _gap_notes(start: int, end: int, how: str, prev: TrackRow | None) -> list[str]:
    n = end - start
    title = (prev.title if prev is not None else "") or "la pista anterior"
    if how == "duracion" and prev is not None:
        return [f"{clock(n)} sin cubrir aunque «{title}» sonara entero",
                f"«{title}» dura {clock(prev.expected_duration_s or 0)} y empieza en {clock(prev.ts_start or 0)}: "
                f"llega hasta {clock(start)}; la siguiente pista empieza en {clock(end)}"]
    if how == "fin" and prev is not None:
        if prev.source == SOURCE:
            return [f"hueco de {n} s sin identificar en trackid.net (sin duración de «{title}»: se mide desde "
                    "su hora de fin)"]
        return [f"hueco de {n} s sin identificar (sin duración de «{title}»: se mide desde su hora de fin)"]
    if how == "mediana":
        return [f"hueco de {n} s sin identificar en trackid.net", ESTIMATED_NOTE]
    return [f"hueco de {n} s al principio del set"]


def gap_row(start: int, end: int, how: str = "inicio", prev: TrackRow | None = None) -> TrackRow:
    return TrackRow(pos=0, title=GAP_TITLE, artists=[], artist_display="", ts_start=start, ts_end=end,
                    source=SOURCE, confidence=0.0, is_id=True, status=RowStatus.ID, download=False,
                    notes=_gap_notes(start, end, how, prev))


def insert_gaps(rows: list[TrackRow], *, threshold_s: int = DEFAULT_THRESHOLD_S) -> list[TrackRow]:
    """The rows in table order with fresh automatic gap rows (old automatic ones are left out), not
    renumbered. The chain is every other row with a start time, in table order; a row without one is
    kept where it is and skipped. Gap rows are new objects; the other rows are the same objects."""
    base = [r for r in rows if not is_auto_gap(r)]
    median = set_median_play_s(base)
    out: list[TrackRow] = []
    covered: int | None = 0                 # the set is accounted for up to here: it starts at 0:00
    how, prev = "inicio", None
    for r in base:
        if r.ts_start is None:
            out.append(r)
            continue
        if covered is not None and r.ts_start - covered > threshold_s:
            out.append(gap_row(covered, r.ts_start, how, prev))
        out.append(r)
        c, h = covered_until(r, median)
        if c is None:
            covered, how, prev = None, "", None      # nothing to measure the next gap from
        elif covered is None or c >= covered:
            covered, how, prev = c, h, r
    return out


@dataclass
class GapRecompute:
    rows: list[TrackRow]
    added: int
    removed: int
    changed: bool


def _neighbour(rows: list[TrackRow], i: int, step: int) -> str | None:
    j = i + step
    while 0 <= j < len(rows):
        if not is_auto_gap(rows[j]):
            return rows[j].uid
        j += step
    return None


GapKey = tuple[str | None, str | None]


def gap_key(rows: list[TrackRow], i: int) -> GapKey:
    """Where a gap row sits, in a way that survives renumbering: (uid of the row before it, uid of the
    row after it), automatic gap rows skipped. The window keeps the keys of the gap rows the user
    deletes and passes them back as `dismissed`, so a deleted gap does not come back."""
    return _neighbour(rows, i, -1), _neighbour(rows, i, 1)


def recompute_gaps(rows: list[TrackRow], *, threshold_s: int = DEFAULT_THRESHOLD_S,
                   dismissed: Collection[GapKey] = ()) -> GapRecompute:
    """Automatic gap rows again, with the durations the rows have now. A no-op (changed=False, the same
    list) unless a row comes from trackid.net. An automatic gap that ends up between the same two rows
    keeps its uid (only its times and notes change). A gap the rule supports in a slot of `dismissed`
    is not added again (the user deleted it). Never edits the input rows: when something changes the
    result holds copies, renumbered."""
    if not any(r.source == SOURCE and not is_auto_gap(r) for r in rows):
        return GapRecompute(rows, 0, 0, False)
    work = [copy.deepcopy(r) for r in rows]
    old: dict[GapKey, list[TrackRow]] = {}
    n_old = 0
    for i, r in enumerate(work):
        if is_auto_gap(r):
            old.setdefault(gap_key(work, i), []).append(r)
            n_old += 1
    fresh = insert_gaps(work, threshold_s=threshold_s)
    dismissed = set(dismissed)
    keep: list[TrackRow] = []
    added = kept = 0
    for i, r in enumerate(fresh):
        if is_auto_gap(r):
            key = gap_key(fresh, i)
            same_place = old.get(key)
            if same_place:
                r.uid = same_place.pop(0).uid
                kept += 1
            elif key in dismissed:
                continue
            else:
                added += 1
        keep.append(r)
    renumber(keep)
    changed = [r.to_dict() for r in keep] != [r.to_dict() for r in rows]
    return GapRecompute(keep if changed else rows, added, n_old - kept, changed)
