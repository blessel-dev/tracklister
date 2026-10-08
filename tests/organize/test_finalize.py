"""place_verified (root vs _dudosos, idempotent) and sync_names (swaps through temp names).

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

from pathlib import Path

from tracklister.core.model import DoubtKind, ResultState, RowResult, TrackRow
from tracklister.organize.finalize import place_verified, sync_names
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
