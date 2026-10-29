"""Free-text parser: the prototype's 24 self-test cases, the new v1.0 formats, to_track_rows."""
from __future__ import annotations

import pytest

from tracklister.core.model import RowStatus
from tracklister.inputs.text import parse_pasted_text
from tracklister.inputs.tlparse import parse_line, parse_text, to_track_rows

# (line, expected: one partial dict per resulting row) -- fuentes/tlparse_selftest.py, unchanged.
SELFTEST_CASES = [
    ("0:00 Phara - Grey Ribbon", [dict(ts=0, artist="Phara", title="Grey Ribbon")]),
    ("00:00:00 - Phara - Grey Ribbon", [dict(ts=0, artist="Phara", title="Grey Ribbon")]),
    ("1:02:03 Truncate - Dust 1 (Kai Van Dongen Remix) [TRUNCATE]",
     [dict(ts=3723, artist="Truncate", title="Dust 1", version="Kai Van Dongen Remix", label="TRUNCATE")]),
    ("01. Exos - Glaður Og Reifur [Mutual Rytm]",
     [dict(ts=None, artist="Exos", title="Glaður Og Reifur", label="Mutual Rytm")]),
    ("12) \U0001F525\U0001F525 45:10 | Lewis Fautzi \u2013 Zona Neutra",
     [dict(ts=2710, artist="Lewis Fautzi", title="Zona Neutra")]),
    ("#7 [12:00] Plug Trax \u2014 Zoned Out (Original Mix)",
     [dict(ts=720, artist="Plug Trax", title="Zoned Out", version="Original Mix")]),
    ("\u25b6 33:00 ID - ID", [dict(ts=1980, is_id=True)]),
    ("39:00 FJAAK - ID", [dict(ts=2340, artist="FJAAK", is_id=True)]),
    ("2:57:00 - ??????", [dict(ts=10620, is_id=True)]),
    ("10:00 Funk Tribu ft. LUCY DYE - All Of It",
     [dict(ts=600, artist="Funk Tribu", feat="LUCY DYE", title="All Of It")]),
    ("10:00 Bongoloverz - Power Of Music (feat. An-Tonic) (Bongoloverz Dub)",
     [dict(ts=600, artist="Bongoloverz", title="Power Of Music", feat="An-Tonic", version="Bongoloverz Dub")]),
    ("20:00 Slam - Viper w/ Robert Hood - Minus",
     [dict(ts=1200, artist="Slam", title="Viper"), dict(ts=1200, artist="Robert Hood", title="Minus")]),
    ("4:10 - Funk Tribu & CAIVA vs Funk Tribu - Keep Up vs Unreleased",
     [dict(ts=250, artist="Funk Tribu & CAIVA", title="Keep Up"), dict(ts=250, artist="Funk Tribu", is_id=True)]),
    ("02:20 - Oscar Mulero - Claro Magnetismo ( Wu100 - Viaje interior )",
     [dict(ts=140, artist="Oscar Mulero", title="Claro Magnetismo", label="Wu100 - Viaje interior")]),
    ('1:32:16 "Ant -  KN" - Fast Lane', [dict(ts=5536, artist="Ant - KN", title="Fast Lane")]),
    ("0:58:25 Deas \u2018Focus\u2019", [dict(ts=3505, artist="Deas", title="Focus")]),
    ("3.03:00 - Oscar Mulero - Dos Esqueletos (Original mix)",
     [dict(ts=10980, artist="Oscar Mulero", title="Dos Esqueletos")]),
    ("3:07:36-  Andrea Belluzzi - 75", [dict(ts=11256, artist="Andrea Belluzzi", title="75")]),
    ("Klint - Gunslingers 31:38", [dict(ts=1898, artist="Klint", title="Gunslingers")]),
    ("50:50 - Deas - Here Again (Upcoming CROWD)",
     [dict(ts=3050, artist="Deas", title="Here Again", label="CROWD")]),
    ("1. 5:22", []),                                   # a 'Transitions' comment: times only
    ("What a set.. absolutely insane", []),            # prose without a time is dropped
    ("TRACKLIST :", []),
]


def _check(rows, expected):
    assert len(rows) == len(expected), [(r.artist, r.title) for r in rows]
    for r, e in zip(rows, expected):
        for k, v in e.items():
            assert getattr(r, k) == v, (k, getattr(r, k), v)


@pytest.mark.parametrize("line,expected", SELFTEST_CASES, ids=[c[0][:40] for c in SELFTEST_CASES])
def test_prototype_selftest_line(line, expected):
    _check(parse_line(line), expected)


def test_prototype_selftest_multiline_comment():
    blob = "Tracklist \U0001F525\n0:00 A - One\n\n2. B - Two (C Remix)\nnice set!\n05:30 D & E - Three [LBL]\n"
    rows = parse_text(blob, duration=600)
    assert [(r.artist, r.title) for r in rows] == [("A", "One"), ("B", "Two"), ("D & E", "Three")]
    assert [r.ts for r in rows] == [0, None, 330]
    assert [r.pos for r in rows] == [1, 2, 3]


def test_selftest_count_is_24():
    assert len(SELFTEST_CASES) + 1 == 24


# ---------------------------------------------------------------- new formats (02 section 3.B)

@pytest.mark.parametrize("line,expected", [
    ("[12] Oscar Mulero - Horizontes [Warm Up]",
     [dict(ts=720, artist="Oscar Mulero", title="Horizontes", label="Warm Up")]),
    ("[00] Planetary Assault Systems - Angel Of The East", [dict(ts=0, title="Angel Of The East")]),
    ("[123] Jeff Mills - The Bells (Original Mix) [Purpose Maker - PM-001]",
     [dict(ts=7380, artist="Jeff Mills", title="The Bells", version="Original Mix", label="Purpose Maker - PM-001")]),
    ("[05] ?", [dict(ts=300, is_id=True)]),
    ("[??] ?", [dict(ts=None, is_id=True)]),
    ("[??] Unknown - Unknown", [dict(ts=None, is_id=True)]),
])
def test_mixesdb_minute_markers(line, expected):
    _check(parse_line(line), expected)


def test_mixesdb_block_keeps_minutes():
    text = "[00] A - One\n[04] B - Two\n[09] ?\n[13] C - Three\n"
    rows = parse_text(text)
    assert [r.ts for r in rows] == [0, 240, 540, 780]
    assert [r.is_id for r in rows] == [False, False, True, False]


def test_bracketed_numbering_is_not_minutes():
    rows = parse_text("[1] A - One\n[2] B - Two\n[3] C - Three\n[4] D - Four\n")
    assert [r.ts for r in rows] == [None, None, None, None]
    assert [(r.artist, r.title) for r in rows] == [("A", "One"), ("B", "Two"), ("C", "Three"), ("D", "Four")]


@pytest.mark.parametrize("line,expected", [
    ("00:00 - 04:30 Fjaak - Spirit", (0, "Fjaak", "Spirit")),
    ("[00:00 - 04:30] Fjaak - Spirit", (0, "Fjaak", "Spirit")),
    ("Fjaak - Spirit [00:00 - 04:30]", (0, "Fjaak", "Spirit")),
    ("00:00-04:30 Fjaak - Spirit", (0, "Fjaak", "Spirit")),
    ("1. 00:00 - 04:30 Fjaak - Spirit", (0, "Fjaak", "Spirit")),
    # lines without a range are read as before
    ("0:00 Fjaak - Spirit", (0, "Fjaak", "Spirit")),
    ("Fjaak - Spirit (04:30)", (270, "Fjaak", "Spirit")),
    ("1:02:03 Fjaak - Spirit", (3723, "Fjaak", "Spirit")),
])
def test_a_time_range_is_the_start_of_the_track(line, expected):
    """CL-03: «00:00 - 04:30 Fjaak - Spirit» gave the artist «30 Fjaak» (the track number rule took «04:»),
    «[00:00 - 04:30] …» gave «30] Fjaak», and «Fjaak - Spirit [00:00 - 04:30]» the title «Spirit [00:00» with
    the start at 4:30. A time range is the start of the track."""
    assert [(r.ts, r.artist, r.title) for r in parse_line(line)] == [expected]


@pytest.mark.parametrize("line,expected", [
    ("Tek.Ka - TTA techno (Joey H\u00e4tz 150bpm remix) @ SDL records",
     [dict(artist="Tek.Ka", title="TTA techno", version="Joey H\u00e4tz 150bpm remix", label="SDL records")]),
    ("Tek.Ka - TTA techno (Joey H\u00e4tz remix @150bpm) @ SDL records",
     [dict(title="TTA techno", version="Joey H\u00e4tz remix @150bpm", label="SDL records")]),
    ("05:00 Oscar Mulero - Generator @ Warm Up Recordings",
     [dict(ts=300, title="Generator", label="Warm Up Recordings")]),
    ("Matt Sassari - Rock trick (@150 bpm)", [dict(title="Rock trick", label=None)]),
    ("Artist - Title @handle", [dict(title="Title @handle", label=None)]),   # a handle is not a label
])
def test_trailing_at_label(line, expected):
    _check(parse_line(line), expected)


@pytest.mark.parametrize("line,expected", [
    ("0:00:02 Bongoloverz - Power Of Music (feat. An-Tonic) Bongoloverz Dub",
     [dict(ts=2, title="Power Of Music", feat="An-Tonic", version="Bongoloverz Dub")]),
    ("Funk Tribu - Keep Up [ft. CAIVA] Extended Mix [Rave Alert]",
     [dict(title="Keep Up", feat="CAIVA", version="Extended Mix", label="Rave Alert")]),
    ("A - Song (feat. B) Part 2", [dict(title="Song (feat. B) Part 2", feat=None, version=None)]),
])
def test_feat_group_then_version(line, expected):
    _check(parse_line(line), expected)


# ---------------------------------------------------------------- to_track_rows

FJAAK_LIKE = """Tracklist
00:00 - ID - ID
00:19 - Blasha, Allatt - 8AM in Salford
2:38 Phara - Grey Ribbon
04:30 rob hood grey move
23:30 Truncate - Dust 1 (Kai Van Dongen Remix)
39:00 FJAAK - ID
44:45 ANFS - Caballero - BITE - revisar
"""


def test_to_track_rows_rules():
    rows = to_track_rows(parse_text(FJAAK_LIKE), "youtube_comment:@x", "https://www.youtube.com/watch?v=abc")
    assert [r.pos for r in rows] == list(range(1, 8))
    assert all(r.source == "youtube_comment:@x" and r.source_url.endswith("abc") for r in rows)
    first, blasha, phara, partial, trunc, fjaak, three = rows
    assert first.is_id and first.status == RowStatus.ID and not first.download and first.confidence == 0
    assert first.artist_display == "ID" and first.artists == []
    assert blasha.status == RowStatus.OK and blasha.download and blasha.confidence == 0.7
    assert blasha.artists == ["Blasha", "Allatt"] and blasha.artist_display == "Blasha, Allatt"
    assert (blasha.ts_start, blasha.ts_end) == (19, 158)
    assert partial.status == RowStatus.REVISAR and not partial.download and partial.confidence == 0.4
    assert partial.title == "rob hood grey move" and partial.artists == []
    assert trunc.version == "Kai Van Dongen Remix" and trunc.ts_end == 2340
    assert fjaak.is_id and fjaak.artist_display == "FJAAK" and fjaak.title == "ID"
    assert three.status == RowStatus.REVISAR and "3+ partes: revisar" in three.notes
    assert three.ts_end is None                       # last row: no later start
    assert blasha.raw == "00:19 - Blasha, Allatt - 8AM in Salford"
    assert len({r.uid for r in rows}) == 7


def test_ts_end_skips_equal_and_earlier_starts():
    rows = to_track_rows(parse_text("20:00 Slam - Viper w/ Robert Hood - Minus\n19:00 A - B\n25:00 C - D\n"), "texto")
    assert [r.ts_start for r in rows] == [1200, 1200, 1140, 1500]
    assert [r.ts_end for r in rows] == [1500, 1500, 1500, None]


def test_unknown_artist_is_review_without_search_artist():
    (row,) = to_track_rows(parse_text("12:00 ID - Some Title"), "texto")
    assert row.status == RowStatus.REVISAR and not row.download
    assert row.artists == [] and row.artist_display == "" and row.search_artist == ""


def test_parse_pasted_text():
    rows = parse_pasted_text("1. Exos - Gla\u00f0ur Og Reifur [Mutual Rytm]\nhola!\n2. Klint - Gunslingers\n")
    assert [(r.pos, r.artist_display, r.title, r.label) for r in rows] == [
        (1, "Exos", "Gla\u00f0ur Og Reifur", "Mutual Rytm"), (2, "Klint", "Gunslingers", None)]
    assert all(r.source == "texto" and r.ts_start is None for r in rows)
    assert parse_pasted_text("") == [] and parse_pasted_text("solo prosa, sin pistas") == []
