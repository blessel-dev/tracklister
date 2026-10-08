"""Names from the row index, Windows-safe, long paths."""
from __future__ import annotations

import os
import unicodedata

from tracklister.core.model import TrackRow
from tracklister.organize.naming import pad_width, safe_component, track_filename, unique_path, win_long


def _row(pos, artist, title, version=None):
    return TrackRow(pos=pos, title=title, artists=[artist], artist_display=artist, version=version)


def test_reserved_characters_and_device_names():
    assert safe_component('AC/DC: "Live" <in> Rio? *|\\') == "AC DC Live in Rio"
    assert safe_component("CON") == "_CON" and safe_component("con.txt") == "_con.txt"
    assert safe_component("LPT1") == "_LPT1" and safe_component("Console") == "Console"
    assert safe_component("Name. . ") == "Name" and safe_component("  ") == "_"
    assert safe_component("tab\there\x01") == "tab here"


def test_track_filename_uses_row_index_and_version():
    r = _row(3, "Chris Liebing", "Higher Things", "FJAAK Remix")
    assert track_filename(r, ".FLAC", 2) == "03 - Chris Liebing - Higher Things (FJAAK Remix).flac"
    assert track_filename(_row(7, "A", "B"), "mp3", 3) == "007 - A - B.mp3"
    assert pad_width(99) == 2 and pad_width(100) == 3


def test_device_name_inside_a_track_name_is_kept():
    assert track_filename(_row(1, "CON", "AUX"), ".wav", 2) == "01 - CON - AUX.wav"


def test_nfd_input_becomes_nfc_and_quotes():
    nfd = unicodedata.normalize("NFD", "H\u00e9ctor Oaks")
    name = track_filename(_row(2, nfd, "Cuerpo S\u00f3lido"), ".mp3", 2)
    assert name == "02 - H\u00e9ctor Oaks - Cuerpo S\u00f3lido.mp3" and unicodedata.is_normalized("NFC", name)
    assert track_filename(_row(9, "Ferdinger", "I\u2019m Still Here"), ".mp3", 2) == "09 - Ferdinger - I'm Still Here.mp3"


def test_long_title_truncated_first():
    r = _row(4, "Larga", "Titulo Larguisimo " * 20, "Some Remix")
    name = track_filename(r, ".flac", 2)
    assert len(name) <= 180 and name.startswith("04 - Larga - Titulo") and name.endswith("(Some Remix).flac")


def test_long_paths_over_260_chars(tmp_path):
    deep = tmp_path
    for i in range(6):
        deep = deep / (f"carpeta-{i}-" + "x" * 40)
    target = deep / track_filename(_row(1, "Artista", "T" * 120), ".flac", 2)
    assert len(str(target)) > 260
    os.makedirs(win_long(target.parent), exist_ok=True)
    with open(win_long(target), "wb") as f:
        f.write(b"data")
    assert os.path.exists(win_long(target))
    assert win_long(target).startswith("\\\\?\\")


def test_unique_path(tmp_path):
    p = tmp_path / "01 - A - B.flac"
    assert unique_path(p) == p
    p.write_bytes(b"1")
    assert unique_path(p).name == "01 - A - B (2).flac"
    (tmp_path / "01 - A - B (2).flac").write_bytes(b"2")
    assert unique_path(p).name == "01 - A - B (3).flac"
