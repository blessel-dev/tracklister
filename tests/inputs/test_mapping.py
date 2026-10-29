"""The user's own tables: column guessing (Spanish/English), Pos rules, ID rows, one-column lists."""
from __future__ import annotations

from pathlib import Path

from tracklister.core.model import RowStatus
from tracklister.inputs.mapping import ColumnMapping, guess_mapping, refine_mapping, rows_from_table
from tracklister.inputs.tabular import RawTable, read_table

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "inputs"


def _rows(name: str):
    t = read_table(FIX / name)
    return rows_from_table(t, refine_mapping(t, guess_mapping(t.headers)))


def test_guess_mapping_english_and_spanish():
    m = guess_mapping(["Pos", "Start", "End", "Artist", "Title", "Label"])
    assert (m.pos, m.start, m.artist, m.title, m.label, m.combined) == (0, 1, 3, 4, 5, None)
    m = guess_mapping(["Nº", "Artista", "Título", "Versión", "Sello", "Duración"])
    assert (m.pos, m.artist, m.title, m.version, m.label, m.length) == (0, 1, 2, 3, 4, 5)
    m = guess_mapping(["#", "Track Title", "Artist", "Time"])
    assert (m.pos, m.title, m.artist, m.start) == (0, 1, 2, 3)
    m = guess_mapping(["Main Artist", "Song Name"])                      # word match
    assert (m.artist, m.title) == (0, 1)
    m = guess_mapping(["Track"])                                         # one "Artist - Title" column
    assert (m.artist, m.title, m.combined) == (None, None, 0) and m.is_usable()
    assert not guess_mapping(["Phara", "Grey Ribbon"]).is_usable()


def test_time_column_is_length_unless_it_grows_like_set_times():
    t = read_table(FIX / "export-dj.csv")
    m = refine_mapping(t, guess_mapping(t.headers))
    assert (m.start, m.length) == (None, 3)
    t2 = RawTable(headers=["Artist", "Title", "Time"], rows=[["A", "One", "00:00"], ["B", "Two", "12:30"],
                                                             ["C", "Three", "31:00"]],
                  encoding=None, delimiter=",", sheet=None)
    m2 = refine_mapping(t2, guess_mapping(t2.headers))
    assert (m2.start, m2.length) == (2, None)


def test_missing_pos_keeps_table_order():
    rows = _rows("sin-pos.csv")
    assert [(r.pos, r.artist_display, r.title) for r in rows] == [
        (1, "Phara", "Grey Ribbon"), (2, "Klint", "Gunslingers"), (3, "Exos", "Glaður Og Reifur")]
    assert all(r.source == "tabla" and r.download and r.confidence == 0.7 for r in rows)


def test_one_missing_pos_never_breaks_the_table():
    rows = _rows("pos-incompleto.csv")       # v1 turned the column into 1.0, 2.0 and renamed nothing
    assert [(r.pos, r.title) for r in rows] == [(1, "Grey Ribbon"), (2, "Gunslingers"), (3, "Glaður Og Reifur")]


def test_pos_column_orders_rows():
    t = RawTable(headers=["Pos", "Artist", "Title"], rows=[["2", "B", "Two"], ["1", "A", "One"]],
                 encoding=None, delimiter=",", sheet=None)
    rows = rows_from_table(t, guess_mapping(t.headers))
    assert [(r.pos, r.title) for r in rows] == [(1, "One"), (2, "Two")]


def test_empty_title_and_id_rows_are_never_downloadable():
    rows = _rows("titulo-vacio.csv")
    assert [(r.pos, r.title, r.is_id, r.download) for r in rows] == [
        (1, "Grey Ribbon", False, True), (2, "ID", True, False), (3, "ID", True, False),
        (4, "Gunslingers", False, True)]
    assert rows[2].artist_display == "Ferdinand" and "sin título" in rows[2].notes
    assert rows[1].status == RowStatus.ID


def test_numeric_artists_and_titles_are_kept():
    rows = _rows("artistas-numericos.csv")
    assert [(r.artist_display, r.title) for r in rows] == [
        ("808 State", "Pacific 202"), ("2 Unlimited", "No Limit"), ("Andrea Belluzzi", "75")]
    x = _rows("mi-lista.xlsx")
    assert [(r.pos, r.artist_display, r.title, r.version, r.label) for r in x] == [
        (1, "Truncate", "Dust 1", "Kai Van Dongen Remix", "Truncate"), (2, "1991", "75", None, None),
        (3, "Exos", "Glaður Og Reifur", None, "Mutual Rytm")]


def test_more_than_99_rows():
    rows = _rows("mas-de-99.csv")
    assert len(rows) == 120 and [r.pos for r in rows] == list(range(1, 121))
    assert rows[119].title == "Titulo 120"


def test_one_column_lists_are_parsed_like_text():
    rows = _rows("una-columna.csv")
    assert [(r.artist_display, r.title, r.version, r.label, r.feat) for r in rows[:2]] == [
        ("Truncate", "Dust 1", "Kai Van Dongen Remix", "Truncate", None),
        ("Funk Tribu", "All Of It", None, None, "LUCY DYE")]
    assert rows[2].status == RowStatus.REVISAR and not rows[2].download and rows[2].title == "Gunslingers"


def test_length_column_sets_expected_duration():
    rows = _rows("export-dj.csv")
    assert [(r.artist_display, r.title, r.expected_duration_s, r.ts_start) for r in rows] == [
        ("Phara", "Grey Ribbon", 309, None), ("Klint", "Gunslingers", 401, None)]


def test_an_excel_time_typed_as_m_ss_is_a_track_length():
    """Barrido CL-04: Excel stores «6:24» typed in a Duración/Length cell as the time 06:24:00, which was read as a
    6 h 24 min track: every row asked the engine for a 6-hour file (--length-tol 3) and found nothing, and the
    enrichment never corrected it (E.23). In the length column an hour from 1 to 23 with 0 seconds is
    minutes:seconds, with a note; an h:mm:ss with seconds, and the start column, are read as before."""
    import datetime as dt
    from tracklister.inputs.tabular import cell_text
    t = RawTable(headers=["Artist", "Title", "Length"],
                 rows=[["Fjaak", "Spirit", cell_text(dt.time(6, 24))], ["Fjaak", "Trip", cell_text(dt.time(0, 6, 24))],
                       ["Fjaak", "Hand", "6:24"], ["Fjaak", "Largo", "1:05:30"]],
                 encoding=None, delimiter=None, sheet="Hoja1")
    rows = rows_from_table(t, ColumnMapping(artist=0, title=1, length=2))
    assert [r.expected_duration_s for r in rows] == [384, 384, 384, 3930]
    assert "duración leída como 6:24 (minutos:segundos)" in rows[0].notes
    assert not [n for r in rows[1:] for n in r.notes if "leída como" in n]
    starts = RawTable(headers=["Start", "Artist", "Title"], rows=[["01:05:00", "Fjaak", "Spirit"]],
                      encoding=None, delimiter=None, sheet="Hoja1")
    (r,) = rows_from_table(starts, ColumnMapping(start=0, artist=1, title=2))
    assert r.ts_start == 3900 and not r.notes


def test_explicit_mapping():
    t = RawTable(headers=["a", "b", "c"], rows=[["x", "Phara", "Grey Ribbon"]], encoding=None, delimiter=",",
                 sheet=None)
    rows = rows_from_table(t, ColumnMapping(artist=1, title=2))
    assert (rows[0].artist_display, rows[0].title) == ("Phara", "Grey Ribbon")
