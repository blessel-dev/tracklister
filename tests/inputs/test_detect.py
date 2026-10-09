"""What was dropped or pasted: files, links, text."""
from __future__ import annotations

from pathlib import Path

import pytest

from tracklister.inputs.detect import InputKind, as_path, detect, normalize_url

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "inputs"
SAMPLE = FIX / "fjaak-techno-dj-set-section-may-2026.csv"


@pytest.mark.parametrize("url,kind", [
    ("https://www.youtube.com/watch?v=mD9ELt_Pvp4", InputKind.YOUTUBE),
    ("https://youtu.be/mD9ELt_Pvp4?si=abc", InputKind.YOUTUBE),
    ("https://m.youtube.com/watch?v=mD9ELt_Pvp4&list=PL1", InputKind.YOUTUBE),
    ("https://music.youtube.com/watch?v=x", InputKind.YOUTUBE),
    ("www.youtube.com/live/abc", InputKind.YOUTUBE),
    ("  https://soundcloud.com/plotsklap/tekka  ", InputKind.SOUNDCLOUD),
    ("https://on.soundcloud.com/AbCd", InputKind.SOUNDCLOUD),
    ("https://trackid.net/audiostreams/fjaak-techno-dj-set-section-may-2026", InputKind.TRACKID_URL),
    ("https://www.1001tracklists.com/tracklist/abc/x.html", InputKind.PASTE_ONLY_URL),
    ("https://www.mixesdb.com/w/2022-x", InputKind.PASTE_ONLY_URL),
    ("https://www.mixcloud.com/blessel/chapter-i/", InputKind.OTHER_URL),
    ("https://notyoutube.com/watch?v=x", InputKind.OTHER_URL),
])
def test_links(url, kind):
    assert detect(url) == kind


def test_files():
    assert detect(SAMPLE) == InputKind.TRACKID_CSV
    assert detect(str(SAMPLE)) == InputKind.TRACKID_CSV
    assert detect(f'"{SAMPLE}"') == InputKind.TRACKID_CSV            # Windows "Copy as path"
    assert detect(SAMPLE.as_uri()) == InputKind.TRACKID_CSV          # file:// from a drop
    assert detect(FIX / "fjaak.xlsx") == InputKind.TRACKID_CSV
    assert detect(FIX / "fjaak-tab-utf16.txt") == InputKind.TRACKID_CSV
    assert detect(FIX / "sin-pos.csv") == InputKind.TABLE
    assert detect(FIX / "MAYUSCULAS.CSV") == InputKind.TABLE
    assert detect(FIX / "mi-lista.xlsx") == InputKind.TABLE
    assert detect(FIX / "tracklist.txt") == InputKind.TEXT
    assert detect(Path("C:/no/existe/lista.xls")) == InputKind.XLS_UNSUPPORTED
    assert detect("C:\\no\\existe\\set.csv") == InputKind.TABLE      # the importer says it is missing


def test_text():
    assert detect("00:00 Phara - Grey Ribbon\n05:10 Klint - Gunslingers") == InputKind.TEXT
    assert detect("Phara - Grey Ribbon") == InputKind.TEXT
    assert detect("Tracklist:\nhttps://www.youtube.com/watch?v=x\n1. A - B") == InputKind.TEXT
    assert detect("") == InputKind.TEXT


def test_helpers():
    assert normalize_url("www.youtube.com/watch?v=x") == "https://www.youtube.com/watch?v=x"
    assert normalize_url("soundcloud.com/a/b") == "https://soundcloud.com/a/b"
    assert normalize_url("Phara - Grey Ribbon") is None
    assert as_path("https://example.com/lista.csv") is None
    assert as_path("Phara - Grey Ribbon") is None
    assert as_path("lista.csv") == Path("lista.csv")
