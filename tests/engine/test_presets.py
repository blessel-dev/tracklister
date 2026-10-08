"""Preset -> passes and post-download accept rules (01 section 6.3, Addendum 5 and 6).

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import json

import pytest

from tracklister.core.settings import CustomPreset
from tracklister.engine.presets import PresetId, build_preset, relaxed


def _names(p):
    return [x.name for x in p.passes]


def test_lossless_default_then_mp3_only_after_asking():
    p = build_preset("lossless")
    assert p.id == PresetId.LOSSLESS and p.label_es == "Lossless"
    assert _names(p) == ["lossless", "mp3_320"]
    assert p.passes[0].formats == ("flac", "wav", "aiff", "aif") and not p.passes[0].lossy
    assert p.passes[1].formats == ("mp3",) and p.passes[1].lossy and p.passes[1].min_bitrate == 320
    assert p.accept.containers == {"flac", "wav", "aiff"} and p.accept.mp3_min_kbps == 320
    assert not p.accept.converts


def test_cdj_prefers_aiff_wav_then_flac_converted_then_asked_mp3():
    p = build_preset("cdj_antiguos")
    assert _names(p) == ["aiff_wav", "flac_a_aiff", "mp3_320"]
    assert p.passes[0].formats == ("aiff", "aif", "wav")
    assert p.passes[1].formats == ("flac",)
    assert p.passes[2].lossy
    assert p.accept.convert_to_aiff == {"flac"} and p.accept.converts
    assert (p.accept.max_samplerate, p.accept.max_bitdepth) == (48000, 24)
    # no search-time sample-rate filter: hi-res FLACs are downloaded and converted (Addendum 5)
    assert all(x.max_samplerate is None for x in p.passes)


def test_mp3_only_no_question_and_no_lossless_accepted():
    p = build_preset("solo_mp3_320")
    assert _names(p) == ["mp3_320"] and not p.passes[0].lossy
    assert p.passes[0].min_bitrate == 320 and p.accept.containers == frozenset()
    assert p.accept.mp3_min_kbps == 320


@pytest.mark.parametrize("pid", ["lossless", "cdj_antiguos", "solo_mp3_320", "personalizado"])
def test_every_pass_is_strict_and_never_m4a(pid):
    for x in build_preset(pid).passes:
        assert x.strict_title and x.strict_artist and x.length_tol_s == 3
        assert "m4a" not in x.formats
    r = relaxed(build_preset(pid).passes[0])
    assert r.strict_title and not r.strict_artist


def test_custom_preset_formats_and_fallback():
    p = build_preset("personalizado", CustomPreset(formats=["FLAC", ".aif", "m4a", "ogg"],
                                                    max_samplerate=48000, max_bitdepth=24))
    assert _names(p) == ["personalizado"]
    assert p.passes[0].formats == ("flac", "aiff", "aif") and p.passes[0].max_samplerate == 48000
    assert p.accept.containers == {"flac", "aiff"} and p.accept.mp3_min_kbps is None
    q = build_preset("personalizado", CustomPreset(formats=["wav"], allow_lossy_fallback=True))
    assert _names(q) == ["personalizado", "mp3_320"] and q.passes[1].lossy
    m = build_preset("personalizado", CustomPreset(formats=["mp3"], min_mp3_kbps=256))
    assert _names(m) == ["mp3_256"] and not m.passes[0].lossy and m.accept.mp3_min_kbps == 256
    empty = build_preset("personalizado", CustomPreset(formats=["m4a"]))
    assert empty.passes[0].formats == ("flac", "wav", "aiff", "aif")


def test_snapshot_is_json():
    snap = build_preset("cdj_antiguos").to_snapshot()
    back = json.loads(json.dumps(snap))
    assert back["id"] == "cdj_antiguos" and back["accept"]["convert_to_aiff"] == ["flac"]
    assert [x["name"] for x in back["passes"]] == ["aiff_wav", "flac_a_aiff", "mp3_320"]


def test_unknown_preset_raises():
    with pytest.raises(ValueError):
        build_preset("otro")
