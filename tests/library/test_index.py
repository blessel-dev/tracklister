"""Library index: keys, root files only, duration tolerance, rebuild from set.json.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

from tracklister.core.jsonio import write_json
from tracklister.core.layout import set_doc_path
from tracklister.core.model import DoubtKind, ResultState, RowResult, SetDoc, TrackRow
from tracklister.library.index import LibraryIndex, library_key


def _row(pos, artist, title, version=None, dur=None):
    return TrackRow(pos=pos, title=title, artists=[a.strip() for a in artist.split("&")], artist_display=artist,
                    version=version, expected_duration_s=dur)


def test_library_key():
    assert library_key("Fjaak & X", "Spirit", None) == library_key("FJAAK", "spirit", "Original Mix")
    assert library_key("Fjaak", "Spirit", "Extended Mix").endswith("|original")
    assert library_key("Chris Liebing", "Higher Things", "FJAAK Remix") != library_key("Chris Liebing", "Higher Things", None)
    assert library_key("Sigur R\u00f3s", "Gla\u00f0ur", None) == "sigur ros|gladur|original"


def _set(tmp_path, name="Set A", set_id="aaaa1111"):
    d = tmp_path / "lib" / name
    d.mkdir(parents=True)
    r1, r2, r3 = _row(1, "Fjaak", "Spirit", dur=300), _row(2, "Kobosil", "Aggression"), _row(3, "X", "Y")
    (d / "01 - Fjaak - Spirit.flac").write_bytes(b"1")
    (d / "_dudosos").mkdir()
    (d / "_dudosos" / "02 - Kobosil - Aggression.flac").write_bytes(b"2")
    (d / "03 - X - Y.flac").write_bytes(b"3")
    doc = SetDoc(set_id=set_id, name=name, preset_id="lossless", rows=[r1, r2, r3], results={
        r1.uid: RowResult(r1.uid, 1, ResultState.VERIFICADO, file="01 - Fjaak - Spirit.flac", duration_s=301.0),
        r2.uid: RowResult(r2.uid, 2, ResultState.DUDOSO, DoubtKind.VERSION, file="_dudosos/02 - Kobosil - Aggression.flac"),
        r3.uid: RowResult(r3.uid, 3, ResultState.DUDOSO, DoubtKind.REVISAR, file="03 - X - Y.flac"),
    })
    write_json(set_doc_path(d), doc.to_dict())
    return d, doc


def test_add_find_and_tolerance(tmp_path):
    d, doc = _set(tmp_path)
    lib = LibraryIndex(tmp_path / "library.json")
    assert lib.add_from_set(d, doc) == 1                      # only the verified root file
    assert lib.add_from_set(d, doc) == 1 and len(lib.entries) == 1   # re-run replaces, no duplicates
    hits = lib.find(_row(5, "FJAAK", "Spirit", "Original Mix", dur=302))
    assert len(hits) == 1 and hits[0].set_name == "Set A" and hits[0].pos == 1
    assert lib.find(_row(5, "Fjaak", "Spirit", dur=310)) == []          # > 3 s apart
    assert lib.find(_row(5, "Fjaak", "Spirit", "Some Remix")) == []
    assert lib.find(_row(5, "Fjaak", "Spirit"), exclude_set_id="aaaa1111") == []
    lib.save()
    other = LibraryIndex(tmp_path / "library.json")
    other.load()
    assert len(other.entries) == 1
    (d / "01 - Fjaak - Spirit.flac").unlink()
    assert other.find(_row(5, "Fjaak", "Spirit")) == [] and other.prune_missing() == 1


def test_rebuild_scans_set_folders(tmp_path):
    _set(tmp_path, "Set A", "aaaa1111")
    _set(tmp_path, "Set B", "bbbb2222")
    (tmp_path / "lib" / "not a set").mkdir()
    lib = LibraryIndex(tmp_path / "library.json")
    assert lib.rebuild(tmp_path / "lib") == 2
    assert {e.set_name for e in lib.entries} == {"Set A", "Set B"}


def test_corrupt_library_file_starts_empty(tmp_path):
    p = tmp_path / "library.json"
    p.write_text("{broken", encoding="utf-8")
    lib = LibraryIndex(p)
    lib.load()
    assert lib.entries == []
