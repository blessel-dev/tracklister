"""'Reordenar carpeta existente' on the sandbox cases of 01 section 3 (P3).

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import unicodedata

import pytest

from tests.fakes.synth import make_track
from tracklister.core.model import RowStatus, TrackRow
from tracklister.organize.journal import Journal
from tracklister.organize.reorder import ReorderError, apply_reorder, propose_reorder


def _row(pos, artist, title, version=None, **kw):
    artists = kw.pop("artists", None) or [artist]
    return TrackRow(pos=pos, title=title, artists=artists, artist_display=artist, version=version, **kw)


# The FJAAK sample CSV as the cleaner leaves it (label removed from the artist, version split).
FJAAK = [
    _row(1, "Blasha & Allatt", "8AM in Salford", artists=["Blasha", "Allatt"]),
    _row(2, "Phara", "Grey Ribbon"), _row(3, "Justyn Nell", "Visions"),
    _row(4, "Roll Dann", "The Red House", "Original"), _row(5, "DJ Dextro", "Covil dos Abutres"),
    _row(6, "Axel Karakasis", "Last Ray"), _row(7, "Plug Trax", "Zoned Out"),
    _row(8, "OFF / GRID", "No Money No Problems"), _row(9, "Ferdinger", "I'm Still Here"),
    _row(10, "Truncate", "Dust 1", "Kai Van Dongen Remix"), _row(11, "STIPP", "Corrie"),
    _row(12, "Klint", "Gunslingers"), _row(13, "Exos", "Gla\u00f0ur Og Reifur"),
    _row(14, "Lewis Fautzi", "Zona Neutra"), _row(15, "ANFS", "Caballero"), _row(16, "Introversion", "Duff"),
    _row(17, "Chris Liebing", "Higher Things", "FJAAK Remix"),
]
CASE_A = {
    "01 - Blasha & Allatt - 8AM in Salford.mp3": 1, "Phara - Grey Ribbon (Original Mix).flac": 2,
    "05. Justyn Nell - Visions.mp3": 3, "Roll Dann - The Red House (Original Mix).mp3": 4,
    "DJ Dextro - Covil dos Abutres.aif": 5, "Axel Karakasis - Last Ray.MP3": 6,
    "plug_trax_-_zoned_out-psy.mp3": 7, "OFF  GRID - No Money No Problems.mp3": 8,
    "Ferdinger - I\u2019m Still Here.mp3": 9, "STIPP - Corrie.mp3": 11, "Klint - Gunslingers.wav": 12,
    "Exos - Gladur Og Reifur.mp3": 13, "01 Lewis Fautzi - Zona Neutra.mp3": 14,
    "Lewis Fautzi - Zona Neutra.mp3": 14, "ANFS - Caballero.mp3": 15, "Introversion - Duff.mp3": 16,
    "Chris Liebing - Higher Things (FJAAK Remix).mp3": 17,
    "Duffy - Mercy.mp3": None, "Chris Liebing - Higher Things (Original Mix).mp3": None,
}


def _make(folder, names):
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        (folder / n).write_bytes(n.encode("utf-8"))


def _by_pos(props):
    return {p.pos: p for p in props if p.pos}


def test_case_a_fjaak_folder(tmp_path):
    folder = tmp_path / "set"
    _make(folder, CASE_A)
    props = propose_reorder(folder, FJAAK)
    by = _by_pos(props)
    for name, pos in CASE_A.items():
        if pos is None:
            continue
        if pos == 14:
            assert by[14].status == "ambiguous" and by[14].src.name in (
                "01 Lewis Fautzi - Zona Neutra.mp3", "Lewis Fautzi - Zona Neutra.mp3")
            continue
        assert by[pos].status == "match", (name, by[pos])
        assert by[pos].src.name == name
    assert by[10].status == "missing"
    assert by[16].src.name == "Introversion - Duff.mp3"            # Duff is not Duffy
    assert by[17].src.name == "Chris Liebing - Higher Things (FJAAK Remix).mp3"
    extras = {p.src.name for p in props if p.status == "extra"}
    assert {"Duffy - Mercy.mp3", "Chris Liebing - Higher Things (Original Mix).mp3"} <= extras
    assert by[5].dst.name == "05 - DJ Dextro - Covil dos Abutres.aif"
    assert by[7].dst.name == "07 - Plug Trax - Zoned Out.mp3" and by[6].dst.name.endswith(".mp3")
    assert by[4].dst.name == "04 - Roll Dann - The Red House (Original).mp3"


def test_apply_then_undo_and_never_overwrite(tmp_path):
    folder = tmp_path / "set"
    _make(folder, CASE_A)
    (folder / "16 - Introversion - Duff.mp3").write_bytes(b"someone else's file")
    props = propose_reorder(folder, FJAAK)
    p16 = next(p for p in props if p.pos == 16)
    assert p16.status == "ambiguous"                            # two candidates: the user must choose
    p16.src, p16.status = folder / "Introversion - Duff.mp3", "match"   # user confirms this one
    j = Journal(folder)
    apply_reorder(folder, props, j)
    assert (folder / "01 - Blasha & Allatt - 8AM in Salford.mp3").read_bytes() == \
        "01 - Blasha & Allatt - 8AM in Salford.mp3".encode()
    assert (folder / "13 - Exos - Gla\u00f0ur Og Reifur.mp3").exists()
    assert (folder / "16 - Introversion - Duff.mp3").read_bytes() == b"someone else's file"   # not overwritten
    assert (folder / "16 - Introversion - Duff (2).mp3").read_bytes() == b"Introversion - Duff.mp3"
    assert (folder / "Duffy - Mercy.mp3").exists()                # extra: untouched
    assert (folder / "Lewis Fautzi - Zona Neutra.mp3").exists() or (folder / "01 Lewis Fautzi - Zona Neutra.mp3").exists()
    assert j.undo_last() == []
    assert sorted(p.name for p in folder.iterdir() if p.is_file()) == sorted(list(CASE_A) + ["16 - Introversion - Duff.mp3"])


def test_case_b_nfd_id_and_empty_title(tmp_path):
    rows = [_row(1, "R\u00f8dh\u00e5d", "Target Lock"), _row(2, "H\u00e9ctor Oaks", "Cuerpo S\u00f3lido"),
            _row(3, "Regal", "Acid Is The Answer"), _row(4, "Ferdinand Weber", "Hypnotic"),
            _row(5, "ID", "ID", is_id=True, status=RowStatus.ID, download=False), _row(6, "Kobosil", "")]
    files = ["R\u00f8dh\u00e5d - Target Lock.mp3", unicodedata.normalize("NFD", "H\u00e9ctor Oaks - Cuerpo S\u00f3lido.mp3"),
             "Regal - Acid Is The Answer.mp3", "Ferdinand Weber - Hypnotic.mp3", "Kobosil - 9 PM.mp3"]
    folder = tmp_path / "b"
    _make(folder, files)
    by = _by_pos(propose_reorder(folder, rows))
    assert [by[i].status for i in (1, 2, 3, 4)] == ["match"] * 4
    assert by[2].dst.name == "02 - H\u00e9ctor Oaks - Cuerpo S\u00f3lido.mp3"
    assert by[5].status == "missing" and by[6].status == "missing"
    props = propose_reorder(folder, rows)
    assert [p.src.name for p in props if p.status == "extra"] == ["Kobosil - 9 PM.mp3"]


def test_case_g_numbers_in_artist(tmp_path):
    rows = [_row(1, "808 State", "Pacific State"), _row(2, "2 Unlimited", "No Limit")]
    folder = tmp_path / "g"
    _make(folder, ["808 State - Pacific State.mp3", "2 Unlimited - No Limit.mp3"])
    by = _by_pos(propose_reorder(folder, rows))
    assert by[1].dst.name == "01 - 808 State - Pacific State.mp3"
    assert by[2].dst.name == "02 - 2 Unlimited - No Limit.mp3"


def test_rerun_on_reordered_folder_is_a_no_op(tmp_path):
    rows = [_row(1, "808 State", "Pacific State")]
    folder = tmp_path / "r"
    _make(folder, ["01 - 808 State - Pacific State.mp3"])
    props = propose_reorder(folder, rows)
    assert props[0].status == "match" and props[0].src == props[0].dst
    j = Journal(folder)
    apply_reorder(folder, props, j)
    assert j.batches() == []


def test_titles_with_other_numbers_never_match(tmp_path):
    """A folder that only has 'Dust 2' never gives it to the row 'Dust 1' (same rule as the download
    verification): the row stays missing and the file extra."""
    rows = [_row(1, "Truncate", "Dust 1"), _row(2, "Regal", "Untitled 1"), _row(3, "Exos", "A1")]
    folder = tmp_path / "n"
    _make(folder, ["Truncate - Dust 2.mp3", "Regal - Untitled 2.mp3", "Exos - B2.mp3"])
    props = propose_reorder(folder, rows)
    by = _by_pos(props)
    assert [by[i].status for i in (1, 2, 3)] == ["missing"] * 3
    assert sorted(p.src.name for p in props if p.status == "extra") == [
        "Exos - B2.mp3", "Regal - Untitled 2.mp3", "Truncate - Dust 2.mp3"]
    _make(folder, ["Truncate - Dust 1.mp3"])
    assert _by_pos(propose_reorder(folder, rows))[1].src.name == "Truncate - Dust 1.mp3"


@pytest.mark.parametrize("want,got", [("Adam Beyer", "Adam Port"), ("Chris Liebing", "Chris Lake"),
                                      ("Len Faki", "Ken Faki")])
def test_r3_b1_an_artist_with_a_similar_name_is_never_proposed(tmp_path, want, got):
    """Audit round 3, B1: 'Adam Port - Rush' scored 0.4*63 + 0.6*100 = 85 >= 75 and was proposed as the
    'match' of the row 'Adam Beyer - Rush'. Now another artist counts as no artist: the row stays
    missing and the file extra (left as it is). Also when the artist is only in the tags."""
    folder = tmp_path / "set"
    _make(folder, [f"{got} - Rush.mp3"])
    rows = [_row(1, want, "Rush")]
    props = propose_reorder(folder, rows)
    assert _by_pos(props)[1].status == "missing"
    assert [p.src.name for p in props if p.status == "extra"] == [f"{got} - Rush.mp3"]
    tagged = tmp_path / "tagged"
    tagged.mkdir()
    make_track(tagged / "pista 1.flac", fmt="flac", seconds=2, tags={"artist": got, "title": "Rush"})
    assert _by_pos(propose_reorder(tagged, rows))[1].status == "missing"
    _make(folder, [f"{want} - Rush.mp3"])                        # the right file is still found
    by = _by_pos(propose_reorder(folder, rows))
    assert by[1].status == "match" and by[1].src.name == f"{want} - Rush.mp3"


def test_r3_b1_genuine_artist_variants_still_match(tmp_path):
    rows = [_row(1, "Chris Liebing", "Motor"), _row(2, "DJ Rush", "Motor 2"), _row(3, "\u00d8 [Phase]", "Motor 3"),
            _row(4, "Blasha & Allatt", "Motor 4", artists=["Blasha", "Allatt"]), _row(5, "Roll Dann", "Motor 5"),
            _row(6, "H\u00e9ctor Oaks", "Motor 6")]
    files = {1: "CHRIS LIEBING - Motor.mp3", 2: "Dj Rush - Motor 2.mp3", 3: "O [Phase] - Motor 3.mp3",
             4: "Allatt & Blasha - Motor 4.mp3", 5: "Roll Dann & Laster Records - Motor 5.mp3",
             6: "Hector Oaks - Motor 6.mp3"}
    folder = tmp_path / "v"
    _make(folder, files.values())
    by = _by_pos(propose_reorder(folder, rows))
    for pos, name in files.items():
        assert by[pos].status == "match" and by[pos].src.name == name, (pos, by[pos])


@pytest.mark.parametrize("want,got", [("Feel It", "Feel It All"), ("Higher", "Higher Love"), ("Sin", "Original Sin")])
def test_r4_b2_a_title_with_a_word_more_or_less_is_never_proposed(tmp_path, want, got):
    """Audit round 4, B2: 'Feel It All' was proposed as the file of the row 'Feel It' (title 78 %). Now it
    scores at most 0.4*100 + 0.6*50 = 70 < MATCH_MIN: the row is missing and the file stays as it is,
    also by its tags; with the right file next to it, that one is the match."""
    folder = tmp_path / "s"
    _make(folder, [f"Amelie Lens - {got}.mp3"])
    tagged = make_track(folder / "sin nombre.flac", fmt="flac", seconds=1, tags={"artist": "Amelie Lens", "title": got})
    rows = [_row(1, "Amelie Lens", want)]
    props = propose_reorder(folder, rows)
    assert _by_pos(props)[1].status == "missing"
    assert {p.src.name for p in props if p.status == "extra"} == {f"Amelie Lens - {got}.mp3", tagged.name}
    _make(folder, [f"Amelie Lens - {want}.mp3"])
    by = _by_pos(propose_reorder(folder, rows))
    assert by[1].status == "match" and by[1].src.name == f"Amelie Lens - {want}.mp3"


def test_r4_v_the_originals_radio_edit_is_never_proposed_for_the_remixs_radio_edit(tmp_path):
    """Audit round 4, second review, B2: the row 'Spirit (Kai Remix) (Radio Edit)' was a plain radio edit,
    so the original's radio edit was a full match. Now it (and the full remix) stay as they are."""
    from tracklister.core.textnorm import split_title_version
    folder = tmp_path / "s"
    _make(folder, ["Fjaak - Spirit (Radio Edit).mp3", "Fjaak - Spirit (Kai Remix).mp3"])
    base, version = split_title_version("Spirit (Kai Remix) (Radio Edit)")
    rows = [_row(1, "Fjaak", base, version)]
    props = propose_reorder(folder, rows)
    assert _by_pos(props)[1].status == "missing"
    assert {p.src.name for p in props if p.status == "extra"} == {"Fjaak - Spirit (Radio Edit).mp3",
                                                                   "Fjaak - Spirit (Kai Remix).mp3"}
    _make(folder, ["Fjaak - Spirit (Kai Remix) (Radio Edit).mp3"])
    by = _by_pos(propose_reorder(folder, rows))
    assert by[1].status == "match" and by[1].src.name == "Fjaak - Spirit (Kai Remix) (Radio Edit).mp3"
    assert by[1].dst.name == "01 - Fjaak - Spirit (Kai Remix - Radio Edit).mp3"


def test_reserved_subdirs_are_ignored(tmp_path):
    folder = tmp_path / "s"
    _make(folder / "_dudosos", ["Phara - Grey Ribbon.flac"])
    _make(folder, ["Klint - Gunslingers.wav"])
    by = _by_pos(propose_reorder(folder, [_row(1, "Phara", "Grey Ribbon"), _row(2, "Klint", "Gunslingers")]))
    assert by[1].status == "missing" and by[2].status == "match"


def test_r2_b4_proposals_of_another_folder_rename_nothing(tmp_path):
    """Audit round 2, B4: a preview made for folder A, applied with folder B (or B's journal), would
    rename A's files and write the undo record in B. apply_reorder refuses it before touching anything."""
    a, b = tmp_path / "A", tmp_path / "B"
    _make(a, ["Phara - Grey Ribbon.flac", "Klint - Gunslingers.wav"])
    _make(b, ["otro.mp3"])
    rows = [_row(1, "Phara", "Grey Ribbon"), _row(2, "Klint", "Gunslingers")]
    props = propose_reorder(a, rows)
    for folder, journal in ((b, Journal(b)), (a, Journal(b)), (b, Journal(a))):
        try:
            apply_reorder(folder, props, journal)
        except ReorderError as e:
            assert "Ver propuesta" in str(e) and "No se ha renombrado nada" in str(e)
        else:
            raise AssertionError("a preview of another folder was applied")
    assert sorted(p.name for p in a.iterdir() if p.is_file()) == ["Klint - Gunslingers.wav", "Phara - Grey Ribbon.flac"]
    assert Journal(a).batches() == [] and Journal(b).batches() == []
    assert not (b / ".tracklister").exists()
    # a proposal whose file sits outside the folder, or whose new name points elsewhere, is refused too
    outside = [p for p in props if p.status == "match"]
    outside[0].src = tmp_path / "Phara - Grey Ribbon.flac"
    try:
        apply_reorder(a, props, Journal(a))
    except ReorderError:
        pass
    else:
        raise AssertionError("a file outside the folder was renamed")
    props = propose_reorder(a, rows)
    props[0].dst = b / props[0].dst.name
    try:
        apply_reorder(a, props, Journal(a))
    except ReorderError:
        pass
    else:
        raise AssertionError("a file was renamed into another folder")
    apply_reorder(a, propose_reorder(a, rows), Journal(a))      # the folder's own preview still works
    assert sorted(p.name for p in a.iterdir() if p.is_file()) == ["01 - Phara - Grey Ribbon.flac",
                                                                  "02 - Klint - Gunslingers.wav"]
