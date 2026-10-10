"""'ID (hueco)' rows from real durations (06 R1): what a track cannot cover even if it played in full.

The user's set (tests/fixtures/inputs/setaoc-trackid.csv, his trackid.net export of a public DJ set) and
the 12 durations his own app enriched at home (06, "Durations his app enriched").
"""
from __future__ import annotations

from pathlib import Path

from tracklister.core.model import RowStatus, TrackRow
from tracklister.inputs.gaps import (
    ESTIMATED_NOTE, GAP_TITLE, clock, covered_until, insert_gaps, is_auto_gap, recompute_gaps,
)
from tracklister.inputs.importer import import_source
from tracklister.inputs.tabular import RawTable, read_table
from tracklister.inputs.trackid import parse_trackid

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "inputs"
SETAOC = FIX / "setaoc-trackid.csv"
FJAAK = FIX / "fjaak-techno-dj-set-section-may-2026.csv"

# 06: "Durations his app enriched" (m:ss)
HOME_DURATIONS = {"Inject": "4:21", "Trip": "5:05", "Show me that light": "6:25", "Seiko": "5:32",
                  "Hidden Reason": "5:33", "Dynamic": "5:19", "Velocity": "6:25", "Interchange III": "6:45",
                  "Lx2": "7:38", "Binary Drive": "5:23", "Twinfall": "5:23", "Space Noise": "5:16"}


def _s(mmss: str) -> int:
    m, s = mmss.split(":")
    return int(m) * 60 + int(s)


def _gaps(rows: list[TrackRow]) -> list[tuple[str, int, int]]:
    """(title of the track before, start, end) of every automatic gap row."""
    out = []
    for i, r in enumerate(rows):
        if is_auto_gap(r):
            before = next((p.title for p in reversed(rows[:i]) if not is_auto_gap(p)), "")
            out.append((before, r.ts_start, r.ts_end))
    return out


def _with_home_durations(rows: list[TrackRow]) -> list[TrackRow]:
    for r in rows:
        if r.title in HOME_DURATIONS:
            r.expected_duration_s, r.enrich_source = _s(HOME_DURATIONS[r.title]), "itunes"
    return rows


def test_without_durations_the_v10_rule_stays():
    rows = parse_trackid(read_table(FJAAK))
    assert [(r.ts_start, r.ts_end) for r in rows if is_auto_gap(r)] == [(1158, 1282), (1587, 1808), (2347, 2847),
                                                                         (3018, 3207)]
    again = recompute_gaps(rows)
    assert not again.changed and again.rows is rows and (again.added, again.removed) == (0, 0)
    setaoc = import_source(SETAOC).rows                 # End-based: the 9 gaps 1.0.0 gave him
    assert [g[0] for g in _gaps(setaoc)] == ["Inject", "Trip", "Seiko", "Hidden Reason", "Twinfall", "Blind Spot",
                                             "Crux", "Incentive Systems", "Talitha"]
    assert len(setaoc) == 30


def test_his_set_with_the_enriched_durations():
    """06 R1 acceptance: no gap after Inject, Seiko or Hidden Reason; the gap after Trip (253 s) stays,
    and so does the one after Twinfall (92 s), where his YouTube list has TR440."""
    rows = _with_home_durations(import_source(SETAOC).rows)
    res = recompute_gaps(rows)
    assert res.changed and res.removed == 3 and res.added == 0
    gaps = {before: (start, end) for before, start, end in _gaps(res.rows)}
    assert not {"Inject", "Seiko", "Hidden Reason"} & set(gaps)
    assert gaps["Trip"] == (334 + 305, 892) and 892 - 639 == 253
    assert gaps["Twinfall"] == (3000 + 323, 3415) and 3415 - 3323 == 92
    # no duration for these four in the brief's list: measured from trackid's End, as in v1.0
    assert set(gaps) == {"Trip", "Twinfall", "Blind Spot", "Crux", "Incentive Systems", "Talitha"}
    assert gaps["Blind Spot"] == (3880, 4851)                    # End 1:04:40 -> Space 1:20:51
    assert [r.pos for r in res.rows] == list(range(1, len(res.rows) + 1)) and len(res.rows) == 27


def test_gap_notes_explain_the_computation():
    rows = recompute_gaps(_with_home_durations(import_source(SETAOC).rows)).rows
    trip_gap = next(r for r in rows if is_auto_gap(r) and r.ts_start == 639)
    assert trip_gap.notes[0] == "4:13 sin cubrir aunque «Trip» sonara entero"
    assert trip_gap.notes[1] == ("«Trip» dura 5:05 y empieza en 5:34: llega hasta 10:39; "
                                 "la siguiente pista empieza en 14:52")
    blind = next(r for r in rows if is_auto_gap(r) and r.ts_start == 3880)
    assert blind.notes == ["hueco de 971 s sin identificar en trackid.net (sin duración de «Blind Spot»: "
                           "se mide desde su hora de fin)"]
    for g in (trip_gap, blind):
        assert g.title == GAP_TITLE and g.is_id and not g.download and g.status == RowStatus.ID
        assert g.confidence == 0 and g.artists == [] and g.artist_display == "" and g.source == "trackid_csv"
    assert clock(253) == "4:13" and clock(3880) == "1:04:40" and clock(0) == "0:00"


def test_duration_column_of_the_csv_is_used_and_kept_as_the_users():
    headers = ["#", "Start", "End", "Artist", "Title", "Label", "Duración"]
    t = RawTable(headers=headers, encoding="utf-8", delimiter=",", sheet=None, rows=[
        ["1", "00:00:02", "00:01:47", "Komplex aka Jeroen Search", "Inject", "Basic Beat", "4:21"],
        ["2", "00:05:34", "00:08:43", "Red Rooms", "Trip", "Phorum Records", "0:05:05"],
        ["3", "00:14:52", "00:16:42", "Kwartz", "Show me that light (Cleric Remix)", "Clergy", ""]])
    rows = parse_trackid(t)
    inject, trip = rows[0], rows[1]
    assert (inject.expected_duration_s, inject.enrich_source) == (261, None)     # E.23: the user's own
    assert trip.expected_duration_s == 305
    assert [r.title for r in rows] == ["Inject", "Trip", GAP_TITLE, "Show me that light"]
    assert rows[2].notes[0] == "4:13 sin cubrir aunque «Trip» sonara entero"
    for key in ("Duration", "duracion", "LENGTH"):
        t2 = RawTable(headers=headers[:-1] + [key], rows=t.rows, encoding="utf-8", delimiter=",", sheet=None)
        assert parse_trackid(t2)[0].expected_duration_s == 261


def test_a_short_store_duration_never_invents_a_gap():
    """D3: for a trackid row the End still counts; a radio edit picked by mistake (2:00) must not
    open a gap while trackid heard the track until 8:00."""
    t = RawTable(headers=["Start", "End", "Artist", "Title"], encoding="utf-8", delimiter=",", sheet=None,
                 rows=[["00:01:00", "00:08:00", "A", "One"], ["00:09:00", "00:12:00", "B", "Two"]])
    rows = parse_trackid(t)
    rows[0].expected_duration_s = 120
    assert covered_until(rows[0]) == (480, "duracion")
    assert not recompute_gaps(rows).changed


def _row(title, start, end=None, dur=None, source="trackid_csv", **kw) -> TrackRow:
    return TrackRow(pos=0, title=title, artists=[title[0]], artist_display=title[0], ts_start=start, ts_end=end,
                    expected_duration_s=dur, source=source, **kw)


def test_fallbacks_end_median_and_set_start():
    rows = insert_gaps([_row("Uno", 200, 300), _row("Dos", 500, 650), _row("Tres", 700),
                        _row("Cuatro", 1000, None, 120), _row("Cinco", 1300, 1400)])
    gaps = [(r.ts_start, r.ts_end, r.notes) for r in rows if is_auto_gap(r)]
    assert gaps[0] == (0, 200, ["hueco de 200 s al principio del set"])
    assert gaps[1][:2] == (300, 500) and "se mide desde su hora de fin" in gaps[1][2][0]
    # «Tres» has no End and no duration: the median of the set (100 s)
    assert gaps[2][:2] == (800, 1000) and gaps[2][2] == ["hueco de 200 s sin identificar en trackid.net",
                                                         ESTIMATED_NOTE]
    assert gaps[3][:2] == (1120, 1300) and gaps[3][2][0] == "3:00 sin cubrir aunque «Cuatro» sonara entero"
    # no End anywhere and no duration: nothing to measure from, no gap is invented
    assert not any(is_auto_gap(r) for r in insert_gaps([_row("Uno", 30), _row("Dos", 1800)]))


def test_rows_without_a_start_do_not_break_the_chain_and_overlaps_keep_the_furthest():
    untimed = _row("Sin hora", None, source="tabla")
    rows = insert_gaps([_row("Larga", 0, 100, 600), _row("Corta", 300, 350), untimed, _row("Siguiente", 650, 700)])
    assert [r.title for r in rows] == ["Larga", "Corta", "Sin hora", "Siguiente"]      # 600 covers past 350


def test_user_edited_or_checked_gap_rows_are_never_touched():
    rows = import_source(SETAOC).rows                     # 9 gaps (End-based)
    after_inject = next(r for r in rows if is_auto_gap(r) and r.ts_start == 107)
    after_seiko = next(r for r in rows if is_auto_gap(r) and r.ts_start == 1218)
    after_inject.download = True                          # the user checked it
    after_seiko.artist_display, after_seiko.artists = "Phil Berg", ["Phil Berg"]   # the user typed an artist
    assert not is_auto_gap(after_inject) and not is_auto_gap(after_seiko)
    res = recompute_gaps(_with_home_durations(rows))
    kept = {r.uid for r in res.rows}
    assert after_inject.uid in kept and after_seiko.uid in kept
    assert res.removed == 1                               # only the untouched one after Hidden Reason
    edited = next(r for r in res.rows if r.uid == after_seiko.uid)
    assert edited.artist_display == "Phil Berg" and edited.ts_start == 1218 and edited.download is False


def test_auto_gap_uids_are_stable_and_inputs_are_never_modified():
    rows = _with_home_durations(import_source(SETAOC).rows)
    before = [r.to_dict() for r in rows]
    uids = {r.ts_end: r.uid for r in rows if is_auto_gap(r)}             # keyed by the next track's start
    res = recompute_gaps(rows)
    assert [r.to_dict() for r in rows] == before                          # copies are renumbered, not these
    survivors = [r for r in res.rows if is_auto_gap(r)]
    assert len(survivors) == 6 and all(r.uid == uids[r.ts_end] for r in survivors)   # same neighbours
    again = recompute_gaps(res.rows)
    assert not again.changed and again.rows is res.rows


def test_tables_without_trackid_rows_are_a_no_op():
    rows = import_source(FIX / "setaoc-youtube.txt").rows
    assert all(r.source == "texto" for r in rows)
    res = recompute_gaps(rows)
    assert (res.changed, res.added, res.removed) == (False, 0, 0) and res.rows is rows
    assert recompute_gaps([]).rows == []
