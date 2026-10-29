"""place_verified (root vs _dudosos, idempotent) and sync_names (swaps through temp names).

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tracklister.core.model import DoubtKind, ResultState, RowResult, TrackRow
from tracklister.organize.finalize import RenameError, place_verified, stray_audio_files, sync_names
from tracklister.organize.journal import Journal
from tracklister.verify.verifier import Verdict


def _row(pos, title="T"):
    return TrackRow(pos=pos, title=title, artists=["A"], artist_display="A")


def _verdict(doubt=None):
    return Verdict(ResultState.DUDOSO if doubt else ResultState.VERIFICADO, doubt, 90, [], [], None)


def _file(p: Path, data=b"audio"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_place_root_and_quarantine(tmp_path):
    s = tmp_path / "set"
    j = Journal(s)
    bid = j.begin("x")
    r1 = place_verified(s, _row(1, "Uno"), _file(tmp_path / "in/1/x.flac"), _verdict(), 2, j, bid)
    r2 = place_verified(s, _row(2, "Dos"), _file(tmp_path / "in/2/y.flac"), _verdict(DoubtKind.VERSION), 2, j, bid)
    r3 = place_verified(s, _row(3, "Tres"), _file(tmp_path / "in/3/z.flac"), _verdict(DoubtKind.ESPECTRO), 2, j, bid)
    assert r1 == "01 - A - Uno.flac" and r2 == "_dudosos/02 - A - Dos.flac" and r3 == "03 - A - Tres.flac"
    assert (s / r1).exists() and (s / r2).exists()


def test_place_is_idempotent_and_never_overwrites(tmp_path):
    s = tmp_path / "set"
    j = Journal(s)
    bid = j.begin("x")
    first = place_verified(s, _row(1), _file(tmp_path / "a.flac", b"same"), _verdict(), 2, j, bid)
    again_src = _file(tmp_path / "b.flac", b"same")
    assert place_verified(s, _row(1), again_src, _verdict(), 2, j, bid) == first and not again_src.exists()
    other = place_verified(s, _row(1), _file(tmp_path / "c.flac", b"different"), _verdict(), 2, j, bid)
    assert other == "01 - A - T (2).flac" and (s / first).read_bytes() == b"same"


def test_sync_names_swaps(tmp_path):
    s = tmp_path / "set"
    rows = [_row(1, "Uno"), _row(2, "Dos")]
    res = {}
    j = Journal(s)
    bid = j.begin("x")
    for r in rows:
        f = place_verified(s, r, _file(tmp_path / f"{r.title}.flac", r.title.encode()), _verdict(), 2, j, bid)
        res[r.uid] = RowResult(uid=r.uid, pos=r.pos, state=ResultState.VERIFICADO, file=f)
    j.commit(bid)
    rows[0].pos, rows[1].pos = 2, 1                       # the user swapped the two rows
    assert sync_names(s, rows, res, j) == 2
    assert (s / "01 - A - Dos.flac").read_bytes() == b"Dos" and (s / "02 - A - Uno.flac").read_bytes() == b"Uno"
    assert res[rows[0].uid].file == "02 - A - Uno.flac"
    assert sync_names(s, rows, res, j) == 0               # idempotent
    assert j.undo_last() == []
    assert (s / "01 - A - Uno.flac").read_bytes() == b"Uno"


def test_sync_names_renames_the_copy_in_originales_too(tmp_path):
    """CDJ antiguos: after reordering the table, the FLAC kept in _originales gets the new number in the
    same journal batch as its AIFF (undo puts both back)."""
    s = tmp_path / "set"
    rows = [_row(1, "Uno"), _row(2, "Dos")]
    res = {}
    for r in rows:
        f = _file(s / f"{r.pos:02d} - A - {r.title}.aiff", r.title.encode())
        o = _file(s / "_originales" / f"{r.pos:02d} - A - {r.title}.flac", b"orig-" + r.title.encode())
        res[r.uid] = RowResult(uid=r.uid, pos=r.pos, state=ResultState.VERIFICADO, file=f.name,
                               original_file=f"_originales/{o.name}")
    j = Journal(s)
    rows[0].pos, rows[1].pos = 2, 1
    assert sync_names(s, rows, res, j) == 4
    uno, dos = res[rows[0].uid], res[rows[1].uid]
    assert (uno.file, uno.original_file) == ("02 - A - Uno.aiff", "_originales/02 - A - Uno.flac")
    assert (dos.file, dos.original_file) == ("01 - A - Dos.aiff", "_originales/01 - A - Dos.flac")
    assert (s / "_originales" / "02 - A - Uno.flac").read_bytes() == b"orig-Uno"
    assert (s / "_originales" / "01 - A - Dos.flac").read_bytes() == b"orig-Dos"
    assert len(j.batches()) == 1 and j.batches()[0]["committed"]
    assert sync_names(s, rows, res, j) == 0
    assert j.undo_last() == []
    assert (s / "_originales" / "01 - A - Uno.flac").read_bytes() == b"orig-Uno"
    assert (s / "01 - A - Uno.aiff").read_bytes() == b"Uno"


# ---- external audit, round 4 (claude-audit-raw-r4-1.txt) ---------------------------------------------

def _rotated_set(tmp_path):
    """3 verified files; the table was rotated (C first): every file needs a new number."""
    s = tmp_path / "set"
    rows = [_row(1, "A"), _row(2, "B"), _row(3, "C")]
    res = {}
    for r in rows:
        f = _file(s / f"{r.pos:02d} - A - {r.title}.flac", b"audio-" + r.title.encode())
        res[r.uid] = RowResult(uid=r.uid, pos=r.pos, state=ResultState.VERIFICADO, file=f.name)
    rows[0].pos, rows[1].pos, rows[2].pos = 2, 3, 1
    return s, rows, res


def _folder(s: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in s.iterdir() if p.is_file()}


@pytest.mark.parametrize("fail_on", [2, 5], ids=["phase-1", "phase-2"])
def test_r4_b4_a_rename_that_fails_puts_every_name_back(tmp_path, monkeypatch, fail_on):
    """B4: a failed rename (WinError 32: the file is open in Ableton) used to leave files under
    __tracklister_tmp_* names, with the batch committed and nothing undone, and those rows were then
    downloaded again. Now the batch is reverted, the folder keeps its names and the results are not
    touched; a later call renames everything."""
    import shutil

    s, rows, res = _rotated_set(tmp_path)
    before = _folder(s)
    before_res = {u: (r.file, r.original_file, r.pos) for u, r in res.items()}
    j = Journal(s)
    real_move, calls = shutil.move, {"n": 0}

    def flaky(src, dst, *a, **kw):
        calls["n"] += 1
        if calls["n"] == fail_on:
            raise PermissionError(13, "El proceso no tiene acceso al archivo porque está siendo utilizado por "
                                      "otro proceso", src)
        return real_move(src, dst, *a, **kw)
    monkeypatch.setattr(shutil, "move", flaky)
    with pytest.raises(OSError) as e:
        sync_names(s, rows, res, j)
    assert isinstance(e.value, RenameError)
    # the 2nd and the 5th move are both B's (02): the message names the file as the user knows it
    assert e.value.msg_es == ("No se pudo cambiar el nombre de '02 - A - B.flac': está abierto en otro programa "
                              "(Ableton, un reproductor…). Ciérralo y vuelve a pulsar Descargar.")
    assert _folder(s) == before and not list(s.glob("__tracklister_tmp_*"))
    assert {u: (r.file, r.original_file, r.pos) for u, r in res.items()} == before_res
    assert all(b["committed"] for b in Journal(s).batches()) and Journal(s).batches() == []
    monkeypatch.setattr(shutil, "move", real_move)
    assert sync_names(s, rows, res, j) == 3
    assert _folder(s) == {"01 - A - C.flac": b"audio-C", "02 - A - A.flac": b"audio-A", "03 - A - B.flac": b"audio-B"}
    assert [res[r.uid].file for r in rows] == ["02 - A - A.flac", "03 - A - B.flac", "01 - A - C.flac"]


@pytest.mark.skipif(os.name != "nt", reason="Windows file locks (no FILE_SHARE_DELETE)")
def test_r4_b4_a_file_really_open_in_another_program_leaves_the_folder_as_it_was(tmp_path):
    """The real Windows case: the file is open (Python opens files without FILE_SHARE_DELETE, like many
    players), so renaming it fails, and shutil.move then copies it and cannot delete the original. No copy
    and no temporary name may stay behind."""
    s, rows, res = _rotated_set(tmp_path)
    before = _folder(s)
    j = Journal(s)
    with open(s / "02 - A - B.flac", "rb"):
        with pytest.raises(RenameError) as e:
            sync_names(s, rows, res, j)
        assert "'02 - A - B.flac': está abierto en otro programa" in e.value.msg_es
        assert sorted(p.name for p in s.iterdir() if p.is_file()) == sorted(before)
    assert _folder(s) == before and Journal(s).batches() == []
    assert sync_names(s, rows, res, j) == 3 and "01 - A - C.flac" in _folder(s)


def test_a_revert_that_also_fails_names_what_stayed(tmp_path, monkeypatch):
    """CL-41: when a rename fails and putting the names back fails too (a USB stick pulled out halfway), the
    notice says what stayed: «Además, no se pudo dejar todo como estaba:» and a line per file. No test covered
    that branch."""
    import errno
    import shutil

    s, rows, res = _rotated_set(tmp_path)
    real_move, calls = shutil.move, {"n": 0}

    def gone(src, dst, *a, **kw):
        calls["n"] += 1
        if calls["n"] >= 5:                     # B's rename in phase 2, then every move of the revert
            raise OSError(errno.EIO, "Input/output error", src)
        return real_move(src, dst, *a, **kw)
    monkeypatch.setattr(shutil, "move", gone)
    with pytest.raises(RenameError) as e:
        sync_names(s, rows, res, Journal(s))
    msg = e.value.msg_es
    assert msg.startswith("No se pudo cambiar el nombre de '02 - A - B.flac' (Input/output error)."), msg
    assert "Además, no se pudo dejar todo como estaba:" in msg and "No se pudo deshacer " in msg, msg


APPLEDOUBLE = b"\x00\x05\x16\x07" + b"\x00\x02\x00\x00" + b"Mac OS X        " + bytes(4096 - 24)


def _mac_usb_set(tmp_path):
    """A set folder on a USB stick a Mac has written to: every file has its 4 KB AppleDouble twin."""
    s = tmp_path / "set"
    _file(s / "01 - A - B.flac")
    _file(s / "._01 - A - B.flac", APPLEDOUBLE)
    _file(s / "_dudosos" / "02 - A - C.flac")
    _file(s / "_dudosos" / "._02 - A - C.flac", APPLEDOUBLE)
    res = [RowResult(uid="u", pos=1, state=ResultState.VERIFICADO, file="01 - A - B.flac"),
           RowResult(uid="v", pos=2, state=ResultState.DUDOSO, file="_dudosos/02 - A - C.flac")]
    return s, res


@pytest.mark.parametrize("plat", ["as_macos", "as_windows"])
def test_appledouble_files_are_never_strays(plat, request, tmp_path):
    """Report 3.1 point 24, and brief mac-1 Addendum 2: the '._*' files a Mac leaves on an exFAT/FAT stick are
    metadata, not audio, on every platform (the stick moves between Macs and PCs). An intentional Windows fix."""
    request.getfixturevalue(plat)
    s, res = _mac_usb_set(tmp_path)
    assert stray_audio_files(s, res) == []
    _file(s / "03 - A - Borrada.flac")
    assert stray_audio_files(s, res) == ["03 - A - Borrada.flac"]       # a real stray is still listed
    assert (s / "._01 - A - B.flac").read_bytes() == APPLEDOUBLE        # nothing touched
    assert (s / "_dudosos" / "._02 - A - C.flac").read_bytes() == APPLEDOUBLE


def test_stray_audio_files_lists_what_no_result_points_to(tmp_path):
    s = tmp_path / "set"
    _file(s / "01 - A - Uno.flac")
    _file(s / "02 - A - Borrada.flac")
    _file(s / "_dudosos" / "03 - A - Vieja.flac")
    _file(s / "_originales" / "01 - A - Uno.flac")
    _file(s / "Informe - set.txt")
    res = [RowResult(uid="u", pos=1, state=ResultState.VERIFICADO, file="01 - A - Uno.flac",
                     original_file="_originales/01 - A - Uno.flac")]
    assert stray_audio_files(s, res) == ["02 - A - Borrada.flac", "_dudosos/03 - A - Vieja.flac"]
    assert stray_audio_files(tmp_path / "no-existe", res) == []
