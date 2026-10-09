"""Combine two sources of the same set, e.g. the trackid.net CSV + the YouTube comment.

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

02 sections 4 and 5.8: the base (trackid.net, from audio fingerprints) wins on names; the extra
source fills the "ID (hueco)" rows and adds the tracks the base missed, aligned by time (+-60 s)
and fuzzy names. Differences are written to the base row's notes, never silently applied.
On the FJAAK set this adds 1 track (Deas - Here Again) and 4 IDs.
"""
from __future__ import annotations

import copy

from rapidfuzz import fuzz

from tracklister.core.model import RowStatus, TrackRow
from tracklister.core.textnorm import norm_key
from tracklister.inputs.clean import mark_duplicates, renumber
from tracklister.inputs.trackid import GAP_TITLE

STRONG_SET, STRONG_SORT, WEAK_SET = 85, 60, 60


def _key(r: TrackRow) -> str:
    return norm_key(f"{r.artist_display} {r.title}")


def _fmt(s: int | None) -> str:
    if s is None:
        return "?"
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _dt(a: TrackRow, b: TrackRow) -> float:
    if a.ts_start is None or b.ts_start is None:
        return float("inf")
    return abs(a.ts_start - b.ts_start)


def _best_match(out: list[TrackRow], x: TrackRow, matched: set[str], tol_s: int) -> TrackRow | None:
    kx = _key(x)
    if not kx:
        return None
    best, best_rank = None, None
    for b in out:
        if b.uid in matched or b.is_id:
            continue
        kb = _key(b)
        if not kb:
            continue
        s_set = fuzz.token_set_ratio(kx, kb)
        strong = s_set >= STRONG_SET and fuzz.token_sort_ratio(kx, kb) >= STRONG_SORT
        weak = s_set >= WEAK_SET and _dt(b, x) <= tol_s
        if not (strong or weak):
            continue
        rank = (strong, s_set, -_dt(b, x))
        if best_rank is None or rank > best_rank:
            best, best_rank = b, rank
    return best


def _differs(b: TrackRow, x: TrackRow) -> bool:
    return (norm_key(b.artist_display) != norm_key(x.artist_display) or norm_key(b.title) != norm_key(x.title)
            or norm_key(b.version, drop_original=False) != norm_key(x.version, drop_original=False))


def _apply_match(b: TrackRow, x: TrackRow) -> None:
    if b.status == RowStatus.REVISAR and x.status == RowStatus.OK:
        b.notes.append(f"corregida con {x.source}: antes '{b.artist_display} - {b.title_with_version}'")
        b.artists, b.artist_display = list(x.artists), x.artist_display
        b.title, b.version, b.feat = x.title, x.version, x.feat or b.feat
        b.status, b.download, b.confidence = RowStatus.OK, True, max(b.confidence, x.confidence)
    elif _differs(b, x):
        b.notes.append(f"según {x.source}: '{x.artist_display} - {x.title_with_version}'")
    b.label = b.label or x.label
    b.feat = b.feat or x.feat
    if b.expected_duration_s is None:
        b.expected_duration_s = x.expected_duration_s
    if b.ts_start is None and x.ts_start is not None:
        b.ts_start = x.ts_start


def _gap_for(out: list[TrackRow], x: TrackRow, filled: set[str], tol_s: int) -> int | None:
    """Index of an unfilled ID row whose time span contains the extra row's start."""
    if x.ts_start is None:
        return None
    for i, b in enumerate(out):
        if not b.is_id or b.uid in filled or b.ts_start is None:
            continue
        end = b.ts_end if b.ts_end is not None else b.ts_start
        if b.ts_start - tol_s <= x.ts_start <= end + tol_s:
            return i
    return None


def _insert_index(out: list[TrackRow], x: TrackRow, anchor_uid: str | None) -> int:
    if x.ts_start is not None and any(r.ts_start is not None for r in out):
        for i, r in enumerate(out):
            if r.ts_start is not None and r.ts_start > x.ts_start:
                return i
        return len(out)
    if anchor_uid is not None:
        for i, r in enumerate(out):
            if r.uid == anchor_uid:
                return i + 1
    return 0


def merge_sources(base: list[TrackRow], extra: list[TrackRow], *, tol_s: int = 60) -> list[TrackRow]:
    out = [copy.deepcopy(r) for r in base]
    matched: set[str] = set()
    filled: set[str] = set()
    from_extra: set[str] = set()
    anchor: str | None = None
    for x in (copy.deepcopy(r) for r in extra):
        if not x.is_id:
            b = _best_match(out, x, matched, tol_s)
            if b is not None:
                _apply_match(b, x)
                matched.add(b.uid)
                anchor = b.uid
                continue
        gi = _gap_for(out, x, filled, tol_s)
        if gi is not None:
            g = out[gi]
            what = "hueco" if g.title == GAP_TITLE else "fila ID"
            x.notes.append(f"rellena un {what} de la tracklist base ({_fmt(g.ts_start)}-{_fmt(g.ts_end)})")
            if x.ts_end is None:
                x.ts_end = g.ts_end
            out[gi] = x
            filled.add(x.uid)
        else:
            x.notes.append(f"añadida desde {x.source}")
            out.insert(_insert_index(out, x, anchor), x)
        from_extra.add(x.uid)
        anchor = x.uid
    for i, r in enumerate(out):
        if r.uid in from_extra and r.ts_start is not None:
            later = next((y.ts_start for y in out[i + 1:] if y.ts_start is not None and y.ts_start > r.ts_start),
                         None)
            if later is not None and (r.ts_end is None or r.ts_end > later or r.ts_end <= r.ts_start):
                r.ts_end = later
    renumber(out)
    mark_duplicates(out)
    return out
