"""Journal: never overwrite, persisted, undo in reverse order.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tracklister.organize.journal import Journal


def test_move_copy_never_overwrite_and_undo(tmp_path):
    s = tmp_path / "set"
    s.mkdir()
    a, b = tmp_path / "a.flac", tmp_path / "b.flac"
    a.write_bytes(b"A")
    b.write_bytes(b"B")
    (s / "01 - X.flac").write_bytes(b"old")
    j = Journal(s)
    bid = j.begin("prueba")
    d1 = j.move(bid, a, s / "01 - X.flac", uid="u1")
    d2 = j.copy(bid, b, s / "_dudosos" / "02 - Y.flac", uid="u2")
    j.commit(bid)
    assert d1.name == "01 - X (2).flac" and (s / "01 - X.flac").read_bytes() == b"old"
    assert d2.exists() and b.exists()
    j2 = Journal(s)                                     # persisted
    assert [x["label_es"] for x in j2.batches()] == ["prueba"]
    assert j2.undo_last() == []
    assert a.read_bytes() == b"A" and not d1.exists() and not d2.exists() and not (s / "_dudosos").exists()
    assert (s / "01 - X.flac").read_bytes() == b"old" and j2.batches() == []
    assert j2.undo_last() == ["No hay nada que deshacer."]


def test_undo_never_overwrites_and_keeps_the_op(tmp_path):
    s = tmp_path / "set"
    s.mkdir()
    a = tmp_path / "a.flac"
    a.write_bytes(b"A")
    j = Journal(s)
    bid = j.begin("x")
    j.move(bid, a, s / "01.flac")
    j.commit(bid)
    a.write_bytes(b"new file in the old place")
    errs = j.undo_last()
    assert errs and "no se sobrescribe" in errs[0]
    assert (s / "01.flac").exists() and a.read_bytes() == b"new file in the old place"
    assert len(j.batches()) == 1


def test_r3_n2_a_copy_that_fails_leaves_no_half_file_and_discard_reverts_the_batch(tmp_path, monkeypatch):
    """Audit round 3, N2: a copy that dies halfway (a full disk) leaves nothing under the final name,
    and discard() reverts what the unfinished batch already did and closes it."""
    s = tmp_path / "set"
    s.mkdir()
    a, b = tmp_path / "a.flac", tmp_path / "b.flac"
    a.write_bytes(b"A" * 1000)
    b.write_bytes(b"B" * 1000)
    real_copy2 = shutil.copy2

    def half_then_full_disk(src, dst, *args, **kw):
        if "02 - Y" in str(dst):
            with open(dst, "wb") as f:
                f.write(b"B" * 10)
            raise OSError(28, "No queda espacio en el disco")
        return real_copy2(src, dst, *args, **kw)
    monkeypatch.setattr(shutil, "copy2", half_then_full_disk)
    j = Journal(s)
    bid = j.begin("Usar el que ya tengo")
    done = j.copy(bid, a, s / "_originales" / "01 - X.flac", uid="u1")
    with pytest.raises(OSError):
        j.copy(bid, b, s / "02 - Y.flac", uid="u2")
    assert done.is_file() and not (s / "02 - Y.flac").exists()          # no half file
    with pytest.raises(KeyError):
        j.discard("otro-lote")
    assert j.discard(bid) == []
    assert not (s / "_originales").exists() and a.exists() and b.exists()   # sources untouched
    assert j.batches() == [] and Journal(s).batches() == []


# ---- external audit, round 4 (claude-audit-raw-r4-1.txt) ---------------------------------------------

def test_r4_b5_mkdir_on_a_drive_that_is_gone_fails_at_once(tmp_path, monkeypatch):
    """B5: the parent of 'Q:\\' is 'Q:\\' itself, so walking up to the first existing folder never ended
    when the library drive (a USB or network disk) was unplugged: the run hung and Cancelar could not
    stop it. Now it is a FileNotFoundError (an OSError) straight away, and nothing is recorded."""
    import tracklister.organize.journal as journal_mod
    from tests.fakes.gone_drive import unplug_drive

    s = tmp_path / "set"
    s.mkdir()
    j = Journal(s)
    bid = j.begin("Pasada 1: lossless")
    calls = unplug_drive(monkeypatch, journal_mod)
    for gone in (Path("Q:/Sets/S/_dudosos"), Path("//servidor/recurso/Sets/S"), s / "_dudosos"):
        with pytest.raises(FileNotFoundError) as e:
            j.mkdir(bid, gone)
        assert e.value.strerror == journal_mod.DRIVE_GONE_ES and e.value.filename == str(gone)
    assert calls["isdir"] < 100
    with pytest.raises(FileNotFoundError):
        j.move(bid, tmp_path / "a.flac", Path("Q:/Sets/S/01 - X.flac"))
    assert j.batches()[0]["ops"] == []                       # nothing recorded


def test_r4_b5_mkdir_still_creates_and_records_the_missing_levels(tmp_path):
    s = tmp_path / "set"
    s.mkdir()
    j = Journal(s)
    bid = j.begin("x")
    j.mkdir(bid, s / "_dudosos")
    j.mkdir(bid, s / "_originales" / "dentro")
    assert (s / "_dudosos").is_dir() and (s / "_originales" / "dentro").is_dir()
    ops = j.batches()[0]["ops"]
    assert [(o["op"], Path(o["dst"]).relative_to(s).as_posix()) for o in ops] == [
        ("mkdir", "_dudosos"), ("mkdir", "_originales"), ("mkdir", "_originales/dentro")]
