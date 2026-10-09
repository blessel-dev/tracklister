"""Journal: never overwrite, persisted, undo in reverse order.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import shutil

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
