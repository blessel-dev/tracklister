"""1.0.1 R3 cross-check: the Diagnóstico judges the same file names with the same rules (read-only use of
diagnostics.run.judge_candidate, which judges the first of verify.identity.name_readings).

SPDX-License-Identifier: GPL-3.0-or-later

The paths are the ones of the user's Diagnóstico (10 Oct) with every personal folder invented; the
duration is the one each row expected there (Trip 5:05, Kwartz 6:25 against files of 6:24, Seiko 5:32).
"""
from __future__ import annotations

import pytest

from tracklister.core.model import TrackRow
from tracklister.diagnostics.run import judge_candidate
from tracklister.engine.presets import build_preset

FMT = build_preset("lossless").passes[0]


def _row(artist, title, version=None, dur=None):
    return TrackRow(pos=1, title=title, artists=[a.strip() for a in artist.split("&")], artist_display=artist,
                    version=version, expected_duration_s=dur)


TRIP = _row("Red Rooms", "Trip", dur=305)
KWARTZ = _row("Kwartz", "Show me that light", "Cleric Remix", dur=385)
SEIKO = _row("Phil Berg", "Seiko", dur=332)

ACCEPTED = [
    (TRIP, "@@inventado\\Musica\\Red_Rooms-Blind_Spot-(PHORUM004)-16BIT-WEB-FLAC-2026-PTC\\04-red_rooms-trip.flac", 305),
    (TRIP, "@@inventado\\Novedades Inventadas\\Red Rooms - Trip (Original Mix) 140.flac", 305),
    (TRIP, "@@inventado\\Red Rooms - Album Inventado\\Red Rooms - Trip (Original Mix) [www.dj-promo.org].flac", 305),
    (KWARTZ, "@@inventado\\Kwartz-Show_Me_That_Light_EP-(CRG014)-16BIT-WEB-FLAC-2018-BABAS\\"
             "04-kwartz-show_me_that_light_(cleric_remix)-3fa1c09b.flac", 384),
    (KWARTZ, "@@inventado\\Kwartz-Show Me That Light EP [inc. Cleric Remix]-(Clergy)-16BIT-WEB-FLAC-2018-GRUPO\\"
             "04-Kwartz-Show me that light (Cleric Remix).flac", 384),
    (KWARTZ, "@@inventado\\Coleccion Inventada\\1-04-Kwartz-Show me that light (Cleric Remix).flac", 384),
    (KWARTZ, "@@inventado\\7 - Carpeta Inventada\\Kwartz - Show Me That Light (Cleric Remix) [.wav", 384),
    (SEIKO, "@@inventado\\Phil_Berg-Darin-MR047D-24BIT-WEB-FLAC-2026-WAVED\\06-phil_berg-seiko.flac", 332),
    (SEIKO, "@@inventado\\Lista Ejemplo\\Phil Berg - D\u0101rin - 06 - Seiko.flac", 332),
]

REJECTED = [
    (_row("Truncate", "Dust 1", dur=300), "@@inventado\\Lista\\04-truncate-dust_2.flac", 300),
    (_row("Confusion & Tino Machauer", "Interchange III", dur=405),
     "@@inventado\\Lista\\Confusion & Tino Machauer - Interchange II.flac", 405),
    (_row("Amelie Lens", "Feel It", dur=300), "@@inventado\\Lista\\1-01-Amelie Lens-Feel It All.flac", 300),
    (_row("Adam Beyer", "Rush", dur=300), "@@inventado\\Lista\\01-adam_port-rush.flac", 300),
    (_row("Len Faki", "Rush", dur=300), "@@inventado\\Lista\\Ken Faki - Rush.flac", 300),
    (_row("Planetary Assault Systems", "Gated", dur=300), "@@inventado\\Lista\\01-systems-gated.flac", 300),
    (KWARTZ, "@@inventado\\Lista\\04-kwartz-show_me_that_light-3fa1c09b.flac", 384),
    (KWARTZ, "@@inventado\\Lista\\Kwartz - Show me that light (Other Remix).flac", 384),
    (TRIP, "@@inventado\\Lista\\Red Rooms - Trip 140.flac", 305),
]


@pytest.mark.parametrize("row,path,dur", ACCEPTED, ids=[p.split("\\")[-1][:40] for _, p, _ in ACCEPTED])
def test_r3_the_diagnostico_accepts_the_real_names(row, path, dur):
    score, ok, why = judge_candidate(row, FMT, path, dur, None)
    assert ok and score >= 95 and why.startswith("aceptable"), (score, why)


@pytest.mark.parametrize("row,path,dur", REJECTED, ids=[p.split("\\")[-1][:40] for _, p, _ in REJECTED])
def test_r3_the_diagnostico_still_rejects(row, path, dur):
    score, ok, why = judge_candidate(row, FMT, path, dur, None)
    assert not ok and score < 50 and why.startswith("rechazado"), (score, why)


# audit v101-1 review, B1-R: no dash between artist and title, so the glued hyphen is the title's own
ADAM_TIME = _row("Adam Beyer", "Time", dur=300)
B1R = [
    (ADAM_TIME, "@@inventado\\Lista\\Adam Beyer Space-Time.flac"),
    (ADAM_TIME, "@@inventado\\Lista\\01 Adam Beyer Space-Time.flac"),
    (ADAM_TIME, "@@inventado\\Lista\\01 - Adam Beyer Space-Time.flac"),
    (ADAM_TIME, "@@inventado\\Lista\\Adam Beyer -Space-Time.flac"),
    (ADAM_TIME, "@@inventado\\Lista\\Adam Beyer\u2013Space-Time.flac"),
    (ADAM_TIME, "@@inventado\\Lista\\adam_beyer_space-time.flac"),
    (ADAM_TIME, "@@inventado\\Lista\\Adam Beyer Space-Time (Original Mix).flac"),
    (_row("Planetary Assault Systems", "Stop", dur=300), "@@inventado\\Lista\\Planetary Assault Systems Non-Stop.flac"),
    (_row("Red Rooms", "Trip", dur=300), "@@inventado\\Lista\\Red Rooms Bad-Trip.flac"),
    (_row("Chris Liebing", "Matter", dur=300), "@@inventado\\Lista\\Chris Liebing Anti-Matter.flac"),
    (_row("Fjaak", "Spirit", dur=300), "@@inventado\\Lista\\Fjaak & Kai Holy-Spirit.flac"),
]


@pytest.mark.parametrize("row,path", B1R, ids=[p.split("\\")[-1][:40] for _, p in B1R])
def test_v101_1r_b1r_the_diagnostico_rejects_a_title_word_glued_to_the_artist(row, path):
    """Same rule as the download: the artist part of the first cut ('Adam Beyer Space') is not the row's."""
    score, ok, why = judge_candidate(row, FMT, path, 300, None)
    assert not ok and score < 50 and why.startswith("rechazado"), (score, why)


@pytest.mark.parametrize("row,path", [
    (_row("Fjaak", "Spirit", dur=300), "@@inventado\\Lista\\Fjaak & Kai-Spirit.flac"),
    (_row("Fjaak", "Spirit", dur=300), "@@inventado\\Lista\\04-fjaak_feat_kai-spirit.flac"),
    (_row("Chris Liebing", "Matter", dur=300), "@@inventado\\Lista\\Chris Leibing-Matter.flac"),
    (_row("Komplex aka Jeroen Search", "Inject", dur=300), "@@inventado\\Lista\\Jeroen Search-Inject.flac"),
    (_row("Kwartz", "Show me that light", "Cleric Remix", dur=300),
     "@@inventado\\Lista\\01 Kwartz-Show me that light (Cleric Remix).flac"),
    (ADAM_TIME, "@@inventado\\Adam Beyer Space Date EP\\Time.flac"),
])
def test_v101_1r_b1r_the_diagnostico_still_accepts_exact_artists_and_credits(row, path):
    score, ok, why = judge_candidate(row, FMT, path, 300, None)
    assert ok and score >= 95 and why.startswith("aceptable"), (score, why)
