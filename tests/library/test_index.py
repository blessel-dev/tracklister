"""Library index: keys, root files only, duration tolerance, rebuild from set.json.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tracklister.core.jsonio import write_json
from tracklister.core.layout import set_doc_path
from tracklister.core.model import DoubtKind, LibraryEntry, ResultState, RowResult, SetDoc, TrackRow
from tracklister.library.index import LibraryIndex, library_key


def _row(pos, artist, title, version=None, dur=None):
    return TrackRow(pos=pos, title=title, artists=[a.strip() for a in artist.split("&")], artist_display=artist,
                    version=version, expected_duration_s=dur)


def test_library_key():
    assert library_key("Fjaak & X", "Spirit", None) == library_key("FJAAK", "spirit", "Original Mix")
    assert library_key("Fjaak", "Spirit", "Extended Mix").endswith("|original")
    assert library_key("Chris Liebing", "Higher Things", "FJAAK Remix") != library_key("Chris Liebing", "Higher Things", None)
    assert library_key("Sigur R\u00f3s", "Gla\u00f0ur", None) == "sigur ros|gladur|original"


def test_r4_v_three_versions_three_keys(tmp_path):
    """Audit round 4, second review, B2: 'Spirit (Kai Remix) (Radio Edit)' was keyed 'radio edit', so «Usar
    el que ya tengo» offered the ORIGINAL's radio edit for it. Now the key keeps every version group."""
    keys = {v: library_key("Fjaak", "Spirit", v) for v in ("Kai Remix - Radio Edit", "Radio Edit", "Kai Remix")}
    assert len(set(keys.values())) == 3 and keys["Kai Remix - Radio Edit"] == "fjaak|spirit|kai remix radio edit"
    assert library_key("Fjaak", "Spirit", "(Kai Remix) [Radio Edit]") == keys["Kai Remix - Radio Edit"]
    assert library_key("Fjaak", "Spirit", "Kai Remix (Extended Mix)") == keys["Kai Remix"]
    assert library_key("Fjaak", "Spirit", "Original Mix - Extended Mix").endswith("|original")
    d = tmp_path / "lib" / "Set R"
    d.mkdir(parents=True)
    rows = [_row(1, "Fjaak", "Spirit", "Radio Edit"), _row(2, "Fjaak", "Spirit", "Kai Remix")]
    for r in rows:
        (d / f"0{r.pos} - Fjaak - Spirit ({r.version}).flac").write_bytes(b"x")
    doc = SetDoc(set_id="rrrr", name="Set R", preset_id="lossless", rows=rows, results={
        r.uid: RowResult(r.uid, r.pos, ResultState.VERIFICADO, file=f"0{r.pos} - Fjaak - Spirit ({r.version}).flac")
        for r in rows})
    lib = LibraryIndex(tmp_path / "library.json")
    assert lib.add_from_set(d, doc) == 2
    assert lib.find(_row(5, "Fjaak", "Spirit", "Kai Remix - Radio Edit")) == []
    assert [e.pos for e in lib.find(_row(5, "Fjaak", "Spirit", "Radio Edit"))] == [1]
    assert [e.pos for e in lib.find(_row(5, "Fjaak", "Spirit", "Kai Remix"))] == [2]


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


def test_fake_lossless_mark_travels_with_the_entry(tmp_path):
    d = tmp_path / "lib" / "Set M"
    d.mkdir(parents=True)
    r1, r2 = _row(1, "DJ Dextro", "Covil dos Abutres"), _row(2, "Fjaak", "Spirit")
    (d / "01 - DJ Dextro - Covil dos Abutres.flac").write_bytes(b"1")
    (d / "02 - Fjaak - Spirit.flac").write_bytes(b"2")
    doc = SetDoc(set_id="mmmm1111", name="Set M", preset_id="lossless", rows=[r1, r2], results={
        r1.uid: RowResult(r1.uid, 1, ResultState.DUDOSO, DoubtKind.ESPECTRO,
                          file="01 - DJ Dextro - Covil dos Abutres.flac",
                          flags=["posible_falso_lossless", "sin_duracion_esperada"]),
        r2.uid: RowResult(r2.uid, 2, ResultState.VERIFICADO, file="02 - Fjaak - Spirit.flac", flags=["sin_tags"]),
    })
    lib = LibraryIndex(tmp_path / "library.json")
    assert lib.add_from_set(d, doc) == 2
    flags = {e.pos: e.flags for e in lib.entries}
    assert flags == {1: ["posible_falso_lossless"], 2: []}         # only the marks a reuse must keep
    lib.save()
    again = LibraryIndex(tmp_path / "library.json")
    again.load()
    assert {e.pos: e.flags for e in again.entries} == flags


def test_old_library_file_without_flags_still_loads(tmp_path):
    old = {"key": "fjaak|spirit|original", "artist_norm": "fjaak", "title_norm": "spirit", "version_kind": "original",
           "path": str(tmp_path / "x.flac"), "set_id": "s", "set_name": "Viejo", "pos": 1, "duration_s": 30.0,
           "format": "flac", "size": 1, "added_at": "2026-10-01T10:00:00"}
    assert LibraryEntry.from_dict(old).flags == []
    write_json(tmp_path / "library.json", {"schema": "tracklister.library/1", "updated_at": None, "entries": [old]})
    lib = LibraryIndex(tmp_path / "library.json")
    lib.load()
    assert len(lib.entries) == 1 and lib.entries[0].flags == [] and lib.entries[0].set_name == "Viejo"


def _v1_entry(path, key, set_id, pos=1, flags=None):
    return {"key": key, "artist_norm": key.split("|")[0], "title_norm": key.split("|")[1],
            "version_kind": "remix", "path": str(path), "set_id": set_id, "set_name": "Viejo", "pos": pos,
            "duration_s": None, "format": "flac", "size": 1, "added_at": "2026-10-09T10:00:00",
            "flags": list(flags or [])}


def test_v101_a_1_0_0_library_is_re_keyed_from_its_sets_and_saved_as_v2(tmp_path):
    """R8: library.json /1 (1.0.0) keyed a version by its groups in written order. On load each set's
    entries are rebuilt from its own set.json with the 1.0.1 keys, so duplicates are still found."""
    from tracklister.core.jsonio import read_json
    d = tmp_path / "lib" / "Set V1"
    d.mkdir(parents=True)
    r1 = _row(1, "Fjaak", "Spirit", "Radio Edit - Kai Remix")
    r2 = _row(2, "Border One", "Spectral Tension")
    f1, f2 = "01 - Fjaak - Spirit (Radio Edit - Kai Remix).flac", "02 - Border One - Spectral Tension.flac"
    (d / f1).write_bytes(b"1")
    (d / f2).write_bytes(b"2")
    doc = SetDoc(set_id="v1v1", name="Set V1", preset_id="lossless", rows=[r1, r2], results={
        r1.uid: RowResult(r1.uid, 1, ResultState.VERIFICADO, file=f1),
        r2.uid: RowResult(r2.uid, 2, ResultState.DUDOSO, DoubtKind.ESPECTRO, file=f2,
                          flags=["posible_falso_lossless"])})
    write_json(set_doc_path(d), doc.to_dict())
    orphan = tmp_path / "suelto" / "x.flac"                      # its folder has no set.json any more
    orphan.parent.mkdir()
    orphan.write_bytes(b"3")
    write_json(tmp_path / "library.json", {"schema": "tracklister.library/1", "updated_at": None, "entries": [
        _v1_entry(d / f1, "fjaak|spirit|radio edit kai remix", "v1v1"),
        _v1_entry(d / f2, "border one|spectral tension|original", "v1v1", 2, ["posible_falso_lossless"]),
        _v1_entry(orphan, "x|y|original", "gone")]})
    lib = LibraryIndex(tmp_path / "library.json")
    lib.load()
    keys = sorted(e.key for e in lib.entries)
    assert keys == ["border one|spectral tension|original", "fjaak|spirit|kai remix radio edit", "x|y|original"]
    assert [e.pos for e in lib.find(_row(7, "Fjaak", "Spirit", "Kai Remix - Radio Edit"))] == [1]
    assert [e.pos for e in lib.find(_row(7, "Fjaak", "Spirit", "(Radio Edit) (Kai Remix)"))] == [1]
    assert next(e for e in lib.entries if e.pos == 2).flags == ["posible_falso_lossless"]
    assert read_json(tmp_path / "library.json")["schema"] == "tracklister.library/1"   # load() writes nothing
    lib.save()
    assert read_json(tmp_path / "library.json")["schema"] == "tracklister.library/2"
    again = LibraryIndex(tmp_path / "library.json")
    again.load()
    assert sorted(e.key for e in again.entries) == keys


def test_v101_a_quality_marked_file_enters_the_library_with_its_mark(tmp_path):
    d = tmp_path / "lib" / "Set Q"
    d.mkdir(parents=True)
    r = _row(1, "Border One", "Spectral Tension")
    (d / "01 - Border One - Spectral Tension.flac").write_bytes(b"1")
    doc = SetDoc(set_id="qqqq", name="Set Q", preset_id="lossless", rows=[r], results={
        r.uid: RowResult(r.uid, 1, ResultState.REVISAR_CALIDAD, file="01 - Border One - Spectral Tension.flac",
                         flags=["probable_mp3_convertido", "sin_tags"])})
    lib = LibraryIndex(tmp_path / "library.json")
    assert lib.add_from_set(d, doc) == 1
    assert lib.entries[0].flags == ["probable_mp3_convertido"]


def _foreign(real: Path) -> tuple[str, Path, Path]:
    """`real` as the OTHER system writes it, and what the old lookups made of that here: (the foreign path, the
    file it resolved to, the folder whose set.json the 1.0.0 re-key read). On a Mac a PC path ('C:\\...') is one
    relative name, looked up in the current folder; on a PC a Mac path ('/Users/...') lands on the current drive."""
    if os.sep == "/":
        foreign = "C:" + str(real).replace("/", "\\")
        return foreign, Path.cwd() / foreign, Path.cwd()
    foreign = str(real)[2:].replace("\\", "/")
    return foreign, real, real.parent


@pytest.mark.parametrize("schema", ["tracklister.library/1", "tracklister.library/2"])
def test_a_library_copied_from_the_other_system_offers_nothing_and_never_crashes(tmp_path, monkeypatch, schema):
    """1.1b: a library.json written on the other system names files that are not on this one. Before, such a
    path was looked up relative to the current folder (or drive): an unrelated set there re-keyed it, and a file
    there was offered as «Ya en biblioteca». Now its entries keep their keys, are never offered, and the library
    still loads and saves."""
    monkeypatch.chdir(tmp_path)
    foreign, resolves_to, rekey_dir = _foreign(tmp_path / "Set A" / "01 - Fjaak - Spirit.flac")
    assert not os.path.isabs(foreign)
    for f in (resolves_to, rekey_dir / "01 - Fjaak - Spirit.flac"):      # what the old lookups found
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"some other file")
    r = _row(1, "Fjaak", "Spirit")
    other = SetDoc(set_id="otro0001", name="Otro set", preset_id="lossless", rows=[r], results={
        r.uid: RowResult(r.uid, 1, ResultState.VERIFICADO, file="01 - Fjaak - Spirit.flac")})
    write_json(set_doc_path(rekey_dir), other.to_dict())
    write_json(tmp_path / "library.json", {"schema": schema, "updated_at": None, "entries": [
        _v1_entry(foreign, "fjaak|spirit|original", "pc000001")]})
    lib = LibraryIndex(tmp_path / "library.json")
    lib.load()
    assert [(e.set_name, e.key, e.path) for e in lib.entries] == [("Viejo", "fjaak|spirit|original", foreign)]
    assert lib.find(_row(5, "Fjaak", "Spirit")) == []
    lib.save()
    again = LibraryIndex(tmp_path / "library.json")
    again.load()
    assert [e.path for e in again.entries] == [foreign] and again.find(_row(5, "Fjaak", "Spirit")) == []
    assert again.prune_missing() == 1 and again.entries == []


def test_corrupt_library_file_starts_empty(tmp_path):
    p = tmp_path / "library.json"
    p.write_text("{broken", encoding="utf-8")
    lib = LibraryIndex(p)
    lib.load()
    assert lib.entries == []


def test_load_marks_a_damaged_index(tmp_path):
    """Barrido AG-03: an empty, cut or unknown library.json is not the same as no library: load() says so
    (damaged), so the next finalize rebuilds the index instead of saving it with only that set."""
    p = tmp_path / "library.json"
    lib = LibraryIndex(p)
    lib.load()
    assert lib.damaged is False and lib.entries == []           # no file yet: a new library
    for text in ("", "{broken", "[]", '{"schema": "otro"}'):
        p.write_text(text, encoding="utf-8")
        lib.load()
        assert lib.damaged is True and lib.entries == [], text
    write_json(p, {"schema": "tracklister.library/2", "updated_at": None, "entries": []})
    lib.load()
    assert lib.damaged is False


def test_rebuild_skips_an_unreadable_set_json(tmp_path, monkeypatch):
    """Barrido AG-03 (CL-41): rebuild() caught only ValueError, KeyError and TypeError, so one set.json that could
    not be read (a PermissionError) stopped «Reconstruir índice», and with it the rebuild of a damaged library.
    That set is now skipped, like a damaged one."""
    import tracklister.library.index as index_mod
    _set(tmp_path, "Set A", "aaaa1111")
    b, _ = _set(tmp_path, "Set B", "bbbb2222")
    real_read = index_mod.read_json

    def locked(path, *args, **kw):
        if Path(path) == set_doc_path(b):
            raise PermissionError(13, "Acceso denegado", str(path))
        return real_read(path, *args, **kw)
    monkeypatch.setattr(index_mod, "read_json", locked)
    lib = LibraryIndex(tmp_path / "library.json")
    assert lib.rebuild(tmp_path / "lib") == 1
    assert {e.set_name for e in lib.entries} == {"Set A"}
