"""Row cleaning before the review table (01 section 6.3)."""
from __future__ import annotations

import unicodedata

import pytest

from tracklister.core.model import RowStatus, TrackRow
from tracklister.inputs.clean import (
    clean_row, clean_rows, duplicate_key, is_label_credit, label_keys, looks_like_label, renumber,
)


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
    # a version the row already has (a table's Mix column) is one more group: none hides the other
    both = clean_row(_row("Truncate", "Dust 1 (Kai Van Dongen Remix)", version="Other Remix"))
    assert both.version == "Kai Van Dongen Remix - Other Remix" and both.title == "Dust 1"
    same = clean_row(_row("Truncate", "Dust 1 (Kai Van Dongen Remix)", version="Kai Van Dongen Remix"))
    assert same.version == "Kai Van Dongen Remix"


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


@pytest.mark.parametrize("title,mix,version", [
    ("Spirit (Kai Remix) (Extended)", None, "Kai Remix"),
    ("Spirit (Kai Remix) [Extended]", None, "Kai Remix"),
    ("Spirit (Kai Remix)", "Extended Mix", "Kai Remix"),
    ("Spirit (Extended)", "Kai Remix", "Kai Remix"),
    ("Spirit (Kai Remix) (Radio Edit)", None, "Kai Remix - Radio Edit"),
    ("Spirit (Kai Remix)", "Radio Edit", "Kai Remix - Radio Edit"),
    ("Spirit", "(Kai Remix) (Radio Edit)", "Kai Remix - Radio Edit"),
    ("Spirit (Kai Remix) (Radio Edit)", "Radio Edit", "Kai Remix - Radio Edit"),
])
def test_r4_v_b1_no_version_group_of_a_table_row_is_lost(title, mix, version):
    """Audit round 4, second review, B1: a bare '(Extended)' (or a Mix column) set the version first, and
    the 'Kai Remix' of the title was thrown away without a note: the original extended was searched,
    verified and offered from the library. Now they are all groups of one version (core merge_versions)."""
    r = clean_row(_row("Fjaak", title, version=mix))
    assert (r.title, r.version) == ("Spirit", version) and r.notes == []


@pytest.mark.parametrize("title,version", [
    ("Spirit (feat. Jo) Extended Mix [Kai Remix]", "Kai Remix"),
    ("Spirit (feat. Jo) Extended Mix (Kai Remix)", "Kai Remix"),
    ("Spirit (feat. Jo) Kai Remix (Radio Edit)", "Kai Remix - Radio Edit"),
    ("Spirit (feat. Jo) Kai Remix", "Kai Remix"),
])
def test_r4_v_b3_the_version_after_a_feat_group_never_hides_the_remix(title, version):
    """B3: 'Title (feat. X) Extended Mix (Kai Remix)' took 'Extended Mix' first and dropped the remix."""
    r = clean_row(_row("Fjaak", title))
    assert (r.title, r.feat, r.version) == ("Spirit", "Jo", version)
    dub = clean_row(_row("Bongoloverz", "Power Of Music (feat. An-Tonic) Bongoloverz Dub"))
    assert (dub.title, dub.feat, dub.version) == ("Power Of Music", "An-Tonic", "Bongoloverz Dub")


def test_r4_v_duplicates_tell_the_three_versions_apart():
    rows = clean_rows([_row("Fjaak", "Spirit (Kai Remix) (Radio Edit)"), _row("Fjaak", "Spirit (Radio Edit)"),
                       _row("Fjaak", "Spirit (Kai Remix)"), _row("Fjaak", "Spirit (Kai Remix - Radio Edit)")])
    assert [r.notes for r in rows] == [[], [], [], ["repetida (fila 1)"]]


def test_r4_3_n1_the_order_of_the_version_groups_does_not_make_another_track():
    """Audit r4-3 N1 (1.0.1): '(Radio Edit) (Kai Remix)' is the same track as '(Kai Remix) (Radio Edit)'."""
    rows = clean_rows([_row("Fjaak", "Spirit (Kai Remix) (Radio Edit)"), _row("Fjaak", "Spirit (Radio Edit) (Kai Remix)"),
                       _row("Fjaak", "Spirit (Kai Remix)"), _row("Fjaak", "Spirit (Radio Edit)")])
    assert rows[0].version == "Kai Remix - Radio Edit" and rows[1].version == "Radio Edit - Kai Remix"
    assert duplicate_key(rows[0]) == duplicate_key(rows[1]) == "fjaak|spirit|kai remix radio edit"
    assert [r.notes for r in rows] == [[], ["repetida (fila 1)"], [], []]
    assert duplicate_key(_row("Fjaak", "Spirit (Original Mix)")) == duplicate_key(_row("Fjaak", "Spirit")) \
        == "fjaak|spirit|original"


@pytest.mark.parametrize("name,label_like", [
    ("KYSH Records", True), ("Demolate Records", True), ("Sello Ejemplo Recordings", True),
    ("Ejemplo Rec.", True), ("Casa Ejemplo Label", True), ("Ejemplo Records Ltd", True),
    ("Records", False), ("Recordings", False),           # one word: not enough to call it a label
    ("Ejemplo Music", False), ("Ejemplo Digital", False),  # these also end real artist names
    ("Sandrien", False), ("Tino Machauer", False), ("Rec Room", False), ("", False), (None, False),
])
def test_r5_looks_like_label(name, label_like):
    assert looks_like_label(name) is label_like


def test_r5_label_credit_from_the_row_or_the_store_label():
    keys = label_keys("KYSH")
    assert is_label_credit("KYSH Records", keys) and is_label_credit("kysh", keys)
    assert is_label_credit("Demolate Records", set())                          # label-shaped on its own
    assert not is_label_credit("Sandrien", label_keys("Mutual Rytm"))           # E.24: a real co-artist
    assert is_label_credit("Laster Records", label_keys("LASTER RECORDS"))
    assert not is_label_credit("Tino Machauer", label_keys("KLAR")) and not is_label_credit("", keys)


def test_clean_rows_is_idempotent_and_does_not_mutate_input():
    src = [_row("Roll Dann, Laster Records", "The Red House (Original)", label="LASTER RECORDS"),
           _row("Funk Tribu ft. LUCY DYE", "All Of It"), _row("Phara", "Grey Ribbon"),
           _row("Phara", "Grey Ribbon"), _row("X", "Movement (Part 2)"), _row("", "Solo título"),
           _row("Fjaak", "Spirit (Kai Remix) (Extended)"), _row("Fjaak", "Spirit (Kai Remix)", version="Radio Edit"),
           _row("Fjaak", "Spirit (feat. Jo) Extended Mix (Kai Remix)"), _row("Fjaak", "Spirit (Radio Edit) (Kai Remix)")]
    before = [r.to_dict() for r in src]
    once = clean_rows(src)
    twice = clean_rows(once)
    assert [r.to_dict() for r in twice] == [r.to_dict() for r in once]
    assert [r.to_dict() for r in src] == before
    assert [r.uid for r in once] == [r.uid for r in src]


def test_renumber():
    rows = [_row("A", "x", pos=5), _row("B", "y", pos=2)]
    assert [r.pos for r in renumber(rows)] == [1, 2]
