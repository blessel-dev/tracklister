"""verify_file(): the fixed verdict rules on synthetic files.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import pytest

from tests.fakes.synth import make_track
from tracklister.core.model import DoubtKind, ResultState, TrackRow
from tracklister.engine.presets import build_preset
from tracklister.verify.verifier import ACCEPT_SCORE, REVIEW_SCORE, verify_file

LOSSLESS = build_preset("lossless").accept
MP3 = build_preset("solo_mp3_320").accept


def _row(artist="Fjaak", title="Spirit", version=None, dur=20):
    return TrackRow(pos=1, title=title, artists=[a.strip() for a in artist.split("&")], artist_display=artist,
                    version=version, expected_duration_s=dur)


def _v(tmp_path, name, row=None, accept=LOSSLESS, lossy=False, tail=None, **kw):
    kw.setdefault("fmt", "flac")
    kw.setdefault("seconds", 20)
    p = make_track(tmp_path / name, **kw)
    return verify_file(row or _row(), p, accept, lossy_allowed=lossy, source_path_tail=tail)


TAGS = {"artist": "Fjaak", "title": "Spirit"}


def test_correct_file_verified(tmp_path):
    v = _v(tmp_path, "Fjaak - Spirit.flac", tags=TAGS)
    assert v.state == ResultState.VERIFICADO and v.doubt is None and v.score == 100


def test_original_vs_remix_goes_to_version_doubt(tmp_path):
    v = _v(tmp_path, "x.flac", tags={"artist": "Fjaak", "title": "Spirit (Kai Van Dongen Remix)"})
    assert v.state == ResultState.DUDOSO and v.doubt == DoubtKind.VERSION
    assert any("Otra versión" in r for r in v.reasons_es)


def test_radio_edit_too_short(tmp_path):
    v = _v(tmp_path, "r.flac", row=_row("Blasha & Allatt", "Dust 1", dur=40), seconds=18,
           tags={"artist": "Blasha & Allatt", "title": "Dust 1 (Radio Edit)"})
    assert v.state == ResultState.DUDOSO and v.doubt == DoubtKind.VERSION
    assert any("Duración" in r for r in v.reasons_es)
    plain = _v(tmp_path, "p.flac", row=_row(dur=40), seconds=18, tags=TAGS)
    assert plain.doubt == DoubtKind.DURACION


def test_truncated(tmp_path):
    v = _v(tmp_path, "t.flac", seconds=20, truncate_to_s=8, tags=TAGS)
    assert v.state == ResultState.DUDOSO and v.doubt == DoubtKind.DURACION and "truncado" in v.flags


def test_no_tags_identified_by_name(tmp_path):
    v = _v(tmp_path, "Fjaak - Spirit.flac", tail="Fjaak\\Fjaak - Spirit.flac")
    assert v.state == ResultState.VERIFICADO and "sin_tags" in v.flags


def test_fake_lossless_stays_marked(tmp_path):
    v = _v(tmp_path, "f.flac", lowpass_hz=16000, tags=TAGS)
    assert v.state == ResultState.DUDOSO and v.doubt == DoubtKind.ESPECTRO and "posible_falso_lossless" in v.flags
    off = verify_file(_row(), tmp_path / "f.flac", LOSSLESS, lossy_allowed=False, source_path_tail=None,
                      spectral=False)
    assert off.state == ResultState.VERIFICADO


def test_wrong_artist_is_identity_doubt(tmp_path):
    v = _v(tmp_path, "w.flac", tags={"artist": "Duffy", "title": "Spirit"})
    assert v.state == ResultState.DUDOSO and v.doubt == DoubtKind.IDENTIDAD


def test_duration_review_band_and_unknown_duration(tmp_path):
    v = _v(tmp_path, "d.flac", row=_row(dur=26), seconds=20, tags=TAGS)   # 6 s off: review band
    assert v.state == ResultState.VERIFICADO and v.score == 90
    n = _v(tmp_path, "n.flac", row=_row(dur=None), tags=TAGS)
    assert "sin_duracion_esperada" in n.flags and n.score == 95 and n.state == ResultState.VERIFICADO


def test_doubtful_never_shows_acceptance_confidence(tmp_path):
    """DUDOSO => score < the acceptance threshold; hard doubts below the 'revisar' band too."""
    hard = {
        "version": _v(tmp_path, "hv.flac", tags={"artist": "Fjaak", "title": "Spirit (Kai Van Dongen Remix)"}),
        "duracion": _v(tmp_path, "hd.flac", row=_row(dur=40), seconds=18, tags=TAGS),
        "truncado": _v(tmp_path, "ht.flac", seconds=20, truncate_to_s=8, tags=TAGS),
        "identidad": _v(tmp_path, "hi.flac", tags={"artist": "Duffy", "title": "Spirit"}),
    }
    for name, v in hard.items():
        assert v.state == ResultState.DUDOSO, name
        assert v.score < REVIEW_SCORE, (name, v.score)
    spec = _v(tmp_path, "hs.flac", lowpass_hz=16000, tags=TAGS)       # right song, suspicious spectrum
    assert spec.doubt == DoubtKind.ESPECTRO and REVIEW_SCORE <= spec.score < ACCEPT_SCORE


@pytest.mark.parametrize("dur", [20, None])
@pytest.mark.parametrize("want,got", [("Dust 1", "Dust 2"), ("Untitled 1", "Untitled 2"), ("A1", "B2"),
                                      ("Part 1", "Part 2")])
def test_other_number_in_the_title_is_another_track(tmp_path, want, got, dur):
    """'Dust 1' vs 'Dust 2' used to score 87-92 and pass as VERIFICADO (P1): now DUDOSO/IDENTIDAD,
    also without an expected duration."""
    v = _v(tmp_path, f"{want} {dur}.flac", row=_row("Blasha & Allatt", want, dur=dur),
           tags={"artist": "Blasha & Allatt", "title": got})
    assert v.state == ResultState.DUDOSO and v.doubt == DoubtKind.IDENTIDAD, v.reasons_es
    assert any("mismos números" in r for r in v.reasons_es) and v.score < REVIEW_SCORE


def test_partial_artist_is_identity_doubt_but_a_collab_tag_is_fine(tmp_path):
    v = _v(tmp_path, "p.flac", row=_row("Planetary Assault Systems", "Gated"),
           tags={"artist": "Systems", "title": "Gated"})
    assert v.state == ResultState.DUDOSO and v.doubt == DoubtKind.IDENTIDAD
    ok = _v(tmp_path, "c.flac", tags={"artist": "Fjaak, Chris Liebing", "title": "Spirit"})
    assert ok.state == ResultState.VERIFICADO and ok.score == 100
    num = _v(tmp_path, "n.flac", row=_row("808 State", "Pacific State"),
             tags={"artist": "808 State", "title": "Pacific State"})
    assert num.state == ResultState.VERIFICADO


@pytest.mark.parametrize("dur", [20, None])
@pytest.mark.parametrize("want,got", [("Adam Beyer", "Adam Port"), ("Chris Liebing", "Chris Lake"),
                                      ("Len Faki", "Ken Faki")])
def test_r3_b1_an_artist_with_a_similar_name_is_never_verified(tmp_path, want, got, dur):
    """Audit round 3, B1: same title, similar artist name. These scored 82-96 and passed as VERIFICADO;
    now they are another artist: DUDOSO/IDENTIDAD (to _dudosos), with or without an expected duration."""
    v = _v(tmp_path, f"{got} {dur}.flac", row=_row(want, "Rush", dur=dur), tags={"artist": got, "title": "Rush"})
    assert v.state == ResultState.DUDOSO and v.doubt == DoubtKind.IDENTIDAD, v.reasons_es
    assert v.score < REVIEW_SCORE
    assert any(r.startswith(f"Otro artista: '{got}' no es '{want}'") and "palabra por palabra" in r
               for r in v.reasons_es), v.reasons_es


@pytest.mark.parametrize("want,got", [("Chris Liebing", "CHRIS LIEBING"), ("DJ Rush", "Dj Rush"),
                                      ("\u00d8 [Phase]", "O [Phase]"), ("Blasha & Allatt", "Allatt & Blasha"),
                                      ("Roll Dann", "Roll Dann & Laster Records"), ("H\u00e9ctor Oaks", "Hector Oaks")])
def test_r3_b1_genuine_artist_variants_are_still_verified(tmp_path, want, got):
    v = _v(tmp_path, "g.flac", row=_row(want, "Rush"), tags={"artist": got, "title": "Rush"})
    assert v.state == ResultState.VERIFICADO and v.score == 100, v.reasons_es


def test_mp3_vbr_and_256_do_not_meet_format(tmp_path):
    v = _v(tmp_path, "v.mp3", accept=MP3, lossy=True, fmt="mp3", vbr=True, tags=TAGS)
    assert v.state == ResultState.NO_CUMPLE_FORMATO and "mp3_vbr" in v.flags
    s = _v(tmp_path, "s.mp3", accept=MP3, lossy=True, fmt="mp3", mp3_kbps=256, tags=TAGS)
    assert s.state == ResultState.NO_CUMPLE_FORMATO
    ok = _v(tmp_path, "o.mp3", accept=MP3, lossy=True, fmt="mp3", tags=TAGS)
    assert ok.state == ResultState.VERIFICADO
    # without LAME's Xing/Info frame the header says nothing: the frames decide (P2)
    hv = _v(tmp_path, "hv.mp3", accept=MP3, lossy=True, fmt="mp3", vbr=True, mp3_info_frame=False, tags=TAGS)
    assert hv.state == ResultState.NO_CUMPLE_FORMATO and "mp3_vbr" in hv.flags
    hc = _v(tmp_path, "hc.mp3", accept=MP3, lossy=True, fmt="mp3", mp3_info_frame=False, tags=TAGS)
    assert hc.state == ResultState.VERIFICADO and "mp3_modo_desconocido" in hc.flags
