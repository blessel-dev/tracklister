"""The trackid.net CSV: 17 rows of the sample + 4 "ID (hueco)" rows, label-as-co-artist cleaned."""
from __future__ import annotations

import datetime
from pathlib import Path

from tracklister.core.model import RowStatus
from tracklister.inputs.tabular import RawTable, cell_text, read_table
from tracklister.inputs.trackid import (
    ESTIMATED_NOTE, GAP_TITLE, is_trackid_table, parse_hms, parse_int, parse_trackid,
)

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "inputs"
SAMPLE = FIX / "fjaak-techno-dj-set-section-may-2026.csv"


def _table(headers, rows) -> RawTable:
    return RawTable(headers=headers, rows=rows, encoding="utf-8", delimiter=",", sheet=None)


def test_is_trackid_table():
    assert is_trackid_table(read_table(SAMPLE))
    assert is_trackid_table(_table([" pos", "START ", "End", "artist", "Title"], []))   # Label optional
    assert not is_trackid_table(read_table(FIX / "sin-pos.csv"))
    assert not is_trackid_table(_table(["Pos", "Artist", "Title", "Label"], []))


def test_sample_gives_17_tracks_and_4_gap_rows():
    rows = parse_trackid(read_table(SAMPLE))
    assert [r.pos for r in rows] == list(range(1, 22))
    gaps = [r for r in rows if r.title == GAP_TITLE]
    assert [(r.ts_start, r.ts_end) for r in gaps] == [(1158, 1282), (1587, 1808), (2347, 2847), (3018, 3207)]
    assert [r.ts_end - r.ts_start for r in gaps] == [124, 221, 500, 189]   # 00:19:18 is the 124 s one
    assert [r.pos for r in gaps] == [9, 12, 17, 20]
    for g in gaps:
        assert g.is_id and not g.download and g.status == RowStatus.ID and g.confidence == 0
        assert g.artists == [] and g.artist_display == ""
    tracks = [r for r in rows if r.title != GAP_TITLE]
    assert len(tracks) == 17
    assert all(r.source == "trackid_csv" and r.download and r.status == RowStatus.OK for r in tracks)
    assert all(r.confidence == 0.7 for r in tracks)


def test_sample_names_versions_and_label_cleaning():
    rows = [r for r in parse_trackid(read_table(SAMPLE)) if r.title != GAP_TITLE]
    roll = rows[3]
    assert (roll.artist_display, roll.artists, roll.label) == ("Roll Dann", ["Roll Dann"], "LASTER RECORDS")
    assert (roll.title, roll.version) == ("The Red House", None)          # "(Original)" = the original
    assert "sello quitado del artista: Laster Records" in roll.notes
    assert roll.raw == '4,00:07:01,00:09:41,"Roll Dann, Laster Records",The Red House (Original),LASTER RECORDS'
    blasha = rows[0]
    assert (blasha.artists, blasha.artist_display, blasha.ts_start, blasha.ts_end) == (
        ["Blasha", "Allatt"], "Blasha & Allatt", 77, 168)
    assert (rows[9].title, rows[9].version) == ("Dust 1", "Kai Van Dongen Remix")
    assert (rows[16].artist_display, rows[16].title, rows[16].version) == ("Chris Liebing", "Higher Things",
                                                                            "FJAAK Remix")
    phara = rows[1]                                         # label == the only artist: kept
    assert (phara.artists, phara.label, phara.notes) == (["Phara"], "Phara", [])
    assert rows[12].title == "Glaður Og Reifur"


def test_gap_threshold_is_configurable():
    t = read_table(SAMPLE)
    assert sum(r.is_id for r in parse_trackid(t, gap_threshold_s=200)) == 2
    assert sum(r.is_id for r in parse_trackid(t, gap_threshold_s=600)) == 0
    # + the 77 s one between tracks, and the 77 s before the first track (0:00 -> 0:01:17)
    rows = parse_trackid(t, gap_threshold_s=60)
    assert sum(r.is_id for r in rows) == 6 and (rows[0].title, rows[0].ts_start, rows[0].ts_end) == (GAP_TITLE, 0, 77)


def test_rows_follow_pos_when_shuffled_and_a_row_without_end_still_finds_the_next_gap():
    """Audit round 2, N9: a row without an End time used to hide the gap after it. It now plays for the
    set's typical (median) track time, so the gap is found, marked as an estimate."""
    headers = ["Pos", "Start", "End", "Artist", "Title", "Label"]
    t = _table(headers, [["2", "00:05:00", "00:06:00", "B", "Two", ""],
                         ["1", "00:00:10", "00:01:00", "A", "One", ""],
                         ["3", "00:10:00", "", "C", "Three", ""],
                         ["4", "00:20:00", "00:21:00", "D", "Four", ""]])
    rows = parse_trackid(t)
    assert [r.title for r in rows] == ["One", GAP_TITLE, "Two", GAP_TITLE, "Three", GAP_TITLE, "Four"]
    assert [r.pos for r in rows] == [1, 2, 3, 4, 5, 6, 7]
    est = rows[5]                                       # plays measured: 50, 60, 60 s -> median 60 s
    assert (est.ts_start, est.ts_end) == (660, 1200) and ESTIMATED_NOTE in est.notes
    assert all(ESTIMATED_NOTE not in g.notes for g in (rows[1], rows[3]))
    assert all(not g.download and g.is_id for g in (rows[1], rows[3], rows[5]))


def test_gap_before_the_first_track_and_rows_without_any_time():
    headers = ["Pos", "Start", "End", "Artist", "Title", "Label"]
    rows = parse_trackid(_table(headers, [["1", "00:03:00", "00:05:00", "A", "One", ""],
                                          ["2", "00:05:00", "00:08:00", "B", "Two", ""]]))
    assert [(r.title, r.ts_start, r.ts_end) for r in rows][:2] == [(GAP_TITLE, 0, 180), ("One", 180, 300)]
    assert rows[0].pos == 1 and rows[1].pos == 2 and not rows[0].download
    # no End anywhere: no typical time to estimate with, so no gap is invented
    rows = parse_trackid(_table(headers, [["1", "00:00:30", "", "A", "One", ""],
                                          ["2", "00:30:00", "", "B", "Two", ""]]))
    assert [r.title for r in rows] == ["One", "Two"]


def test_parse_helpers():
    assert parse_hms("00:01:17") == 77 and parse_hms("1:17") == 77 and parse_hms("1:02:03") == 3723
    assert parse_hms("77") == 77 and parse_hms("") is None and parse_hms("abc") is None
    assert parse_hms("00:01:17.500") == 77
    assert parse_int("1") == 1 and parse_int("1.0") == 1 and parse_int("") is None and parse_int("x") is None
    assert parse_int("2.5") is None


def test_an_excel_time_in_a_trackid_duration_column_is_m_ss():
    """Barrido audit AU-1-02 (his decision, 29 Oct): his trackid.net CSV opened in Excel, with a «Duración» column
    added (X.1) and saved as .xlsx. Excel stores «6:24» as the time 06:24:00, which was read as 23,040 s: the track
    was never found and the gap was mismeasured. That column now follows the Z.11 rule (an hour from 1 to 23 with
    0 seconds is minutes:seconds, with a note); Start and End do not change."""
    headers = ["Pos", "Start", "End", "Artist", "Title", "Label", "Duración"]
    rows = parse_trackid(_table(headers, [
        ["1", "00:00:00", "00:06:24", "A", "One", "", cell_text(datetime.time(6, 24))],
        ["2", "00:06:24", "00:11:34", "B", "Two", "", cell_text(datetime.time(5, 10))],
        ["3", "01:02:00", "01:07:05", "C", "Three", "", "0:05:05"]]))
    tracks = [r for r in rows if not r.is_id]
    assert [r.expected_duration_s for r in tracks] == [384, 310, 305]
    assert "duración leída como 6:24 (minutos:segundos)" in tracks[0].notes
    assert "duración leída como 5:10 (minutos:segundos)" in tracks[1].notes
    assert not any(n.startswith("duración leída") for n in tracks[2].notes)
    assert tracks[2].ts_start == 3720
