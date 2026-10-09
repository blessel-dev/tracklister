"""Quality rule per preset: MP3 CBR >= 320 only, CDJ conversions, Personalizado limits.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

from dataclasses import replace

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


def test_mp3_without_xing_or_info_frame_is_judged_by_its_frames(tmp_path):
    """No Xing/Info/VBRI frame: mutagen only sees the first frame (320 kbps here). Every frame read
    must have the same bitrate; a VBR file is refused, a real CBR 320 is accepted."""
    v = _q(tmp_path, "v.mp3", MP3, True, fmt="mp3", vbr=True, mp3_info_frame=False)
    assert not v.ok and "mp3_vbr" in v.flags and "VBR sin cabecera" in v.reasons_es[0]
    c = _q(tmp_path, "c.mp3", MP3, True, fmt="mp3", mp3_info_frame=False)
    assert c.ok and "mp3_modo_desconocido" in c.flags
    low = _q(tmp_path, "l.mp3", MP3, True, fmt="mp3", mp3_kbps=256, mp3_info_frame=False)
    assert not low.ok and "mp3_bajo_bitrate" in low.flags and "256" in low.reasons_es[0]
    # every preset that allows MP3 follows the same rule
    lv = _q(tmp_path, "lv.mp3", LOSSLESS, True, fmt="mp3", vbr=True, mp3_info_frame=False)
    assert not lv.ok and "mp3_vbr" in lv.flags
    cdj = _q(tmp_path, "cv.mp3", CDJ, True, fmt="mp3", vbr=True, mp3_info_frame=False)
    assert not cdj.ok and "mp3_vbr" in cdj.flags
    own = build_preset("personalizado", CustomPreset(formats=["mp3"], min_mp3_kbps=256)).accept
    assert _q(tmp_path, "o.mp3", own, True, fmt="mp3", mp3_kbps=256, mp3_info_frame=False).ok
    assert not _q(tmp_path, "ov.mp3", own, True, fmt="mp3", vbr=True, mp3_info_frame=False).ok


def test_mp3_with_unreadable_frames_is_never_accepted(tmp_path):
    info = probe(make_track(tmp_path / "c.mp3", fmt="mp3", seconds=3, mp3_info_frame=False))
    q = check_quality(replace(info, mp3_frame_kbps=()), MP3, lossy_allowed=True)
    assert not q.ok and "mp3_cabecera_ilegible" in q.flags and "no se puede comprobar" in q.reasons_es[0]


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
