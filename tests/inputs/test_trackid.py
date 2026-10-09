"""The trackid.net CSV: 17 rows of the sample + 4 "ID (hueco)" rows, label-as-co-artist cleaned."""
from __future__ import annotations

from pathlib import Path

from tracklister.core.model import RowStatus
from tracklister.inputs.tabular import RawTable, read_table
from tracklister.inputs.trackid import GAP_TITLE, is_trackid_table, parse_hms, parse_int, parse_trackid

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
    assert sum(r.is_id for r in parse_trackid(t, gap_threshold_s=60)) == 5      # + the 77 s one


def test_rows_follow_pos_when_shuffled_and_missing_end_stops_gap_detection():
    headers = ["Pos", "Start", "End", "Artist", "Title", "Label"]
    t = _table(headers, [["2", "00:05:00", "00:06:00", "B", "Two", ""],
                         ["1", "00:00:10", "00:01:00", "A", "One", ""],
                         ["3", "00:10:00", "", "C", "Three", ""],
                         ["4", "00:20:00", "00:21:00", "D", "Four", ""]])
    rows = parse_trackid(t)
    assert [r.title for r in rows] == ["One", "ID (hueco)", "Two", "ID (hueco)", "Three", "Four"]
    assert [r.pos for r in rows] == [1, 2, 3, 4, 5, 6]


def test_parse_helpers():
    assert parse_hms("00:01:17") == 77 and parse_hms("1:17") == 77 and parse_hms("1:02:03") == 3723
    assert parse_hms("77") == 77 and parse_hms("") is None and parse_hms("abc") is None
    assert parse_hms("00:01:17.500") == 77
    assert parse_int("1") == 1 and parse_int("1.0") == 1 and parse_int("") is None and parse_int("x") is None
    assert parse_int("2.5") is None
