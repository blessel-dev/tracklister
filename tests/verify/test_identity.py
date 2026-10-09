"""Identity scores: tags first, file-name fallback, version rule, track numbers.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import pytest

from tests.fakes.synth import make_track
from tracklister.core.model import TrackRow
from tracklister.verify.audioinfo import probe
from tracklister.verify.identity import (
    NUMBER_MISMATCH_MAX, artist_similarity, identity_score, number_tokens, parse_name, strip_track_number,
    title_similarity,
)


def _row(artist, title, version=None):
    return TrackRow(pos=1, title=title, artists=[a.strip() for a in artist.split("&")], artist_display=artist,
                    version=version)


def _info(tmp_path, name, tags=None):
    return probe(make_track(tmp_path / name, fmt="flac", seconds=2, tags=tags))


def test_tags_match(tmp_path):
    s = identity_score(_row("Fjaak", "Spirit"), _info(tmp_path, "x.flac", {"artist": "FJAAK", "title": "Spirit"}), None)
    assert s.artist == 100 and s.title == 100 and s.version_ok and s.evidence == "tags"


def test_original_vs_remix_in_tags(tmp_path):
    info = _info(tmp_path, "x.flac", {"artist": "Fjaak", "title": "Spirit (Kai Van Dongen Remix)"})
    s = identity_score(_row("Fjaak", "Spirit"), info, None)
    assert s.title == 100 and not s.version_ok and "original" in s.version_reason_es


def test_remix_needs_the_remixer(tmp_path):
    want = _row("Chris Liebing", "Higher Things", "FJAAK Remix")
    ok = _info(tmp_path, "a.flac", {"artist": "Chris Liebing", "title": "Higher Things (Fjaak Remix)"})
    assert identity_score(want, ok, None).version_ok
    orig = _info(tmp_path, "b.flac", {"artist": "Chris Liebing", "title": "Higher Things (Original Mix)"})
    assert not identity_score(want, orig, None).version_ok
    other = _info(tmp_path, "c.flac", {"artist": "Chris Liebing", "title": "Higher Things (Ben Klock Remix)"})
    assert not identity_score(want, other, None).version_ok


def test_version_only_in_file_name_counts(tmp_path):
    info = _info(tmp_path, "Fjaak - Spirit (Kai Remix).flac", {"artist": "Fjaak", "title": "Spirit"})
    assert not identity_score(_row("Fjaak", "Spirit"), info, None).version_ok


def test_radio_edit_is_not_the_original(tmp_path):
    info = _info(tmp_path, "x.flac", {"artist": "Blasha & Allatt", "title": "Dust 1 (Radio Edit)"})
    assert not identity_score(_row("Blasha & Allatt", "Dust 1"), info, None).version_ok


def test_no_tags_uses_file_name_and_folder(tmp_path):
    info = _info(tmp_path, "03 - Sigur Ro\u0301s - Gla\u00f0ur.flac")          # NFD accent on disk
    s = identity_score(_row("Sigur R\u00f3s", "Gla\u00f0ur"), info, "Sigur Ros\\03 - Sigur Ro\u0301s - Gla\u00f0ur.flac")
    assert s.evidence == "nombre" and s.artist >= 90 and s.title == 100
    plain = _info(tmp_path, "Mercy.flac")
    s2 = identity_score(_row("Roll Dann", "Mercy"), plain, "Roll Dann\\Mercy.flac")
    assert s2.artist == 100 and s2.title == 100


def test_wrong_song_scores_low(tmp_path):
    info = _info(tmp_path, "x.flac", {"artist": "Duffy", "title": "Mercy"})
    s = identity_score(_row("Duff", "Warwick Avenue"), info, None)
    assert s.title < 70


def test_generic_tags_fall_back_to_name(tmp_path):
    info = _info(tmp_path, "Fjaak - Spirit.flac", {"artist": "Unknown Artist", "title": "Track 01"})
    s = identity_score(_row("Fjaak", "Spirit"), info, "Fjaak\\Fjaak - Spirit.flac")
    assert s.artist == 100 and s.title == 100 and s.evidence == "nombre"


@pytest.mark.parametrize("want,got", [("Dust 1", "Dust 2"), ("Untitled 1", "Untitled 2"), ("A1", "B2"),
                                      ("Part 1", "Part 2"), ("Dust 01", "Dust 2"), ("Spirit", "Spirit 2")])
def test_titles_with_other_numbers_are_another_track(tmp_path, want, got):
    info = _info(tmp_path, "x.flac", {"artist": "Blasha & Allatt", "title": got})
    s = identity_score(_row("Blasha & Allatt", want), info, None)
    assert not s.numbers_ok and s.title <= NUMBER_MISMATCH_MAX < 70


def test_same_numbers_still_match():
    score, same = title_similarity("Dust 1", "Dust 01")
    assert same and score > 90
    assert title_similarity("8AM in Salford", "8AM In Salford") == (100.0, True)
    assert title_similarity("Dust 1", "Dust 2")[1] is False
    assert title_similarity("A1", "A1") == (100.0, True) and title_similarity("A1", "B1")[1] is False
    assert number_tokens("part 2 of 03") == ["2", "3"] and number_tokens("a01 b2") == ["a1", "b2"]
    # a track number glued to the file name ('01 Spirit.flac') is not a title number; '808' stays
    assert title_similarity("Spirit", "01 Spirit") == (100.0, True)
    assert title_similarity("Dust 1", "01 Dust 2")[1] is False
    assert title_similarity("Pacific State", "808 Pacific State")[1] is False


def test_partial_artist_needs_two_words():
    assert artist_similarity(["Planetary Assault Systems"], "Systems") < 60
    assert artist_similarity(["Systems"], "Planetary Assault Systems") < 60
    assert artist_similarity(["Fjaak"], "Fjaak, Chris Liebing") == 100      # one of the split artists
    assert artist_similarity(["808 State"], "808 State") == 100
    assert artist_similarity(["Chris Liebing"], "Chris Liebing Speedy J") == 100   # 2 words: subset counts
    assert artist_similarity(["Fjaak"], "Fjaak - Live 2026") == 100         # an 'Artist - Album' folder
    assert artist_similarity(["Fjaak"], "01 Fjaak") == 100                  # '01 Fjaak - Spirit.mp3'
    assert artist_similarity(["2 Unlimited"], "2 Unlimited") == 100
    assert artist_similarity(["Blasha & Allatt", "Blasha", "Allatt"], "Allatt & Blasha") == 100


def test_partial_artist_in_tags_scores_low(tmp_path):
    info = _info(tmp_path, "x.flac", {"artist": "Systems", "title": "Gated"})
    assert identity_score(_row("Planetary Assault Systems", "Gated"), info, None).artist < 60
    collab = _info(tmp_path, "c.flac", {"artist": "Fjaak, Chris Liebing", "title": "Spirit"})
    assert identity_score(_row("Fjaak", "Spirit"), collab, None).artist == 100


@pytest.mark.parametrize("stem,out", [
    ("01 - Fjaak - Spirit", "Fjaak - Spirit"), ("07. Spirit", "Spirit"), ("12_Fjaak_-_Spirit", "Fjaak - Spirit"),
    ("808 State - Pacific", "808 State - Pacific"), ("2 Unlimited - No Limit", "2 Unlimited - No Limit"),
])
def test_strip_track_number(stem, out):
    assert strip_track_number(stem) == out


def test_parse_name():
    assert parse_name("01 - A - B (X Remix).flac", "Folder") == ("A", "B (X Remix)")
    assert parse_name("Title Only.flac", "Artist Folder") == ("Artist Folder", "Title Only")
