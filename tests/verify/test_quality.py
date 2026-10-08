"""Quality rule per preset: MP3 CBR >= 320 only, CDJ conversions, Personalizado limits.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

from tests.fakes.synth import make_track
from tracklister.core.settings import CustomPreset
from tracklister.engine.presets import build_preset
from tracklister.verify.audioinfo import probe
from tracklister.verify.quality import check_quality

LOSSLESS = build_preset("lossless").accept
CDJ = build_preset("cdj_antiguos").accept
MP3 = build_preset("solo_mp3_320").accept


def _q(tmp_path, name, accept, lossy=False, **kw):
    return check_quality(probe(make_track(tmp_path / name, seconds=3, **kw)), accept, lossy_allowed=lossy)


def test_mp3_rules(tmp_path):
    assert _q(tmp_path, "a.mp3", MP3, True, fmt="mp3").ok
    v = _q(tmp_path, "v.mp3", MP3, True, fmt="mp3", vbr=True)
    assert not v.ok and "mp3_vbr" in v.flags and "CBR" in v.reasons_es[0]
    low = _q(tmp_path, "l.mp3", MP3, True, fmt="mp3", mp3_kbps=256)
    assert not low.ok and "mp3_bajo_bitrate" in low.flags and "256" in low.reasons_es[0]


def test_mp3_in_lossless_only_when_approved(tmp_path):
    assert not _q(tmp_path, "a.mp3", LOSSLESS, False, fmt="mp3").ok
    assert _q(tmp_path, "b.mp3", LOSSLESS, True, fmt="mp3").ok
    fake = _q(tmp_path, "c.flac", LOSSLESS, False, fmt="mp3")
    assert not fake.ok and "extension_distinta" in fake.flags


def test_lossless_accepts_hires_and_float_as_is(tmp_path):
    q = _q(tmp_path, "h.flac", LOSSLESS, fmt="flac", samplerate=96000, bitdepth=24)
    assert q.ok and not q.needs_conversion
    assert _q(tmp_path, "f.wav", LOSSLESS, fmt="wav", float_pcm=True).ok


def test_cdj_conversions(tmp_path):
    f = _q(tmp_path, "a.flac", CDJ, fmt="flac")
    assert f.ok and f.needs_conversion and "reducido_48k_24b" not in f.flags
    h = _q(tmp_path, "h.flac", CDJ, fmt="flac", samplerate=96000, bitdepth=24)
    assert h.ok and h.needs_conversion and "reducido_48k_24b" in h.flags
    w = _q(tmp_path, "w.wav", CDJ, fmt="wav")
    assert w.ok and not w.needs_conversion
    w96 = _q(tmp_path, "w96.wav", CDJ, fmt="wav", samplerate=96000, bitdepth=24)
    assert w96.ok and w96.needs_conversion
    ac = _q(tmp_path, "c.aiff", CDJ, fmt="aiff", float_pcm=True)
    assert ac.ok and ac.needs_conversion and "aiff_c_o_float" in ac.flags


def test_custom_limits_reject(tmp_path):
    acc = build_preset("personalizado", CustomPreset(formats=["flac"], max_samplerate=48000)).accept
    assert not _q(tmp_path, "h.flac", acc, fmt="flac", samplerate=96000).ok
    assert not _q(tmp_path, "w.wav", acc, fmt="wav").ok
    assert _q(tmp_path, "ok.flac", acc, fmt="flac").ok


def test_unreadable(tmp_path):
    p = tmp_path / "x.flac"
    p.write_bytes(b"garbage" * 20)
    q = check_quality(probe(p), LOSSLESS, lossy_allowed=False)
    assert not q.ok and "ilegible" in q.flags
