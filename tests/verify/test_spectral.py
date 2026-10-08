"""Fake-lossless check on synthetic audio: brick-wall cuts flagged, dark mixes not."""
from __future__ import annotations

import pytest

from tests.fakes.synth import make_low_treble_track, make_track
from tracklister.verify.spectral import fake_lossless_check


def test_full_band_not_flagged(tmp_path):
    r = fake_lossless_check(make_track(tmp_path / "f.flac", fmt="flac", seconds=12))
    assert not r.suspicious and r.reason_es is None


@pytest.mark.parametrize("cut", [16000, 19000])
def test_lowpass_flagged(tmp_path, cut):
    r = fake_lossless_check(make_track(tmp_path / "l.flac", fmt="flac", seconds=12, lowpass_hz=cut))
    assert r.suspicious and abs(r.cutoff_hz - cut) <= 600 and r.drop_db >= 25
    assert "kHz" in r.reason_es and "se queda en el set" in r.reason_es.lower()


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_low_treble_without_sharp_cut_not_flagged(tmp_path, seed):
    r = fake_lossless_check(make_low_treble_track(tmp_path / "d.flac", seconds=12, seed=seed))
    assert not r.suspicious


def test_hires_upsampled_transcode_flagged(tmp_path):
    p = make_track(tmp_path / "h.flac", fmt="flac", seconds=6, samplerate=96000, bitdepth=24, lowpass_hz=16000)
    assert fake_lossless_check(p).suspicious
    q = make_track(tmp_path / "h2.flac", fmt="flac", seconds=6, samplerate=96000, bitdepth=24)
    assert not fake_lossless_check(q).suspicious


def test_cut_outside_band_and_too_short_are_ignored(tmp_path):
    assert not fake_lossless_check(make_track(tmp_path / "a.flac", fmt="flac", seconds=8, lowpass_hz=21000)).suspicious
    assert not fake_lossless_check(make_track(tmp_path / "b.flac", fmt="flac", seconds=0.1)).suspicious
