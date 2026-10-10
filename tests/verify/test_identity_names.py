"""1.0.1 R3: identity from the file names Soulseek users really write (the user's Diagnóstico, 10 Oct).

SPDX-License-Identifier: GPL-3.0-or-later

Every name below is a real file name from the user's Diagnóstico and set report. Each PERSONAL folder
name of a peer was replaced by an invented one with the same pattern; scene release folders and
catalogue numbers are public release names and stay (their group or hash suffix is invented). No peer
name appears. The must-reject set pins the v1.0 audit rules on the same name patterns.
"""
from __future__ import annotations

import pytest

from tests.fakes.synth import make_track
from tracklister.core.model import ResultState, TrackRow
from tracklister.core.textnorm import split_title_version
from tracklister.engine.presets import build_preset
from tracklister.verify.audioinfo import probe
from tracklister.verify.identity import (
    artist_match, clean_title, identity_from_names, identity_score, name_readings, parse_folder, parse_name,
    strip_trailing_metadata, strip_watermarks,
)
from tracklister.verify.verifier import verify_file

LOSSLESS = build_preset("lossless").accept


def _row(artist, title, version=None, dur=None, artists=None):
    return TrackRow(pos=1, title=title, artists=artists or [a.strip() for a in artist.split("&")],
                    artist_display=artist, version=version, expected_duration_s=dur)


TRIP = _row("Red Rooms", "Trip")
KWARTZ = _row("Kwartz", "Show me that light", "Cleric Remix")
SEIKO = _row("Phil Berg", "Seiko")

# (row, Soulseek path tail 'folder\name', the reading parse_name must give first)
REAL_NAMES = [
    # the 7 rejections of the Diagnóstico table (06 R3)
    (TRIP, "Red_Rooms-Blind_Spot-(PHORUM004)-16BIT-WEB-FLAC-2026-PTC\\04-red_rooms-trip.flac", ("red rooms", "trip")),
    (KWARTZ, "Kwartz-Show_Me_That_Light_EP-(CRG014)-16BIT-WEB-FLAC-2018-BABAS\\"
             "04-kwartz-show_me_that_light_(cleric_remix)-3fa1c09b.flac",
     ("kwartz", "show me that light (cleric remix)")),
    (SEIKO, "Phil_Berg-Darin-MR047D-24BIT-WEB-FLAC-2026-WAVED\\06-phil_berg-seiko.flac", ("phil berg", "seiko")),
    (KWARTZ, "Coleccion Inventada\\1-04-Kwartz-Show me that light (Cleric Remix).flac",
     ("Kwartz", "Show me that light (Cleric Remix)")),
    (TRIP, "Novedades Inventadas\\Red Rooms - Trip (Original Mix) 140.flac", ("Red Rooms", "Trip (Original Mix)")),
    (SEIKO, "Lista Ejemplo\\Phil Berg - D\u0101rin - 06 - Seiko.flac", ("Phil Berg", "Seiko")),
    (KWARTZ, "7 - Carpeta Inventada\\Kwartz - Show Me That Light (Cleric Remix) [.wav",
     ("Kwartz", "Show Me That Light (Cleric Remix)")),
    # the same Diagnóstico: the other scene folder, and the names v1.0 already accepted (they must stay)
    (KWARTZ, "Kwartz-Show Me That Light EP [inc. Cleric Remix]-(Clergy)-16BIT-WEB-FLAC-2018-GRUPO\\"
             "04-Kwartz-Show me that light (Cleric Remix).flac", ("Kwartz", "Show me that light (Cleric Remix)")),
    (TRIP, "Red Rooms - Album Inventado [Sello Inventado]\\Red Rooms - Trip (Original Mix) [www.dj-promo.org].flac",
     ("Red Rooms", "Trip (Original Mix)")),
    (TRIP, "Red Rooms - Album Inventado\\04 - Red Rooms - Trip.flac", ("Red Rooms", "Trip")),
    (KWARTZ, "Carpeta Ficticia\\Kwartz - Show me that light (Cleric Remix).wav",
     ("Kwartz", "Show me that light (Cleric Remix)")),
    (KWARTZ, "Kwartz - Album Inventado - (2018) [WEB-FLAC]\\4 Show me that light (Cleric Remix).flac",
     ("Kwartz - Album Inventado - (2018) [WEB-FLAC]", "4 Show me that light (Cleric Remix)")),
    (SEIKO, "Otra Lista\\Phil Berg - Seiko.aif", ("Phil Berg", "Seiko")),
]


@pytest.fixture(scope="module")
def untagged(tmp_path_factory):
    return probe(make_track(tmp_path_factory.mktemp("id") / "x.flac", fmt="flac", seconds=2))


@pytest.mark.parametrize("row,tail,first", REAL_NAMES, ids=[t.split("\\")[-1][:40] for _, t, _ in REAL_NAMES])
def test_r3_real_names_are_read_and_accepted(untagged, row, tail, first):
    folder, name = tail.rsplit("\\", 1)
    assert parse_name(name, folder) == first
    s = identity_score(row, untagged, tail)
    assert s.same_artist and s.artist >= 85 and s.title >= 95 and s.version_ok, s
    assert s.numbers_ok and s.title_words_ok and s.evidence == "nombre"


@pytest.mark.parametrize("row,tail", [(r, t) for r, t, _ in REAL_NAMES[:7]],
                         ids=[t.split("\\")[-1][:40] for _, t, _ in REAL_NAMES[:7]])
def test_r3_real_names_are_verified_end_to_end(tmp_path, row, tail):
    """The whole verification (no tags, as on the Diagnóstico): VERIFICADO, never _dudosos."""
    p = make_track(tmp_path / "descarga.flac", fmt="flac", seconds=20)
    timed = TrackRow(pos=1, title=row.title, artists=row.artists, artist_display=row.artist_display,
                     version=row.version, expected_duration_s=20)
    v = verify_file(timed, p, LOSSLESS, lossy_allowed=False, source_path_tail=tail)
    assert v.state == ResultState.VERIFICADO and v.score >= 95 and "sin_tags" in v.flags, v.reasons_es


def test_r3_watermarks_are_stripped_never_a_real_word():
    assert strip_watermarks("Talitha (Original Mix) electronicfresh.com") == "Talitha (Original Mix)"
    assert strip_watermarks("Trip (Original Mix) [www.dj-promo.org]") == "Trip (Original Mix)"
    assert strip_watermarks("Trip (www.dj-promo.org)") == "Trip"
    assert strip_watermarks("www.example-site.net - Red Rooms - Trip") == "Red Rooms - Trip"
    assert strip_watermarks("Red Rooms - Trip - https://example.org/x?y=1") == "Red Rooms - Trip"
    assert strip_watermarks("Red Rooms - Trip [promo-musica.ru]") == "Red Rooms - Trip"
    assert strip_watermarks("Seiko (descargas-ejemplo.info)") == "Seiko"
    for real in ("St. Germain - Rose Rouge", "Vkn.modular - Hidden Reason", "D.A.V.E. The Drummer - Hydraulix",
                 "Mr.Me - Title", "Dr. Who - Theme", "Title (feat.me)", "Vol.de 1", "Remix.Com - Track",
                 "Red Rooms - Trip (Original Mix)", "13130 Space Project - Talitha", "Lx2", "1982"):
        assert strip_watermarks(real) == real, real
    assert clean_title("Talitha (Original Mix) electronicfresh.com") == "Talitha (Original Mix)"


def test_r3_a_watermark_in_the_tags_is_no_identity_doubt(tmp_path):
    """Row 21 of his report: 'Otro título: 'Talitha (Original Mix) electronicfresh.com' no tiene las mismas
    palabras que 'Talitha''. The watermark is gone before comparing: VERIFICADO."""
    p = make_track(tmp_path / "t.flac", fmt="flac", seconds=20,
                   tags={"artist": "13130 Space Project", "title": "Talitha (Original Mix) electronicfresh.com"})
    row = _row("13130 Space Project", "Talitha", dur=20)
    v = verify_file(row, p, LOSSLESS, lossy_allowed=False, source_path_tail=None)
    assert v.state == ResultState.VERIFICADO and v.score == 100, v.reasons_es
    tagged_artist = make_track(tmp_path / "a.flac", fmt="flac", seconds=20,
                               tags={"artist": "13130 Space Project [www.ejemplo-promo.com]", "title": "Talitha"})
    assert verify_file(row, tagged_artist, LOSSLESS, lossy_allowed=False,
                       source_path_tail=None).state == ResultState.VERIFICADO
    by_name = identity_score(row, probe(make_track(tmp_path / "n.flac", fmt="flac", seconds=2)),
                             "Carpeta Inventada\\13130 Space Project - Talitha (Original Mix) electronicfresh.com.mp3")
    assert by_name.same_artist and by_name.title == 100 and by_name.version_ok


def test_r3_trailing_numbers_only_after_a_version_or_marked():
    assert strip_trailing_metadata("Trip (Original Mix) 140") == "Trip (Original Mix)"
    assert strip_trailing_metadata("Trip (Original Mix) 140 8A") == "Trip (Original Mix)"
    assert strip_trailing_metadata("Trip (Extended Mix) 128.5") == "Trip (Extended Mix)"
    assert strip_trailing_metadata("Seiko 128 BPM") == "Seiko" and strip_trailing_metadata("Seiko - 128bpm") == "Seiko"
    assert strip_trailing_metadata("Seiko key: Am") == "Seiko" and strip_trailing_metadata("Seiko key 8A") == "Seiko"
    # a number attached to the title words stays part of the title
    for keep in ("Dust 2", "Trip 140", "Lx2", "1982", "Trip [Phorum Records] 140", "Trip (Part 2) 140",
                 "Interchange III", "Track (Original Mix) 2", "The Key", "Seiko (Original Mix) 303"):
        assert strip_trailing_metadata(keep) == keep, keep


def test_r3_parse_folder():
    assert parse_folder("Red_Rooms-Blind_Spot-(PHORUM004)-16BIT-WEB-FLAC-2026-PTC") == "Red Rooms"
    assert parse_folder("Phil_Berg-Darin-MR047D-24BIT-WEB-FLAC-2026-WAVED") == "Phil Berg"
    assert parse_folder("Kwartz-Show Me That Light EP [inc. Cleric Remix]-(Clergy)-16BIT-WEB-FLAC-2018-GRUPO") == "Kwartz"
    # other folders keep their name (artist_match tries each ' - ' part): never cut 'A-ha' or 'Hip-Hop Classics'
    for f in ("A-ha", "Hip-Hop Classics", "Red Rooms - Album Inventado", "Roll Dann", "2 Unlimited"):
        assert parse_folder(f) == f
    assert parse_folder("Roll Dann [www.ejemplo-promo.com]") == "Roll Dann"
    assert parse_folder(None) is None and parse_folder("") is None


def test_r3_readings_never_split_inside_brackets_and_keep_v1_names():
    """r4-3 N3: 'Spirit (Kai Remix - Radio Edit)' is one title; the v1.0 parse_name cases still hold."""
    assert parse_name("Spirit (Kai Remix - Radio Edit).flac", "Fjaak") == ("Fjaak", "Spirit (Kai Remix - Radio Edit)")
    assert parse_name("01 - A - B (X Remix).flac", "Folder") == ("A", "B (X Remix)")
    assert parse_name("Title Only.flac", "Artist Folder") == ("Artist Folder", "Title Only")
    assert parse_name("plug_trax_-_zoned_out-psy.mp3", None) == ("plug trax", "zoned out")
    assert parse_name("Artist - Hip-Hop.mp3", None) == ("Artist", "Hip-Hop")
    # a compound word is not an artist-title split first ('Hip-Hop' alone), but the reading exists
    assert parse_name("Hip-Hop.mp3", "Artist") == ("Artist", "Hip-Hop")
    assert ("Hip", "Hop") in {(r.artist, r.title) for r in name_readings("Hip-Hop.mp3", "Artist")}
    # a disc-track prefix that is in fact the artist's name: the name as written is a reading too
    assert ("2-4 Grooves", "Writing On The Wall") in {
        (r.artist, r.title) for r in name_readings("2-4 Grooves - Writing On The Wall.flac", None)}
    # the scene folder's own release group glued to the name goes; another word never does
    folder = "Red_Rooms-Blind_Spot-(PHORUM004)-16BIT-WEB-FLAC-2026-PTC"
    assert parse_name("04-red_rooms-trip-ptc.flac", folder) == ("red rooms", "trip")
    assert parse_name("04-red_rooms-trip-xyz.flac", folder) == ("red rooms", "trip-xyz")
    # a hash needs letters and digits; a word of hex letters ('facade') or a year stays
    assert parse_name("04-red_rooms-trip-facade.flac", None) == ("red rooms", "trip-facade")
    assert parse_name("04-red_rooms-trip-20260101.flac", None) == ("red rooms", "trip-20260101")
    readings = {(r.artist, r.title) for r in name_readings("01-808_state-pacific_state.flac", None)}
    assert ("808 state", "pacific state") in readings


# ---- the must-reject set: every v1.0 rule on the new name patterns ----------------------------------------
REJECT = [
    # 'Dust 1' / 'Dust 2', 'Interchange II' / 'Interchange III': other numbers or words in the title
    (_row("Truncate", "Dust 1"), "Carpeta Inventada\\Truncate - Dust 2.flac"),
    (_row("Truncate", "Dust 1"), "Truncate-Dust-(CAT001)-WEB-FLAC-2026-GRUPO\\04-truncate-dust_2.flac"),
    (_row("Truncate", "Dust 1"), "Coleccion Inventada\\1-04-Truncate-Dust 2.flac"),
    (_row("Confusion & Tino Machauer", "Interchange III"), "Lista Ejemplo\\Confusion & Tino Machauer - Interchange II.flac"),
    (_row("Confusion & Tino Machauer", "Interchange III"),
     "Confusion-Interchange-(CAT002)-WEB-FLAC-2026-GRUPO\\03-confusion_and_tino_machauer-interchange_ii.flac"),
    # 'Feel It' / 'Feel It All' / 'Original Sin'
    (_row("Amelie Lens", "Feel It"), "Lista Ejemplo\\Amelie Lens - Feel It All.flac"),
    (_row("Amelie Lens", "Feel It"), "Lens-Feel-(CAT003)-WEB-FLAC-2026-GRUPO\\01-amelie_lens-feel_it_all.flac"),
    (_row("Amelie Lens", "Feel It"), "Coleccion Inventada\\1-01-Amelie Lens-Feel It All.flac"),
    (_row("Amelie Lens", "Sin"), "Lista Ejemplo\\Amelie Lens - Original Sin.flac"),
    # a number attached to the title words is no BPM
    (TRIP, "Novedades Inventadas\\Red Rooms - Trip 140.flac"),
    # namesakes, also with the right artist only in the folder (D10: the name has an artist part)
    (_row("Adam Beyer", "Rush"), "Lista Ejemplo\\Adam Port - Rush.flac"),
    (_row("Adam Beyer", "Rush"), "Adam Beyer\\Adam Port - Rush.flac"),
    (_row("Adam Beyer", "Rush"), "Port-Rush-(CAT004)-WEB-FLAC-2026-GRUPO\\01-adam_port-rush.flac"),
    (_row("Adam Beyer", "Rush"), "Adam Beyer\\1-01-Adam Port-Rush.flac"),
    (_row("Len Faki", "Rush"), "Lista Ejemplo\\Ken Faki - Rush.flac"),
    (_row("Len Faki", "Rush"), "Len Faki\\01-ken_faki-rush.flac"),
    # partial artists
    (_row("Planetary Assault Systems", "Gated"), "Lista Ejemplo\\Systems - Gated.flac"),
    (_row("Planetary Assault Systems", "Gated"), "Lista Ejemplo\\01-systems-gated.flac"),
    # remix kind and remixer
    (KWARTZ, "Lista Ejemplo\\Kwartz - Show me that light (Other Remix).flac"),
    (KWARTZ, "Lista Ejemplo\\Kwartz - Show me that light (Cleric Dub).flac"),
    (KWARTZ, "Kwartz-Show_Me_That_Light_EP-(CRG014)-16BIT-WEB-FLAC-2018-BABAS\\04-kwartz-show_me_that_light-3fa1c09b.flac"),
    (KWARTZ, "Coleccion Inventada\\1-04-Kwartz-Show me that light.flac"),
    (TRIP, "Red_Rooms-Blind_Spot-(PHORUM004)-16BIT-WEB-FLAC-2026-PTC\\04-red_rooms-trip_(cleric_remix).flac"),
    (TRIP, "Novedades Inventadas\\Red Rooms - Trip (Cleric Remix) 140.flac"),
    (_row("Fjaak", "Spirit", "Kai Remix"), "Lista Ejemplo\\Fjaak - Spirit (Kai Remix Edit).flac"),
    (_row("Fjaak", "Spirit", "Kai Remix - Radio Edit"), "Lista Ejemplo\\Fjaak - Spirit (Radio Edit).flac"),
]


@pytest.mark.parametrize("row,tail", REJECT, ids=[t.split("\\")[-1][:40] for _, t in REJECT])
def test_r3_the_must_reject_set_still_rejects(untagged, row, tail):
    s = identity_score(row, untagged, tail)
    same_song = s.same_artist and s.artist >= 60 and s.title >= 70
    assert not (same_song and s.version_ok), s


def test_r3_must_reject_end_to_end_goes_to_a_doubt(tmp_path):
    p = make_track(tmp_path / "d.flac", fmt="flac", seconds=20)
    for row, tail in REJECT[:4] + REJECT[10:12] + REJECT[18:20]:
        timed = TrackRow(pos=1, title=row.title, artists=row.artists, artist_display=row.artist_display,
                         version=row.version, expected_duration_s=20)
        v = verify_file(timed, p, LOSSLESS, lossy_allowed=False, source_path_tail=tail)
        assert v.state == ResultState.DUDOSO and v.score < 50, (tail, v.reasons_es)


def test_r3_the_folder_counts_only_without_an_artist_part(untagged):
    """D10 (folds the T.4 note): a folder named like the artist no longer rescues a file whose name or
    tag says another artist; a title-only name in the artist's folder still verifies."""
    row = _row("Adam Beyer", "Rush")
    assert not identity_score(row, untagged, "Adam Beyer\\Adam Port - Rush.flac").same_artist
    assert identity_score(row, untagged, "Adam Beyer\\Rush.flac").same_artist
    assert identity_score(row, untagged, "Adam Beyer - Album Inventado\\03 Rush.flac").same_artist
    # the same judgement without an audio file (a search result: name and folder only)
    assert not identity_from_names(row, "Adam Port - Rush.flac", "Adam Beyer").same_artist
    assert identity_from_names(row, "Rush.flac", "Adam Beyer") == identity_score(row, untagged, "Adam Beyer\\Rush.flac")


def test_r3_tag_artist_wins_over_the_folder(tmp_path):
    info = probe(make_track(tmp_path / "t.flac", fmt="flac", seconds=2, tags={"artist": "Adam Port"}))
    s = identity_score(_row("Adam Beyer", "Rush"), info, "Adam Beyer\\Rush.flac")
    assert not s.same_artist and s.got_artist == "Adam Port"


# ---- R4, verify side: aliases and spellings (needs core.aliases, C-0) ---------------------------------------
@pytest.mark.parametrize("row,tail", [
    (_row("Komplex aka Jeroen Search", "Inject"), "Lista Ejemplo\\Jeroen Search - Inject.flac"),
    (_row("Komplex aka Jeroen Search", "Inject"), "Lista Ejemplo\\Komplex - Inject.flac"),
    (_row("Komplex aka Jeroen Search", "Inject"), "Lista Ejemplo\\Komplex aka Jeroen Search - Inject.flac"),
    (_row("Komplex a.k.a. Jeroen Search", "Inject"), "Lista Ejemplo\\01-jeroen_search-inject.flac"),
    (_row("TR440", "Somewhen"), "Lista Ejemplo\\TR-440 - Somewhen.flac"),
    (_row("TR440", "Somewhen"), "Lista Ejemplo\\TR 440 - Somewhen.flac"),
    (_row("TR440", "Somewhen"), "Lista Ejemplo\\01-tr-440-somewhen.flac"),
    (_row("TR-440", "Somewhen"), "Lista Ejemplo\\TR440 - Somewhen.flac"),
    (_row("Vkn.modular", "Hidden Reason"), "Lista Ejemplo\\Vkn Modular - Hidden Reason.flac"),
    (_row("Vkn.modular", "Hidden Reason"), "Lista Ejemplo\\VKN.modular - Hidden Reason.flac"),
])
def test_r4_aliases_and_spellings_are_the_same_artist(untagged, row, tail):
    s = identity_score(row, untagged, tail)
    assert s.same_artist and s.artist >= 85 and s.title == 100, s


def test_r4_aliases_never_open_a_namesake():
    assert not artist_match(["Adam Beyer"], "Adam Port").same
    assert not artist_match(["Komplex aka Jeroen Search"], "Jeroen Searching").same
    assert not artist_match(["Komplex aka Jeroen Search"], "Jeroen").same          # one word of a 2-word name
    assert not artist_match(["TR440"], "TR 404").same
    assert artist_match(["Komplex"], "Komplex aka Jeroen Search").same          # an alias in the file's name


# ---- audit v101-1: a later reading never moves title words into the artist (B1), and a title tag never
# makes the folder the artist of a name that says its own artist (B2) ------------------------------------
B1_OTHER_TRACK = [
    # (row, Soulseek path tail: another track whose title ENDS with the row's title, the row of that file)
    (_row("Planetary Assault Systems", "Stop"), "Techno Inventado\\Planetary Assault Systems-Non-Stop.flac",
     _row("Planetary Assault Systems", "Non-Stop")),
    (_row("Planetary Assault Systems", "Stop"), "Techno Inventado\\03-planetary_assault_systems-non-stop.flac",
     _row("Planetary Assault Systems", "Non-Stop")),
    (TRIP, "Lista Ejemplo\\04-red_rooms-bad-trip-3fa1c09b.flac", _row("Red Rooms", "Bad-Trip")),
    (_row("Chris Liebing", "Matter"), "Lista Ejemplo\\01-chris_liebing-anti-matter-3fa1c09b.flac",
     _row("Chris Liebing", "Anti-Matter")),
    (_row("Adam Beyer", "Time"), "Lista Ejemplo\\Adam Beyer-Space-Time.flac", _row("Adam Beyer", "Space-Time")),
    (_row("Adam Beyer", "Rush"), "Lista Ejemplo\\Adam Beyer-Pilot-Rush.flac", _row("Adam Beyer", "Pilot-Rush")),
]


@pytest.mark.parametrize("row,tail,right", B1_OTHER_TRACK, ids=[t.split("\\")[-1][:40] for _, t, _ in B1_OTHER_TRACK])
def test_v101_1_b1_a_later_reading_never_moves_title_words_into_the_artist(tmp_path, untagged, row, tail, right):
    """'Planetary Assault Systems-Non-Stop.flac' was also read as 'Planetary Assault Systems-Non' + 'Stop';
    the extra word passed the partial-artist rule, so «Non-Stop» was VERIFICADO 100 for the row «Stop».
    Now that reading only counts with an artist part that is exactly a row name: a doubt, «Otro título»."""
    s = identity_score(row, untagged, tail)
    assert not (s.same_artist and s.artist >= 60 and s.title >= 70 and s.version_ok), s
    assert not s.title_words_ok and s.same_artist, s          # the name's own reading: same artist, other title
    p = make_track(tmp_path / "d.flac", fmt="flac", seconds=20)
    timed = TrackRow(pos=1, title=row.title, artists=row.artists, artist_display=row.artist_display,
                     expected_duration_s=20)
    v = verify_file(timed, p, LOSSLESS, lossy_allowed=False, source_path_tail=tail)
    assert v.state == ResultState.DUDOSO and v.score < 50, v.reasons_es
    assert any(r.startswith("Otro título") for r in v.reasons_es), v.reasons_es
    # an artist tag alone does not open it either (the title still comes from that reading of the name)
    tagged = make_track(tmp_path / "a.flac", fmt="flac", seconds=20, tags={"artist": row.artist_display})
    assert verify_file(timed, tagged, LOSSLESS, lossy_allowed=False,
                       source_path_tail=tail).state == ResultState.DUDOSO
    # the row of that file still verifies
    good = TrackRow(pos=1, title=right.title, artists=right.artists, artist_display=right.artist_display,
                    expected_duration_s=20)
    assert verify_file(good, p, LOSSLESS, lossy_allowed=False, source_path_tail=tail).state == ResultState.VERIFICADO


@pytest.mark.parametrize("row,tail", [
    (_row("X-Ray Spex", "Oh Bondage"), "Lista Ejemplo\\x-ray_spex-oh_bondage.flac"),   # the 2nd split is the artist's
    (_row("808 State", "Pacific State"), "Lista Ejemplo\\01-808_state-pacific_state.flac"),
    (_row("808 State", "Pacific State"), "Lista Ejemplo\\808-state-pacific_state.flac"),
    (_row("A-ha", "Take On Me"), "Lista Ejemplo\\A-ha-Take On Me.flac"),
    (_row("Jay-Z", "Song Inventada"), "Lista Ejemplo\\Jay-Z-Song Inventada.flac"),
    (_row("Fjaak", "Spirit"), "Fjaak\\Fjaak-Spirit.flac"),
    (_row("2-4 Grooves", "Writing On The Wall"), "Lista Ejemplo\\2-4 Grooves - Writing On The Wall.flac"),
    (_row("TR440", "Somewhen"), "Lista Ejemplo\\01-tr-440-somewhen.flac"),
    (_row("Komplex aka Jeroen Search", "Inject"), "Lista Ejemplo\\01-jeroen_search-inject.flac"),
])
def test_v101_1_b1_a_later_reading_with_the_rows_exact_artist_still_counts(untagged, row, tail):
    s = identity_score(row, untagged, tail)
    assert s.same_artist and s.artist >= 85 and s.title == 100 and s.version_ok and s.title_words_ok, s


B2_FOLDER_IS_NOT_THE_ARTIST = [
    (_row("Adam Beyer", "Rush"), "Adam Beyer\\Adam Port - Rush.flac", "Rush"),
    (_row("Chris Lake", "Rush"), "Chris Lake\\Chris Liebing - Rush.flac", "Rush"),
    (TRIP, "Red_Rooms-Blind_Spot-(PHORUM004)-16BIT-WEB-FLAC-2026-PTC\\04-otro_artista-trip.flac", "Trip"),
    (_row("Adam Beyer", "Rush"), "Adam Beyer\\01-adam_port-rush.flac", "Rush"),
]


@pytest.mark.parametrize("row,tail,title_tag", B2_FOLDER_IS_NOT_THE_ARTIST,
                         ids=[t.split("\\")[-1][:40] for _, t, _ in B2_FOLDER_IS_NOT_THE_ARTIST])
def test_v101_1_b2_a_title_tag_never_makes_the_folder_the_artist(tmp_path, row, tail, title_tag):
    """'Adam Beyer\\Adam Port - Rush.flac' with only a title tag 'Rush' was VERIFICADO 100 for «Adam Beyer -
    Rush»: the folder reading took the title tag. The name says its own artist (D10): «Otro artista»."""
    p = make_track(tmp_path / "t.flac", fmt="flac", seconds=20, tags={"title": title_tag})
    s = identity_score(row, probe(p), tail)
    assert not s.same_artist, s
    timed = TrackRow(pos=1, title=row.title, artists=row.artists, artist_display=row.artist_display,
                     expected_duration_s=20)
    v = verify_file(timed, p, LOSSLESS, lossy_allowed=False, source_path_tail=tail)
    assert v.state == ResultState.DUDOSO and v.score < 50, v.reasons_es
    assert any(r.startswith("Otro artista") for r in v.reasons_es), v.reasons_es


@pytest.mark.parametrize("tail,title_tag", [
    ("Fjaak\\Spirit.flac", "Spirit"),                         # a title-only name in the artist's folder
    ("Fjaak\\03 Spirit.flac", "Spirit"),
    ("Fjaak\\pista03.flac", "Spirit"),                         # a name that is no title: the folder and the tag
    ("Fjaak\\Spirit - Original Mix.flac", "Spirit (Original Mix)"),   # the name's 'artist part' is the title
    ("Fjaak - Album Inventado\\03 Spirit.flac", "Spirit"),
])
def test_v101_1_b2_the_folder_still_counts_when_the_name_says_no_artist(tmp_path, tail, title_tag):
    p = make_track(tmp_path / "t.flac", fmt="flac", seconds=20, tags={"title": title_tag})
    row = TrackRow(pos=1, title="Spirit", artists=["Fjaak"], artist_display="Fjaak", expected_duration_s=20)
    v = verify_file(row, p, LOSSLESS, lossy_allowed=False, source_path_tail=tail)
    assert v.state == ResultState.VERIFICADO, (tail, v.reasons_es)


def test_r3_version_in_the_title_of_every_reading_counts_for_an_original_row(untagged):
    row = _row("Red Rooms", "Trip")
    s = identity_score(row, untagged, "Lista Ejemplo\\1-04-Red Rooms-Trip (Cleric Remix).flac")
    assert not s.version_ok and "original" in s.version_reason_es
    base, version = split_title_version(parse_name("1-04-Red Rooms-Trip (Cleric Remix).flac", "x")[1])
    assert (base, version) == ("Trip", "Cleric Remix")
