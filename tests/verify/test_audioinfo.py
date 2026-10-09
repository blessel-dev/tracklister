"""probe(): real container by header, truncation, tags, MP3 bitrate mode.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

from tests.fakes.synth import make_track
from tracklister.verify.audioinfo import mp3_frame_bitrates, probe


def test_flac_with_tags(tmp_path):
    i = probe(make_track(tmp_path / "a.flac", fmt="flac", seconds=6, bitdepth=24, samplerate=48000,
                         tags={"artist": "Fjaak", "title": "Spirit", "album": "Live"}))
    assert (i.container, i.ext_matches, i.samplerate, i.bitdepth, i.channels) == ("flac", True, 48000, 24, 2)
    assert (i.tag_artist, i.tag_title, i.tag_album) == ("Fjaak", "Spirit", "Live") and i.has_tags
    assert abs(i.duration_s - 6) < 0.05 and abs(i.decoded_duration_s - 6) < 0.05


def test_truncated_flac_decodes_shorter_than_header(tmp_path):
    i = probe(make_track(tmp_path / "t.flac", fmt="flac", seconds=20, truncate_to_s=8))
    assert i.duration_s == 20.0 and i.decoded_duration_s < 10


def test_no_tags_is_not_falsy_trap(tmp_path):
    i = probe(make_track(tmp_path / "n.wav", fmt="wav", seconds=3))
    assert i.container == "wav" and i.samplerate == 44100 and i.bitdepth == 16 and not i.has_tags


def test_mp3_renamed_flac_is_detected(tmp_path):
    i = probe(make_track(tmp_path / "fake.flac", fmt="mp3", seconds=4))
    assert i.container == "mp3" and not i.ext_matches and i.bitrate_kbps == 320 and i.bitrate_mode == "cbr"


def test_mp3_modes(tmp_path):
    assert probe(make_track(tmp_path / "v.mp3", fmt="mp3", seconds=4, vbr=True)).bitrate_mode == "vbr"
    c = probe(make_track(tmp_path / "c.mp3", fmt="mp3", seconds=4, mp3_kbps=256))
    assert (c.bitrate_kbps, c.bitrate_mode) == (256, "cbr")


def test_mp3_without_info_frame_reads_frames_across_the_file(tmp_path):
    v = probe(make_track(tmp_path / "v.mp3", fmt="mp3", seconds=6, vbr=True, mp3_info_frame=False))
    assert v.bitrate_mode == "unknown" and v.bitrate_kbps == 320      # mutagen only saw the first frame
    assert len(v.mp3_frame_kbps) >= 40 and len(set(v.mp3_frame_kbps)) > 1
    c = probe(make_track(tmp_path / "c.mp3", fmt="mp3", seconds=6, mp3_info_frame=False,
                         tags={"artist": "Fjaak", "title": "Spirit"}))     # ID3v2 in front: skipped
    assert c.bitrate_mode == "unknown" and len(c.mp3_frame_kbps) >= 40 and set(c.mp3_frame_kbps) == {320}
    assert probe(make_track(tmp_path / "h.mp3", fmt="mp3", seconds=4)).mp3_frame_kbps is None   # Info: CBR
    assert probe(make_track(tmp_path / "w.flac", fmt="flac", seconds=2)).mp3_frame_kbps is None


def test_mp3_frame_scan_never_takes_noise_for_frames(tmp_path):
    import numpy as np
    p = tmp_path / "ruido.mp3"
    p.write_bytes(b"\xff\xfb\x90\x00" + np.random.default_rng(3).integers(0, 256, 200000, dtype=np.uint8).tobytes())
    assert mp3_frame_bitrates(p) == ()


def test_float_and_aifc(tmp_path):
    w = probe(make_track(tmp_path / "f.wav", fmt="wav", seconds=2, float_pcm=True))
    assert w.is_float and not w.is_aifc
    a = probe(make_track(tmp_path / "f.aiff", fmt="aiff", seconds=2, float_pcm=True))
    assert a.is_float and a.is_aifc and a.container == "aiff"


def test_garbage_file(tmp_path):
    p = tmp_path / "x.flac"
    p.write_bytes(b"not audio at all" * 10)
    i = probe(p)
    assert i.container == "unknown" and i.decoded_duration_s is None
