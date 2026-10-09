"""Reading CSV/TXT/Excel tables: both delimiters, the three encodings, Excel numbers and times."""
from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

import pytest

from tests.inputs import fixturegen
from tracklister.inputs.tabular import TableError, cell_text, decode_bytes, detect_delimiter, read_table

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "inputs"
SAMPLE = FIX / fixturegen.SAMPLE
HEADERS = ["Pos", "Start", "End", "Artist", "Title", "Label"]


def test_sample_trackid_csv():
    t = read_table(SAMPLE)
    assert (t.encoding, t.delimiter, t.sheet) == ("utf-8", ",", None)
    assert t.headers == HEADERS
    assert len(t.rows) == 17
    assert t.rows[3] == ["4", "00:07:01", "00:09:41", "Roll Dann, Laster Records", "The Red House (Original)",
                         "LASTER RECORDS"]
    assert t.rows[12][4] == "Glaður Og Reifur"


@pytest.mark.parametrize("name,delimiter,encoding", [
    ("fjaak-coma-utf8-bom.csv", ",", "utf-8-sig"),
    ("fjaak-coma-cp1252.csv", ",", "cp1252"),
    ("fjaak-puntoycoma-cp1252.csv", ";", "cp1252"),
    ("fjaak-puntoycoma-utf8-bom.csv", ";", "utf-8-sig"),
    ("fjaak-puntoycoma-utf8.csv", ";", "utf-8"),
    ("fjaak-tab-utf16.txt", "\t", "utf-16"),
])
def test_variants_read_like_the_sample(name, delimiter, encoding):
    t = read_table(FIX / name)
    assert (t.delimiter, t.encoding) == (delimiter, encoding)
    assert t.headers == HEADERS
    assert t.rows == read_table(SAMPLE).rows


def test_xlsx_numbers_and_times_become_text():
    t = read_table(FIX / "fjaak.xlsx")
    assert (t.encoding, t.delimiter, t.sheet) == (None, None, "Tracklist")
    assert t.headers == HEADERS
    assert t.rows == read_table(SAMPLE).rows          # "1" not "1.0"; "00:01:17" not a time object


def test_xlsx_first_non_empty_sheet_and_numeric_cells():
    t = read_table(FIX / "mi-lista.xlsx")
    assert t.sheet == "Mi set"
    assert t.headers == ["Nº", "Artista", "Título", "Versión", "Sello"]
    assert t.rows[1] == ["2", "1991", "75", "", ""]
    assert t.rows[2] == ["", "Exos", "Glaður Og Reifur", "", "Mutual Rytm"]


def test_capital_extension_and_cp1252():
    t = read_table(FIX / "MAYUSCULAS.CSV")
    assert (t.delimiter, t.encoding) == (";", "cp1252")
    assert t.rows[1] == ["Exos", "Glaður Og Reifur"]


def test_xls_is_refused_with_a_clear_message(tmp_path):
    p = tmp_path / "lista.xls"
    p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64)
    with pytest.raises(TableError, match="Guarda el archivo como .xlsx o .csv"):
        read_table(p)


def test_unknown_extension_and_empty_table(tmp_path):
    with pytest.raises(TableError, match=r"\.pdf"):
        read_table(tmp_path / "set.pdf")
    empty = tmp_path / "vacia.csv"
    empty.write_bytes(b"\r\n\r\n")
    with pytest.raises(TableError, match="vacía"):
        read_table(empty)
    broken = tmp_path / "roto.xlsx"
    broken.write_bytes(b"no soy un zip")
    with pytest.raises(TableError, match="como Excel"):
        read_table(broken)
    with pytest.raises(TableError, match="No se pudo abrir"):
        read_table(tmp_path / "no-existe.csv")


def test_short_rows_are_padded_and_blank_rows_dropped(tmp_path):
    p = tmp_path / "t.csv"
    p.write_bytes(b"Artist;Title;Label\nPhara;Grey Ribbon\n;;\n\nKlint;Gunslingers;ARTS\n")
    t = read_table(p)
    assert t.rows == [["Phara", "Grey Ribbon", ""], ["Klint", "Gunslingers", "ARTS"]]


def test_decode_bytes():
    assert decode_bytes("Glaður".encode("utf-8")) == ("Glaður", "utf-8")
    assert decode_bytes(b"\xef\xbb\xbf" + "Glaður".encode("utf-8")) == ("Glaður", "utf-8-sig")
    assert decode_bytes("Glaður".encode("cp1252")) == ("Glaður", "cp1252")
    assert decode_bytes(b"\xff\xfe" + "Glaður".encode("utf-16-le")) == ("Glaður", "utf-16")


def test_detect_delimiter_fallbacks():
    assert detect_delimiter("Artist;Title\n") == ";"            # one line: Sniffer has too little to go on
    assert detect_delimiter('Artist,Title\n"A, B",C\n') == ","
    assert detect_delimiter("Artist;Title\nRoll Dann, Laster Records;The Red House\n") == ";"
    assert detect_delimiter("solo una columna\n") == ","
    assert detect_delimiter("") == ","


def test_cell_text():
    assert cell_text(None) == ""
    assert cell_text(7) == "7" and cell_text(7.0) == "7" and cell_text(3.5) == "3.5"
    assert cell_text(dt.time(0, 1, 17)) == "00:01:17"
    assert cell_text(dt.time(0, 1, 16, 999999)) == "00:01:17"
    assert cell_text(dt.timedelta(minutes=5, seconds=9)) == "00:05:09"
    assert cell_text(dt.datetime(1899, 12, 30, 0, 53, 27)) == "00:53:27"
    assert cell_text(dt.date(2026, 5, 1)) == "2026-05-01"
    assert cell_text(True) == "1"


def test_fixtures_are_reproducible(tmp_path):
    shutil.copy(SAMPLE, tmp_path / SAMPLE.name)
    for p in fixturegen.generate(tmp_path):
        checked_in = FIX / p.name
        if p.suffix == ".xlsx":
            a, b = read_table(p), read_table(checked_in)
            assert (a.headers, a.rows, a.sheet) == (b.headers, b.rows, b.sheet), p.name
        else:
            assert p.read_bytes() == checked_in.read_bytes(), p.name
