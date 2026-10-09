"""Engine CSV: quoting, no BOM, LF, ORIGINAL not appended, empty title refused, snum order.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import csv

import pytest

from tracklister.core.model import TrackRow
from tracklister.engine.csvwriter import write_engine_csv


def _row(pos, artist, title, version=None, length=None, **kw):
    return TrackRow(pos=pos, title=title, artists=[a.strip() for a in artist.split("&")],
                    artist_display=artist, version=version, expected_duration_s=length, **kw)


def test_csv_shape_and_manifest(tmp_path):
    rows = [
        _row(5, "Chris Liebing", "Higher Things", "FJAAK Remix", 289),
        _row(2, "Blasha & Allatt", "Dust 1", "Original Mix", 400),
        _row(9, 'Comma, "Quoted"', "Say, \"Hi\"\nthere"),
        _row(3, "Sigur Ros", "Gla\u00f0ur", "Extended Mix"),
    ]
    p = tmp_path / "input.csv"
    m = write_engine_csv(rows, p)
    raw = p.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw
    text = raw.decode("utf-8")
    lines = text.split("\n")
    assert lines[0] == '"Artist","Title","Length"'
    assert lines[1] == '"Blasha","Dust 1","400"'          # primary artist, ORIGINAL not appended
    assert lines[2] == '"Sigur Ros","Gla\u00f0ur (Extended Mix)",""'
    assert lines[3] == '"Chris Liebing","Higher Things (FJAAK Remix)","289"'
    assert lines[4] == '"Comma, ""Quoted""","Say, ""Hi"" there",""'
    assert text.endswith("\n") and lines[5] == ""
    parsed = list(csv.reader(text.splitlines()))
    assert parsed[4] == ['Comma, "Quoted"', 'Say, "Hi" there', ""]
    assert [(x.snum, x.pos) for x in m] == [(1, 2), (2, 3), (3, 5), (4, 9)]
    assert m[2].title == "Higher Things (FJAAK Remix)" and m[2].length == 289 and m[3].length is None
    assert {x.uid for x in m} == {r.uid for r in rows}


@pytest.mark.parametrize("version,title", [
    ("Kai Remix - Radio Edit", "Spirit (Kai Remix)"), ("Radio Edit - Kai Remix", "Spirit (Kai Remix)"),
    ("Kai Remix - Edit", "Spirit (Kai Remix)"), ("Kai Remix - Live", "Spirit (Kai Remix)"),
    ("Kai Remix - Instrumental", "Spirit (Kai Remix)"), ("Kai Remix - Remastered", "Spirit (Kai Remix)"),
    ("(Kai Remix) (Radio Edit)", "Spirit (Kai Remix)"), ("Kai Remix (Extended Mix)", "Spirit (Kai Remix)"),
    ("Live - Radio Edit", "Spirit (Radio Edit)"),
    # one group: as always
    ("Kai Remix", "Spirit (Kai Remix)"), ("Radio Edit", "Spirit (Radio Edit)"), ("Extended Mix", "Spirit (Extended Mix)"),
    ("Original Mix", "Spirit"), (None, "Spirit"), ("Live at Awakenings", "Spirit (Live at Awakenings)"),
])
def test_r4_v_engine_title_asks_for_the_remixer_of_a_version_with_several_groups(tmp_path, version, title):
    """Audit round 4, second review, B2: the row 'Spirit (Kai Remix) (Radio Edit)' was searched as 'Spirit
    (Radio Edit)': --strict-title (a literal part of the file name) let the ORIGINAL's radio edit through and
    refused 'Spirit (Kai Remix) (Radio Edit)'. Now the engine is asked for the remix; the verification and
    --length-tol tell its edits apart."""
    from tracklister.engine.csvwriter import engine_title
    row = _row(1, "Fjaak", "Spirit", version)
    assert engine_title(row) == title
    p = tmp_path / "input.csv"
    (item,) = write_engine_csv([row], p)
    assert item.title == title and p.read_text(encoding="utf-8").splitlines()[1] == f'"Fjaak","{title}",""'


def test_csv_refuses_empty_title_and_unchecked_rows(tmp_path):
    with pytest.raises(ValueError):
        write_engine_csv([_row(1, "Artist", "  ")], tmp_path / "a.csv")
    with pytest.raises(ValueError):
        write_engine_csv([_row(1, "Artist", "T", download=False)], tmp_path / "b.csv")


def test_csv_no_url_like_columns(tmp_path):
    write_engine_csv([_row(1, "A", "T")], tmp_path / "c.csv")
    header = (tmp_path / "c.csv").read_text(encoding="utf-8").splitlines()[0].lower()
    for bad in ("id", "url", "uri"):
        assert f'"{bad}"' not in header
