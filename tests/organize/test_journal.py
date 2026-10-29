"""Journal: never overwrite, persisted, undo in reverse order.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import errno
import os
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


def test_a_damaged_journal_is_set_aside_and_a_new_one_starts(tmp_path):
    """Barrido AG-06: an empty or cut journal.json raised «JSON corrupto…» in Journal(), so the set could not be
    opened, continued or reordered although its music and set.json were fine. It is now kept as
    journal-danado.json and a new journal starts (the old undo history, already unreadable, is lost)."""
    from tracklister.core.layout import journal_path
    s = tmp_path / "set"
    s.mkdir()
    jp = journal_path(s)
    jp.parent.mkdir(parents=True)
    jp.write_text("{", encoding="utf-8")
    j = Journal(s)
    assert j.batches() == []
    assert (jp.parent / "journal-danado.json").read_text(encoding="utf-8") == "{"
    a = tmp_path / "a.flac"
    a.write_bytes(b"A")
    bid = j.begin("Reordenar")
    moved = j.move(bid, a, s / "01 - X.flac")
    j.commit(bid)
    again = Journal(s)                                         # the new journal was saved
    assert [b["label_es"] for b in again.batches()] == ["Reordenar"]
    assert again.undo_last() == [] and a.read_bytes() == b"A" and not moved.exists()


def _dies_after_10_bytes(src, dst, *args, **kw):
    """A copy killed halfway (a power cut, a forced close, a USB stick pulled out): 10 bytes, then gone. Not an
    OSError, so no `except OSError` cleans it up."""
    with open(dst, "wb") as f:
        f.write(b"x" * 10)
    raise KeyboardInterrupt


def test_a_copy_killed_halfway_leaves_nothing_under_the_final_name(tmp_path, monkeypatch):
    """Barrido CL-34: «Usar el que ya tengo» and the _originales copies wrote straight to the final name, so a
    copy killed halfway left a cut file with the track's name; the next run then put the good one at ' (2)'.
    The data now goes to '<name>.part', which gets the final name only once it is whole."""
    s = tmp_path / "set"
    s.mkdir()
    a = tmp_path / "a.flac"
    a.write_bytes(b"A" * 1000)
    j = Journal(s)
    bid = j.begin("Usar el que ya tengo")
    monkeypatch.setattr(shutil, "copy2", _dies_after_10_bytes)
    with pytest.raises(KeyboardInterrupt):
        j.copy(bid, a, s / "01 - X.flac")
    assert not (s / "01 - X.flac").exists()
    assert not (s / "01 - X.flac.part").exists() and a.read_bytes() == b"A" * 1000


def test_a_move_to_another_drive_killed_halfway_leaves_nothing_under_the_final_name(tmp_path, monkeypatch):
    """Barrido CL-34: a library on another drive (a USB stick, an external disk). shutil.move cannot rename
    across drives, so it copies and then deletes the source; that copy went straight to the final name."""
    s = tmp_path / "set"
    s.mkdir()
    a = tmp_path / "a.flac"
    a.write_bytes(b"A" * 1000)
    j = Journal(s)
    bid = j.begin("Pasada 1: lossless")

    def cross_device(src, dst, *args, **kw):
        raise OSError(errno.EXDEV, "cross-device", src)
    monkeypatch.setattr(os, "rename", cross_device)            # another drive: shutil.move falls back to a copy
    monkeypatch.setattr(shutil, "copyfile", _dies_after_10_bytes)
    try:
        import _winapi                                          # Windows: shutil.copy2 copies with CopyFile2
        if hasattr(_winapi, "CopyFile2"):
            monkeypatch.setattr(_winapi, "CopyFile2", _dies_after_10_bytes)
    except ImportError:
        pass
    with pytest.raises(KeyboardInterrupt):
        j.move(bid, a, s / "01 - X.flac")
    assert not (s / "01 - X.flac").exists() and not (s / "01 - X.flac.part").exists()
    assert a.read_bytes() == b"A" * 1000                       # the source is still there, whole


def test_a_part_locked_for_a_moment_still_gets_its_name(tmp_path, monkeypatch):
    """Barrido audit AU-2-01: on Windows an antivirus or the indexer can hold a just-written file for a moment.
    Since the copies go through '<name>.part' (Z.3), a PermissionError on the rename of that '.part' failed the
    copy at once (the row ended «Fallida»), where the copy straight to the final name of T had no rename at all.
    The rename is now retried, as write_json does for journal.json."""
    s = tmp_path / "set"
    s.mkdir()
    a, b = tmp_path / "a.flac", tmp_path / "b.flac"
    a.write_bytes(b"A" * 1000)
    b.write_bytes(b"B" * 1000)
    real_replace = os.replace
    locked = []

    def locked_once(src, dst, *args, **kw):
        if os.fspath(src).endswith(".part") and os.fspath(src) not in locked:
            locked.append(os.fspath(src))
            raise PermissionError(errno.EACCES, "held by another process", os.fspath(src))
        return real_replace(src, dst, *args, **kw)
    monkeypatch.setattr(os, "replace", locked_once)
    j = Journal(s)
    bid = j.begin("Usar el que ya tengo")
    copied = j.copy(bid, a, s / "01 - X.flac", uid="u1")

    def cross_device(src, dst, *args, **kw):
        raise OSError(errno.EXDEV, "cross-device", src)
    monkeypatch.setattr(os, "rename", cross_device)            # another drive: shutil.move copies through a .part
    moved = j.move(bid, b, s / "02 - Y.flac", uid="u2")
    j.commit(bid)
    assert len(locked) == 2                                    # each rename met the lock once
    assert copied.name == "01 - X.flac" and copied.read_bytes() == b"A" * 1000 and a.exists()
    assert moved.name == "02 - Y.flac" and moved.read_bytes() == b"B" * 1000 and not b.exists()
    assert not list(s.glob("*.part"))


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
