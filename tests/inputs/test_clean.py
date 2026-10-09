"""Row cleaning before the review table (01 section 6.3)."""
from __future__ import annotations

import unicodedata

from tracklister.core.model import RowStatus, TrackRow
from tracklister.inputs.clean import clean_row, clean_rows, renumber


def _row(artist: str, title: str, **kw) -> TrackRow:
    return TrackRow(pos=kw.pop("pos", 1), title=title, artist_display=artist, **kw)


def test_label_written_as_co_artist_is_removed():
    r = clean_row(_row("Roll Dann, Laster Records", "The Red House (Original)", label="LASTER RECORDS"))
    assert (r.artist_display, r.artists, r.title, r.version) == ("Roll Dann", ["Roll Dann"], "The Red House", None)
    assert r.search_artist == "Roll Dann"
    assert any(n.startswith("sello quitado del artista") for n in r.notes)
    r2 = clean_row(_row("Phara", "Grey Ribbon", label="Phara"))       # never the only artist
    assert (r2.artists, r2.notes) == (["Phara"], [])
    r3 = clean_row(_row("Laster, Roll Dann", "X", label="Laster Records"))   # label without "Records"
    assert r3.artists == ["Roll Dann"]


def test_feat_out_of_artist_and_title():
    r = clean_row(_row("Funk Tribu ft. LUCY DYE", "All Of It"))
    assert (r.artist_display, r.artists, r.feat) == ("Funk Tribu", ["Funk Tribu"], "LUCY DYE")
    r = clean_row(_row("Bongoloverz", "Power Of Music (feat. An-Tonic) (Bongoloverz Dub)"))
    assert (r.title, r.feat, r.version) == ("Power Of Music", "An-Tonic", "Bongoloverz Dub")
    r = clean_row(_row("Bongoloverz", "Power Of Music (feat. An-Tonic) Bongoloverz Dub"))
    assert (r.title, r.feat, r.version) == ("Power Of Music", "An-Tonic", "Bongoloverz Dub")
    r = clean_row(_row("A", "Song feat. B"))
    assert (r.title, r.feat) == ("Song", "B")


def test_version_split():
    assert clean_row(_row("Truncate", "Dust 1 (Kai Van Dongen Remix)")).version == "Kai Van Dongen Remix"
    r = clean_row(_row("Plug Trax", "Zoned Out (Original Mix)"))
    assert (r.title, r.version) == ("Zoned Out", "Original Mix")
    r = clean_row(_row("X", "Song (Extended)"))
    assert (r.title, r.version) == ("Song", "Extended")
    r = clean_row(_row("X", "Song - Y Remix"))
    assert (r.title, r.version) == ("Song", "Y Remix")
    r = clean_row(_row("X", "Movement (Part 2)"))           # same base title as the verifier computes
    assert r.title == "Movement" and "quitado del título: (Part 2)" in r.notes
    kept = clean_row(_row("Truncate", "Dust 1 (Kai Van Dongen Remix)", version="Other Remix"))
    assert kept.version == "Other Remix" and kept.title == "Dust 1"


def test_nfc_and_typographic_quotes():
    r = clean_row(TrackRow(pos=1, title=unicodedata.normalize("NFD", "Cuerpo Sólido"),
                           artist_display="Ferdinger\u2019s  Band", artists=[]))
    assert r.title == "Cuerpo Sólido" and unicodedata.is_normalized("NFC", r.title)
    assert r.artist_display == "Ferdinger's Band" and r.artists == ["Ferdinger's Band"]


def test_id_review_and_empty_rows_are_unchecked():
    r = clean_row(_row("ID", "ID"))
    assert r.is_id and r.status == RowStatus.ID and not r.download and r.confidence == 0
    r = clean_row(_row("FJAAK", "Unreleased"))
    assert r.is_id and r.artist_display == "FJAAK"
    r = clean_row(_row("Ferdinand", ""))
    assert r.is_id and r.title == "ID" and "sin título" in r.notes and not r.download
    r = clean_row(_row("", "rob hood grey move", status=RowStatus.REVISAR, confidence=0.4))
    assert r.status == RowStatus.REVISAR and not r.download
    r = clean_row(_row("", "Grey Ribbon"))                       # no artist: never searched title-only
    assert r.status == RowStatus.REVISAR and not r.download and "sin artista" in r.notes
    r = clean_row(_row("?", "Some Title"))
    assert r.artists == [] and r.artist_display == "" and r.status == RowStatus.REVISAR
    gap = clean_row(TrackRow(pos=1, title="ID (hueco)", is_id=True, status=RowStatus.ID, download=False))
    assert gap.title == "ID (hueco)"


def test_duplicates_inside_the_set_are_noted_and_pos_renumbered():
    rows = clean_rows([_row("Phara", "Grey Ribbon", pos=7), _row("Klint", "Gunslingers", pos=3),
                       _row("phara", "Grey Ribbon (Original Mix)", pos=9), _row("Phara", "Grey Ribbon (X Remix)")])
    assert [r.pos for r in rows] == [1, 2, 3, 4]
    assert rows[2].notes == ["repetida (fila 1)"]
    assert rows[3].notes == []                                   # another version is another track
    assert rows[2].download                                      # noted, not unchecked


def test_clean_rows_is_idempotent_and_does_not_mutate_input():
    src = [_row("Roll Dann, Laster Records", "The Red House (Original)", label="LASTER RECORDS"),
           _row("Funk Tribu ft. LUCY DYE", "All Of It"), _row("Phara", "Grey Ribbon"),
           _row("Phara", "Grey Ribbon"), _row("X", "Movement (Part 2)"), _row("", "Solo título")]
    before = [r.to_dict() for r in src]
    once = clean_rows(src)
    twice = clean_rows(once)
    assert [r.to_dict() for r in twice] == [r.to_dict() for r in once]
    assert [r.to_dict() for r in src] == before
    assert [r.uid for r in once] == [r.uid for r in src]


def test_renumber():
    rows = [_row("A", "x", pos=5), _row("B", "y", pos=2)]
    assert [r.pos for r in renumber(rows)] == [1, 2]
