"""Combine two sources of the same set, e.g. the trackid.net CSV + the YouTube comment.

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

02 sections 4 and 5.8 (DECISIONES B.8, E.8, E.14): the base (trackid.net, from audio fingerprints)
wins on names; the extra source fills the "ID (hueco)" rows and adds the tracks the base missed.
Differences are written to the base row's notes, never silently applied. Matching is by fuzzy
name, or by a weaker name within +-60 s ("PAS" = "Planetary Assault Systems"). More than 60 s apart
(or when a row has no time), a fuzzy name match also needs the same numbers in the title and the same
version (CL-33, DECISIONES AA.4): «Minus 1» and «Minus 2», or «Spirit» and «Spirit (Kai Remix)», are
two tracks there.

1.0.1 (06 R2, plan §11.1): a track of the other source that matches no base row goes where its start
time puts it, between the two base rows around it:
- if that interval holds an ID row (a gap or an "ID - ID" row of the base), the track takes its place
  and its number: the one whose time span holds the start, else the nearest one by start;
- otherwise it is inserted there, in time order, and the later rows move down one number.
On the user's set this places TR440 (53:32), Border One (1:18:25) and Aidan Rudd (1:34:28). With
keep_positions=True (the set folder already holds files: decision B, D8) an insertion goes to the end
instead, with a note saying where it belongs, so no existing row changes its number.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from tracklister.core.model import RowStatus, TrackRow
from tracklister.core.textnorm import norm_key, version_key
from tracklister.inputs.clean import mark_duplicates, renumber
from tracklister.inputs.gaps import GAP_TITLE
from tracklister.verify.identity import number_tokens

STRONG_SET, STRONG_SORT, WEAK_SET = 85, 60, 60


@dataclass
class MergeResult:
    rows: list[TrackRow]
    inserted: list[str] = field(default_factory=list)      # uids put between rows: later numbers shift
    replaced_ids: list[str] = field(default_factory=list)  # uids that took an ID/gap row's place (same pos)
    appended: list[str] = field(default_factory=list)      # uids put after every row (no number changes);
    #   with keep_positions=True also the ones that belong earlier in the set (their note says where)
    matched: list[str] = field(default_factory=list)       # base uids completed by a row of the other source


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


def _same_track(b: TrackRow, x: TrackRow) -> bool:
    """The same numbers in the title and the same version: what two rows far apart in time need, besides a
    strong name match, to be one track (CL-33). 'Original Mix', 'Extended Mix' and no version are one version."""
    return (number_tokens(norm_key(b.title)) == number_tokens(norm_key(x.title))
            and version_key(b.version) == version_key(x.version))


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
        near = _dt(b, x) <= tol_s                      # a missing time is inf: far
        strong = (s_set >= STRONG_SET and fuzz.token_sort_ratio(kx, kb) >= STRONG_SORT
                  and (near or _same_track(b, x)))
        weak = s_set >= WEAK_SET and near
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


def _insert_index(out: list[TrackRow], x: TrackRow, anchor_uid: str | None) -> int:
    """v1.0 rule for a row without a time (or a base without times): after the last placed row."""
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


def _timed_track(r: TrackRow) -> bool:
    return not r.is_id and r.ts_start is not None


def _interval(out: list[TrackRow], t: int) -> tuple[int, int, bool]:
    """(lo, hi, has_next): out[lo:hi] lies between `prev`, the last track with start <= t, and `next`,
    the first track with start > t (table order; ID rows are never prev/next)."""
    nxt = next((i for i, r in enumerate(out) if _timed_track(r) and r.ts_start > t), None)
    hi = nxt if nxt is not None else len(out)
    prv = next((j for j in range(hi - 1, -1, -1) if _timed_track(out[j]) and out[j].ts_start <= t), None)
    return (prv + 1 if prv is not None else 0), hi, nxt is not None


def _id_to_replace(out: list[TrackRow], x: TrackRow, lo: int, hi: int, protected: set[str],
                   tol_s: int) -> int | None:
    """The base ID row of out[lo:hi] that x replaces: the one whose span holds x's start, else the
    nearest by start (an ID row without a time comes last)."""
    ids = [i for i in range(lo, hi) if out[i].is_id and out[i].uid not in protected]
    if not ids:
        return None
    t = x.ts_start
    for i in ids:
        r = out[i]
        if r.ts_start is not None:
            end = r.ts_end if r.ts_end is not None else r.ts_start
            if r.ts_start - tol_s <= t <= end + tol_s:
                return i
    return min(ids, key=lambda i: abs(out[i].ts_start - t) if out[i].ts_start is not None else float("inf"))


def _time_slot(out: list[TrackRow], x: TrackRow, lo: int, hi: int, has_next: bool) -> int:
    """Where x goes inside out[lo:hi] by time: before the first later row; with no `next`, right after
    the last timed row (rows without a time stay after it)."""
    if has_next:
        return next((i for i in range(lo, hi) if out[i].ts_start is not None and out[i].ts_start > x.ts_start),
                    hi)
    last = next((i for i in range(hi - 1, lo - 1, -1) if out[i].ts_start is not None
                 and out[i].ts_start <= x.ts_start), None)
    first_later = next((i for i in range(lo, hi) if out[i].ts_start is not None and out[i].ts_start > x.ts_start),
                       None)
    if first_later is not None:
        return first_later
    return last + 1 if last is not None else lo


def _place(out: list[TrackRow], x: TrackRow, res: MergeResult, protected: set[str], anchor: str | None,
           tol_s: int, keep_positions: bool) -> None:
    pos = None
    if x.ts_start is not None and any(_timed_track(r) for r in out):
        lo, hi, has_next = _interval(out, x.ts_start)
        gi = _id_to_replace(out, x, lo, hi, protected, tol_s)
        if gi is not None:
            g = out[gi]
            what = "hueco" if g.title == GAP_TITLE else "fila ID"
            x.notes.append(f"rellena un {what} de la tracklist base ({_fmt(g.ts_start)}-{_fmt(g.ts_end)})")
            if x.ts_end is None:
                x.ts_end = g.ts_end
            out[gi] = x
            res.replaced_ids.append(x.uid)
            return
        pos = _time_slot(out, x, lo, hi, has_next)
    else:
        pos = _insert_index(out, x, anchor)
    if pos >= len(out):
        x.notes.append(f"añadida desde {x.source}")
        out.append(x)
        res.appended.append(x.uid)
    elif keep_positions:
        where = f"después de «{out[pos - 1].title}»" if pos > 0 else "al principio"
        x.notes.append(f"añadida al final para no cambiar números: en el set va {where}")
        out.append(x)
        res.appended.append(x.uid)
    else:
        x.notes.append(f"añadida desde {x.source}")
        out.insert(pos, x)
        res.inserted.append(x.uid)


def merge_sources_detailed(base: list[TrackRow], extra: list[TrackRow], *, tol_s: int = 60,
                           keep_positions: bool = False) -> MergeResult:
    """Copies of the base rows with the other source merged in (the inputs are never modified),
    renumbered 1..n and with repeated tracks marked."""
    out = [copy.deepcopy(r) for r in base]
    res = MergeResult(rows=out)
    matched: set[str] = set()
    from_extra: set[str] = set()          # rows of the other source: never replaced by another of them
    anchor: str | None = None
    for x in (copy.deepcopy(r) for r in extra):
        if not x.is_id:
            b = _best_match(out, x, matched, tol_s)
            if b is not None:
                _apply_match(b, x)
                matched.add(b.uid)
                res.matched.append(b.uid)
                anchor = b.uid
                continue
        _place(out, x, res, from_extra, anchor, tol_s, keep_positions)
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
    return res


def merge_sources(base: list[TrackRow], extra: list[TrackRow], *, tol_s: int = 60) -> list[TrackRow]:
    return merge_sources_detailed(base, extra, tol_s=tol_s).rows
