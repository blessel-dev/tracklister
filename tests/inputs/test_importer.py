"""import_source: every input kind, Spanish messages, never an exception for user input."""
from __future__ import annotations

from pathlib import Path

import pytest

from tracklister.core.model import RowStatus
from tracklister.inputs.detect import InputKind
from tracklister.inputs.importer import ImportResult, import_source
from tracklister.inputs.trackid import GAP_TITLE

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "inputs"
SAMPLE = FIX / "fjaak-techno-dj-set-section-may-2026.csv"
VARIANTS = ("fjaak-coma-utf8-bom.csv", "fjaak-coma-cp1252.csv", "fjaak-puntoycoma-cp1252.csv",
            "fjaak-puntoycoma-utf8-bom.csv", "fjaak-puntoycoma-utf8.csv", "fjaak-tab-utf16.txt", "fjaak.xlsx")


def _names(res: ImportResult) -> list[tuple]:
    return [(r.pos, r.artist_display, r.title, r.version, r.label, r.ts_start, r.ts_end, r.is_id, r.download)
            for r in res.rows]


def test_trackid_csv():
    res = import_source(SAMPLE)
    assert res.kind == InputKind.TRACKID_CSV
    assert len(res.rows) == 21 and sum(r.title == GAP_TITLE for r in res.rows) == 4
    assert res.message_es == ("trackid.net: 17 pistas, 4 filas ID (sin descargar). "
                              "Revisa la tabla antes de descargar.")
    assert res.suggested_name == "fjaak-techno-dj-set-section-may-2026"
    (src,) = res.sources
    assert (src.kind, src.ref, src.detail) == ("trackid_csv", SAMPLE.name, "trackid.net CSV (17 pistas, 4 huecos)")
    assert "\\" not in src.ref and "/" not in src.ref                 # file name only, no folders
    assert src.imported_at
    assert res.rows[3].artist_display == "Roll Dann"
    assert res.warnings_es == [] and res.candidates == [] and res.chosen is None


@pytest.mark.parametrize("name", VARIANTS)
def test_every_encoding_and_delimiter_gives_the_same_rows(name):
    res = import_source(FIX / name)
    assert res.kind == InputKind.TRACKID_CSV
    assert _names(res) == _names(import_source(SAMPLE))


def test_own_tables():
    res = import_source(FIX / "pos-incompleto.csv")
    assert res.kind == InputKind.TABLE and [r.pos for r in res.rows] == [1, 2, 3]
    assert res.message_es == "pos-incompleto.csv: 3 pistas. Revisa la tabla antes de descargar."
    res = import_source(FIX / "titulo-vacio.csv")
    assert "2 filas ID (sin descargar)" in res.message_es
    assert [r.download for r in res.rows] == [True, False, False, True]
    res = import_source(FIX / "nfd.csv")
    assert [r.title for r in res.rows] == ["Cuerpo Sólido", "Wise Saying"]
    assert res.rows[1].artist_display == "Rødhåd"
    res = import_source(FIX / "apostrofo.csv")
    assert res.rows[0].title == "I'm Still Here"
    res = import_source(FIX / "MAYUSCULAS.CSV")
    assert [r.title for r in res.rows] == ["Grey Ribbon", "Glaður Og Reifur"]
    assert len(import_source(FIX / "mas-de-99.csv").rows) == 120


def test_headerless_table_warns():
    res = import_source(FIX / "sin-cabecera.csv")
    assert [(r.artist_display, r.title) for r in res.rows] == [("Phara", "Grey Ribbon"), ("Klint", "Gunslingers")]
    assert any("No encontré los nombres de las columnas" in w for w in res.warnings_es)


def test_duplicate_warning(tmp_path):
    p = tmp_path / "dup.csv"
    p.write_text("Artist,Title\nPhara,Grey Ribbon\nKlint,Gunslingers\nPhara,Grey Ribbon\n", encoding="utf-8")
    res = import_source(p)
    assert res.rows[2].notes == ["repetida (fila 1)"]
    assert res.warnings_es == ["La fila 3 (Phara - Grey Ribbon) está repetida (fila 1)."]


def test_text_file_and_pasted_text():
    res = import_source(FIX / "tracklist.txt")
    assert res.kind == InputKind.TEXT and len(res.rows) == 3
    assert res.message_es == "tracklist.txt: 2 pistas, 1 fila ID (sin descargar)."
    res = import_source("0:00 Phara - Grey Ribbon\n\n5:10 Klint - Gunslingers\nqué set!")
    assert res.kind == InputKind.TEXT
    assert [(r.artist_display, r.title, r.ts_start, r.ts_end) for r in res.rows] == [
        ("Phara", "Grey Ribbon", 0, 310), ("Klint", "Gunslingers", 310, None)]
    assert res.message_es == "Texto: 2 pistas (2 con tiempo)."
    assert res.sources[0].ref == "texto" and res.suggested_name is None
    empty = import_source("hola, ¿alguien sabe la tracklist?")
    assert empty.rows == [] and empty.sources == [] and "No he encontrado pistas" in empty.message_es


def test_problems_become_messages(tmp_path):
    xls = tmp_path / "lista.xls"
    xls.write_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * 60)
    res = import_source(xls)
    assert res.kind == InputKind.XLS_UNSUPPORTED and res.rows == []
    assert "Guarda el archivo como .xlsx o .csv" in res.message_es
    assert "No encuentro el archivo set.csv" in import_source(tmp_path / "set.csv").message_es
    assert "es una carpeta" in import_source(tmp_path).message_es
    bad = tmp_path / "raro.csv"
    bad.write_bytes(bytes(range(256)) * 4)
    res = import_source(bad)                                       # never raises
    assert isinstance(res, ImportResult)
    pdf = tmp_path / "set.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert ".pdf" in import_source(pdf).message_es


def test_links_that_cannot_be_read_automatically():
    res = import_source("https://trackid.net/audiostreams/fjaak-techno-dj-set-section-may-2026")
    assert res.kind == InputKind.TRACKID_URL and res.rows == []
    assert "pulsa Export" in res.message_es
    assert res.links == ["https://trackid.net/audiostreams/fjaak-techno-dj-set-section-may-2026"]
    res = import_source("https://www.1001tracklists.com/tracklist/2abc/x.html")
    assert res.kind == InputKind.PASTE_ONLY_URL and "1001tracklists" in res.message_es and "pégala" in res.message_es
    assert "MixesDB" in import_source("https://www.mixesdb.com/w/2022-x").message_es
    res = import_source("https://www.mixcloud.com/blessel/chapter-i/")
    assert res.kind == InputKind.OTHER_URL and res.rows == []


def test_youtube_without_ytdlp_explains_what_to_do():
    res = import_source("https://www.youtube.com/watch?v=mD9ELt_Pvp4", ytdlp=None)
    assert res.kind == InputKind.YOUTUBE and res.rows == []
    assert "yt-dlp no está disponible" in res.message_es and "YouTube" in res.message_es
    res = import_source("https://soundcloud.com/a/b", ytdlp=None)
    assert "SoundCloud" in res.message_es


@pytest.mark.parametrize("line,version", [
    ("Fjaak - Spirit (Kai Remix) (Extended Mix)", "Kai Remix"),
    ("Fjaak - Spirit (Extended Mix) (Kai Remix)", "Kai Remix"),
    ("Fjaak - Spirit (Live at Awakenings)", "Live at Awakenings"),
    ("Fjaak - Spirit (Live)", "Live")])
def test_r4_b3_a_pasted_remix_or_live_keeps_its_version(tmp_path, line, version):
    """Audit round 4, B3: '(Kai Remix) (Extended Mix)' became the extended ORIGINAL (the remix went to the
    label column), and '(Live ...)' a label: the original was searched, verified and keyed in the library.
    The same for pasted text and for a table."""
    from tracklister.engine.csvwriter import engine_title
    from tracklister.library.index import library_key, row_key
    table = tmp_path / "tabla.csv"
    table.write_text('Artist,Title\nFjaak,"' + line.split(" - ", 1)[1] + '"\n', encoding="utf-8")
    for source in (line, table):
        (r,) = import_source(source).rows
        assert (r.title, r.version) == ("Spirit", version), source
        assert engine_title(r) == f"Spirit ({version})" and r.label is None
        assert row_key(r) != library_key("Fjaak", "Spirit", None)


def _every_input(tmp_path, title: str, mix: str | None = None) -> dict[str, object]:
    """The same track through each import path: own CSV (',' and ';'), own XLSX, trackid.net CSV, pasted
    text. A Mix column only exists in the own tables."""
    from tests.inputs.fixturegen import write_xlsx
    head, cells = ["Artista", "Título"] + (["Mix"] if mix else []), ["Fjaak", title] + ([mix] if mix else [])
    tables = {}
    for name, sep in (("coma.csv", ","), ("puntoycoma.csv", ";")):
        p = tmp_path / name
        p.write_text(sep.join(head) + "\n" + sep.join(f'"{c}"' for c in cells) + "\n", encoding="utf-8")
        tables[name] = p
    tables["tabla.xlsx"] = tmp_path / "tabla.xlsx"
    write_xlsx(tables["tabla.xlsx"], [head, cells])
    if mix is None:
        trackid = tmp_path / "trackid.csv"
        trackid.write_text(f'Pos,Start,End,Artist,Title,Label\n1,00:00:00,00:05:00,Fjaak,"{title}",Drumcode\n',
                           encoding="utf-8")
        tables["trackid.csv"] = trackid
        tables["texto"] = f"Fjaak - {title}"
    return tables


@pytest.mark.parametrize("title,mix", [("Spirit (Kai Remix) (Extended)", None), ("Spirit (Kai Remix) [Extended]", None),
                                       ("Spirit (Kai Remix)", "Extended Mix")])
def test_r4_v_b1_an_own_table_keeps_the_remix_behind_a_bare_extended_or_a_mix_column(tmp_path, title, mix):
    """Audit round 4, second review, B1: an own CSV/XLSX with Title 'Spirit (Kai Remix) (Extended)' (or
    '[Extended]', or the Mix column 'Extended Mix') lost the remix: engine title 'Spirit (Extended)', library
    key 'original', and the original extended was VERIFICADO. Every path now gives the Kai Remix."""
    from tracklister.engine.csvwriter import engine_title
    from tracklister.library.index import row_key
    for name, source in _every_input(tmp_path, title, mix).items():
        res = import_source(source)
        (r,) = res.rows
        assert (r.title, r.version) == ("Spirit", "Kai Remix"), name
        assert engine_title(r) == "Spirit (Kai Remix)" and row_key(r) == "fjaak|spirit|kai remix", name
        assert row_key(r) != "fjaak|spirit|original" and r.download, name
    for name, source in _every_input(tmp_path, "Song (Extended)").items():      # unchanged
        assert import_source(source).rows[0].version == "Extended", name
    for name, source in _every_input(tmp_path, "The Red House (Original)").items():
        (r,) = import_source(source).rows
        assert (r.title, r.version, row_key(r)) == ("The Red House", None, "fjaak|the red house|original"), name


@pytest.mark.parametrize("title,version", [
    ("Spirit (Kai Remix) (Radio Edit)", "Kai Remix - Radio Edit"),
    ("Spirit (Radio Edit) (Kai Remix)", "Radio Edit - Kai Remix"),
    ("Spirit (Kai Remix - Radio Edit)", "Kai Remix - Radio Edit"),
    ("Spirit (Kai Remix) (Edit)", "Kai Remix - Edit"),
    ("Spirit (Kai Remix) (Live)", "Kai Remix - Live"),
    ("Spirit (Kai Remix) (Instrumental)", "Kai Remix - Instrumental"),
    ("Spirit (Kai Remix) (Remastered)", "Kai Remix - Remastered"),
    ("Spirit (Kai Remix) (2011 Remaster)", "Kai Remix - 2011 Remaster"),
    ("Spirit (feat. Jo) Extended Mix [Kai Remix]", "Kai Remix"),
    ("Spirit (feat. Jo) Extended Mix (Kai Remix)", "Kai Remix"),
    ("Spirit (feat. Jo) Kai Remix (Radio Edit)", "Kai Remix - Radio Edit"),
])
def test_r4_v_b2_b3_every_input_keeps_the_remixer_and_its_other_group(tmp_path, title, version):
    """B2: '(Kai Remix) (Radio Edit)' kept only 'Radio Edit' in every path (in pasted text the remixer went
    to the notes), so the original's radio edit was searched with 'Spirit (Radio Edit)' and verified. B3:
    the version after a feat group hid the remix in a table. Now every path gives the same version, and
    the engine is asked for the remix ('Spirit (Kai Remix)')."""
    from tracklister.engine.csvwriter import engine_title
    from tracklister.library.index import library_key, row_key
    for name, source in _every_input(tmp_path, title).items():
        (r,) = import_source(source).rows
        assert (r.title, r.version) == ("Spirit", version), name
        assert "Kai Remix" not in r.notes and r.label in (None, "Drumcode"), name
        assert engine_title(r) == "Spirit (Kai Remix)", name
        assert row_key(r) not in (library_key("Fjaak", "Spirit", "Radio Edit"), library_key("Fjaak", "Spirit", None)), name
        if "feat" in title and name != "trackid.csv":
            assert r.feat == "Jo", name


def test_review_rows_count_in_message():
    res = import_source(FIX / "una-columna.csv")
    assert res.message_es == "una-columna.csv: 3 pistas, 1 por revisar. Revisa la tabla antes de descargar."
    assert res.rows[2].status == RowStatus.REVISAR
