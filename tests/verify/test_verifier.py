"""verify_file(): the fixed verdict rules on synthetic files.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

from tests.fakes.synth import make_track
from tracklister.core.model import DoubtKind, ResultState, TrackRow
from tracklister.engine.presets import build_preset
from tracklister.verify.verifier import verify_file

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


def test_mp3_vbr_and_256_do_not_meet_format(tmp_path):
    v = _v(tmp_path, "v.mp3", accept=MP3, lossy=True, fmt="mp3", vbr=True, tags=TAGS)
    assert v.state == ResultState.NO_CUMPLE_FORMATO and "mp3_vbr" in v.flags
    s = _v(tmp_path, "s.mp3", accept=MP3, lossy=True, fmt="mp3", mp3_kbps=256, tags=TAGS)
    assert s.state == ResultState.NO_CUMPLE_FORMATO
    ok = _v(tmp_path, "o.mp3", accept=MP3, lossy=True, fmt="mp3", tags=TAGS)
    assert ok.state == ResultState.VERIFICADO
