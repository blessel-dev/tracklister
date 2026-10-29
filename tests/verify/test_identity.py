"""Identity scores: tags first, file-name fallback, version rule, track numbers.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import pytest

from tests.fakes.synth import make_track
from tracklister.core.model import TrackRow
from tracklister.verify.audioinfo import probe
from tracklister.core.textnorm import split_title_version
from tracklister.verify.identity import (
    NUMBER_MISMATCH_MAX, SAME_ARTIST_MIN, ArtistMatch, artist_match, artist_similarity, identity_from_names,
    identity_score, number_tokens, parse_name, strip_track_number, title_similarity, title_words_match,
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


def test_z_a_number_after_the_artist_or_in_a_title_tag_belongs_to_the_title():
    """Barrido CL-01: a leading number was taken for a track number also in the title part after ' - ' and in a
    title tag, so 'Surgeon - 9 Lives.flac' (or the tag '2 Rain') was VERIFICADO 100 for «Lives» («Rain»).
    DECISIONES R.2 only exempts a track number glued to the start of the FILE NAME. After the artist, or in a
    title tag, only a zero-padded two-digit token ('01') is a ripper's track number."""
    other = [(_row("Surgeon", "Lives"), "Surgeon - 9 Lives.flac", "Surgeon", None, None),
             (_row("Kerri Chandler", "Rain"), "Kerri Chandler - 24 Rain.flac", None, None, None),
             (_row("Kerri Chandler", "Rain"), "track.flac", None, "Kerri Chandler", "2 Rain")]
    for row, name, parent, tag_artist, tag_title in other:
        s = identity_from_names(row, name, parent, tag_artist, tag_title)
        assert s.numbers_ok is False and s.title <= NUMBER_MISMATCH_MAX, (name, tag_title, s)
    same = [("01 Spirit.flac", "Fjaak", None, None), ("01 Fjaak - Spirit.mp3", None, None, None),
            ("01 - Fjaak - Spirit.flac", None, None, None), ("Fjaak - 01 Spirit.flac", None, None, None),
            ("x.flac", None, "Fjaak", "01 Spirit")]
    for name, parent, tag_artist, tag_title in same:
        s = identity_from_names(_row("Fjaak", "Spirit"), name, parent, tag_artist, tag_title)
        assert (s.artist, s.title) == (100.0, 100.0), (name, tag_title, s)


def test_z_a_track_number_with_a_separator_in_a_title_tag():
    """Barrido audit AU-3-01 (his decision, 29 Oct; changes Z.4): since CL-01 a good file whose title TAG is
    «12 - Spirit», «12. Spirit» or «1 - Spirit» went to _dudosos («Otro título: … no lleva los mismos números…»)
    although its name and its duration fit. A 1-2 digit number followed by « - » or «. » at the start of the title
    tag is a track number again, as at T. Without a separator («2 Rain», «9 Lives») it stays part of the title, and
    the file NAME after the artist does not change («Fjaak - 12 Spirit.flac»)."""
    for tag in ("12 - Spirit", "12. Spirit", "1 - Spirit", "7. Spirit", "12 \u2013 Spirit"):
        s = identity_from_names(_row("Fjaak", "Spirit"), "x.flac", None, "Fjaak", tag)
        assert (s.title, s.numbers_ok) == (100.0, True), (tag, s)
    other = [(_row("Fjaak", "Spirit"), "x.flac", "Fjaak", "12 Spirit"),
             (_row("Kerri Chandler", "Rain"), "x.flac", "Kerri Chandler", "2 Rain"),
             (_row("Surgeon", "Lives"), "x.flac", "Surgeon", "9 Lives"),
             (_row("Fjaak", "Spirit"), "Fjaak - 12 Spirit.flac", None, None)]
    for row, name, tag_artist, tag_title in other:
        s = identity_from_names(row, name, None, tag_artist, tag_title)
        assert s.numbers_ok is False and s.title <= NUMBER_MISMATCH_MAX, (name, tag_title, s)
    s = identity_from_names(_row("Fjaak", "12 Spirit"), "x.flac", None, "Fjaak", "12 - Spirit")
    assert (s.title, s.numbers_ok) == (100.0, True), s


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


# ---- external audit, round 3 (claude-audit-raw-r3-1.txt), B1 ----------------------------------------

# The auditor's namesakes: similar letters, other artists (whole-name similarity 63 / 70 / 88 %).
NAMESAKES = [("Adam Beyer", "Adam Port"), ("Chris Liebing", "Chris Lake"), ("Len Faki", "Ken Faki")]
# Genuine variants of the same artist: case, 'DJ'/'Dj', 'Ø'/'O', the order of a duo, a label as
# co-artist (the row has it stripped), accents, a German transliteration, a typo in a long word.
SAME_ARTIST = [("Chris Liebing", "CHRIS LIEBING"), ("DJ Rush", "Dj Rush"), ("\u00d8 [Phase]", "O [Phase]"),
               ("A & B", "B & A"), ("Blasha & Allatt", "Allatt & Blasha"),
               ("Roll Dann", "Roll Dann & Laster Records"), ("H\u00e9ctor Oaks", "Hector Oaks"),
               ("R\u00f8dh\u00e5d", "Rodhad"), ("Sven V\u00e4th", "Sven Vaeth"), ("Chris Liebing", "Chris Leibing"),
               ("DVS1", "DVS 1")]


@pytest.mark.parametrize("want,got", NAMESAKES)
def test_r3_b1_a_similar_name_is_another_artist(tmp_path, want, got):
    m = artist_match(_row(want, "Rush").artists + [want], got)
    assert not m.same and 60 <= m.score < 90                    # similar letters, but not the same artist
    s = identity_score(_row(want, "Rush"), _info(tmp_path, "x.flac", {"artist": got, "title": "Rush"}), None)
    assert not s.same_artist and s.title == 100 and s.got_artist == got
    # the same rule without tags (file name) and with the artist only in the folder
    by_name = identity_score(_row(want, "Rush"), _info(tmp_path, "y.flac"), f"{got}\\{got} - Rush.flac")
    assert by_name.evidence == "nombre" and not by_name.same_artist
    by_folder = identity_score(_row(want, "Rush"), _info(tmp_path, "z.flac"), f"{got}\\Rush.flac")
    assert not by_folder.same_artist


@pytest.mark.parametrize("want,got", SAME_ARTIST)
def test_r3_b1_genuine_variants_are_the_same_artist(tmp_path, want, got):
    row = _row(want, "Rush")
    m = artist_match(row.artists + [want], got)
    assert m.same and m.score >= SAME_ARTIST_MIN, m
    s = identity_score(row, _info(tmp_path, "x.flac", {"artist": got, "title": "Rush"}), None)
    assert s.same_artist and s.artist >= SAME_ARTIST_MIN


def test_r3_b1_word_rule_details():
    # 'Duff' is not 'Duffy' (the P3 sandbox case): short words must be equal
    assert not artist_match(["Duff"], "Duffy").same
    # a whole-name similarity between 60 and 85 % is never the same artist
    for want, got in NAMESAKES + SAME_ARTIST + [("Ben Klock", "Klock"), ("Amelie Lens", "Amelie Lenz"),
                                                ("Chris Liebing", "Chris Liebingers Band"), ("Fjaak", "Fjak")]:
        m = artist_match([want], got)
        assert not (m.same and m.score < SAME_ARTIST_MIN), (want, got, m)
    # rounds 1-2 still hold: a one-word part of a longer name, numbers, collabs, folders, track numbers
    assert not artist_match(["Planetary Assault Systems"], "Systems").same
    assert not artist_match(["DJ Rush"], "Rush").same
    assert artist_match(["Chris Liebing"], "Chris Liebing Speedy J").same          # 2+ words: subset counts
    assert artist_match(["Fjaak"], "Fjaak, Chris Liebing") == ArtistMatch(100.0, True)
    assert artist_match(["Fjaak"], "Fjaak - Live 2026").same and artist_match(["Fjaak"], "01 Fjaak").same
    assert artist_match(["808 State"], "808 State").same and not artist_match(["808 State"], "909 State").same
    assert artist_similarity(["Adam Beyer"], "Adam Port") == artist_match(["Adam Beyer"], "Adam Port").score


# ---- external audit, round 4 (claude-audit-raw-r4-1.txt), B2 ----------------------------------------
# A word more or less is another track: the auditor's pairs (they scored 71-100 and passed).
OTHER_TITLES = [("Feel It", "Feel It All"), ("Higher", "Higher Love"), ("Feel It All", "Feel It"),
                ("Sin", "Original Sin"), ("Feel It", "Feel Me")]
# The same title written in other ways.
SAME_TITLES = [("Feel It", "FEEL IT"), ("Rock and Roll", "Rock & Roll"), ("Rock & Roll", "Rock and Roll"),
               ("Don't Stop", "Dont Stop"), ("Dont Stop", "Don t Stop"), ("Strobe", "Strobbe"),
               ("Part 2", "Pt. 2"), ("Dust 1", "Dust 01"), ("Feel It", "01 Feel It"), ("Original Sin", "Original Sin")]


@pytest.mark.parametrize("want,got", OTHER_TITLES)
def test_r4_b2_a_word_more_or_less_is_another_track(tmp_path, want, got):
    assert not title_words_match(want, got)
    score, same_numbers = title_similarity(want, got)
    assert score <= NUMBER_MISMATCH_MAX < 70 and same_numbers
    s = identity_score(_row("Amelie Lens", want), _info(tmp_path, "x.flac", {"artist": "Amelie Lens", "title": got}),
                       None)
    assert not s.title_words_ok and s.title <= NUMBER_MISMATCH_MAX and s.numbers_ok
    by_name = identity_score(_row("Amelie Lens", want), _info(tmp_path, "y.flac"), f"Amelie Lens - {got}.flac")
    assert by_name.evidence == "nombre" and not by_name.title_words_ok and by_name.title <= NUMBER_MISMATCH_MAX


@pytest.mark.parametrize("want,got", SAME_TITLES)
def test_r4_b2_the_same_title_written_another_way_still_matches(want, got):
    assert title_words_match(want, got), (want, got)
    assert title_similarity(want, got)[0] > 70


def test_r4_b2_scene_names_and_version_suffixes():
    # the release group glued to a scene-style name is not a word of the title (the P3 sandbox case)
    assert parse_name("plug_trax_-_zoned_out-psy.mp3", None) == ("plug trax", "zoned out")
    assert parse_name("Artist_-_Title_(Kai_Remix)-WEB.flac", None) == ("Artist", "Title (Kai Remix)")
    # a version word glued like that stays (it is not a release group); names with spaces are untouched
    assert parse_name("artist_-_title-remix.mp3", None) == ("artist", "title-remix")
    assert parse_name("artist_-_title-live.mp3", None) == ("artist", "title-live")
    assert parse_name("Artist - Hip-Hop.mp3", None) == ("Artist", "Hip-Hop")
    # suffixes that split_title_version takes away never count as words
    for got in ("Feel It (Original Mix)", "Feel It - Original Mix", "Feel It [LENSKE001]", "Feel It feat. X",
                "Feel It (feat. X)"):
        base, _ = split_title_version(got)
        assert title_words_match("Feel It", base), got
