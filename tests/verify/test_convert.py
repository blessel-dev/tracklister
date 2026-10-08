"""CDJ conversion: FLAC 96k/24 -> AIFF 48k/24 with tags + cover; exact copies; never AIFF-C/float."""
from __future__ import annotations

import mutagen
import numpy as np
import soundfile as sf

from tests.fakes.synth import make_track, tiny_png
from tracklister.verify.convert import target_samplerate, to_aiff_pcm


def _is_plain_aiff(p):
    head = p.read_bytes()[:12]
    return head[:4] == b"FORM" and head[8:12] == b"AIFF"


def test_flac_96k_24_to_aiff_48k_24_keeps_tags_and_cover(tmp_path):
    cover = tiny_png()
    src = make_track(tmp_path / "s.flac", fmt="flac", seconds=6, samplerate=96000, bitdepth=24,
                     tags={"artist": "Fjaak", "title": "Spirit", "album": "Live", "cover": cover})
    r = to_aiff_pcm(src, tmp_path / "out" / "s.aiff")
    info = sf.info(str(r.dst))
    assert (r.samplerate, r.bitdepth, r.downconverted) == (48000, 24, True) and "48 kHz" in r.warning_es
    assert info.samplerate == 48000 and info.subtype == "PCM_24" and abs(info.frames - 6 * 48000) <= 1
    assert _is_plain_aiff(r.dst)
    tags = mutagen.File(str(r.dst)).tags
    assert tags.version[:2] == (2, 3)
    assert str(tags["TPE1"]) == "Fjaak" and str(tags["TIT2"]) == "Spirit" and str(tags["TALB"]) == "Live"
    assert tags.getall("APIC")[0].data == cover
    assert not (tmp_path / "out" / "s.aiff.part").exists()


def test_within_limits_is_an_exact_copy(tmp_path):
    src = make_track(tmp_path / "cd.flac", fmt="flac", seconds=3)
    r = to_aiff_pcm(src, tmp_path / "cd.aiff")
    assert not r.downconverted and r.warning_es is None and sf.info(str(r.dst)).subtype == "PCM_16"
    a, _ = sf.read(str(src), dtype="int16")
    b, _ = sf.read(str(r.dst), dtype="int16")
    assert np.array_equal(a, b)
    src24 = make_track(tmp_path / "s24.flac", fmt="flac", seconds=2, samplerate=48000, bitdepth=24)
    r24 = to_aiff_pcm(src24, tmp_path / "s24.aiff")
    a, _ = sf.read(str(src24), dtype="int32")
    b, _ = sf.read(str(r24.dst), dtype="int32")
    assert np.array_equal(a, b) and r24.samplerate == 48000


def test_resampler_accuracy_and_rate_rules(tmp_path):
    sr = 88200
    x = 0.5 * np.sin(2 * np.pi * 1000 * np.arange(sr) / sr)
    sf.write(str(tmp_path / "t.flac"), np.column_stack([x, x]), sr, subtype="PCM_24")
    r = to_aiff_pcm(tmp_path / "t.flac", tmp_path / "t.aiff")
    y, sr2 = sf.read(str(r.dst))
    assert sr2 == 44100 and len(y) == 44100
    ref = 0.5 * np.sin(2 * np.pi * 1000 * np.arange(len(y)) / sr2)
    assert np.max(np.abs(y[500:-500, 0] - ref[500:-500])) < 1e-4
    assert [target_samplerate(s, 48000) for s in (44100, 48000, 88200, 96000, 176400, 192000, 64000)] == \
        [44100, 48000, 44100, 48000, 44100, 48000, 48000]


def test_float_and_aifc_become_pcm24(tmp_path):
    for name, fmt in (("f.wav", "wav"), ("f.aiff", "aiff")):
        src = make_track(tmp_path / name, fmt=fmt, seconds=2, samplerate=48000, float_pcm=True)
        r = to_aiff_pcm(src, tmp_path / (name + ".out.aiff"))
        assert sf.info(str(r.dst)).subtype == "PCM_24" and _is_plain_aiff(r.dst) and r.bitdepth == 24
