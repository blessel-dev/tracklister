"""Synthetic audio fixtures (numpy + soundfile + mutagen). No network, no external encoder.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

make_track() writes FLAC/WAV/AIFF/MP3 with broadband noise plus a few tones, optionally:
- low-passed with an FFT brick-wall mask (simulates a lossy transcode: "fake lossless");
- truncated by cutting bytes off the end (header still announces the full length);
- tagged with mutagen (artist/title/album and an embedded cover).
make_low_treble_track() is the negative case: little treble but a smooth roll-off, no sharp cut.

Imported by tests and by tests/fakes/fake_engine.py (a subprocess): stdlib + numpy + soundfile +
mutagen only.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np
import soundfile as sf

# libsndfile 1.2.2 (soundfile 0.14.0, pinned) maps compression_level to LAME's CBR bitrate; measured on the
# frame headers (tests/verify/test_spectral_calibration.py checks each one). VBR level 0.0 is LAME's V0.
_MP3_LEVEL_FOR_KBPS = {320: 0.0, 256: 0.2, 224: 0.3, 192: 0.4, 160: 0.5, 128: 0.65}
_SUBTYPE = {16: "PCM_16", 24: "PCM_24", 32: "PCM_32"}


def tiny_png(size: int = 8, shade: int = 128) -> bytes:
    """A valid grayscale PNG (used as embedded cover art)."""
    raw = b"".join(b"\x00" + bytes([shade]) * size for _ in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _fft_filter(x: np.ndarray, sr: int, gain_fn) -> np.ndarray:
    n = x.shape[0]
    spec = np.fft.rfft(x, axis=0)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    spec *= gain_fn(freqs)[:, None]
    return np.fft.irfft(spec, n=n, axis=0)


def make_signal(seconds: float, samplerate: int = 44100, *, channels: int = 2, seed: int = 0,
                lowpass_hz: float | None = None, low_treble: bool = False) -> np.ndarray:
    n = max(1, int(round(seconds * samplerate)))
    rng = np.random.default_rng(seed)
    x = rng.standard_normal((n, channels)) * 0.12
    t = np.arange(n) / samplerate
    for f, a in ((55.0 * (1 + seed % 3), 0.20), (440.0, 0.05), (2500.0 + 100 * (seed % 5), 0.02)):
        x += a * np.sin(2 * np.pi * f * t)[:, None]
    if lowpass_hz:
        x = _fft_filter(x, samplerate, lambda f: (f <= lowpass_hz).astype(float))
    if low_treble:
        # About -12 dB/octave above 1.5 kHz: dark, but no brick wall anywhere.
        x = _fft_filter(x, samplerate, lambda f: 1.0 / (1.0 + (f / 1500.0) ** 2))
    peak = float(np.max(np.abs(x))) or 1.0
    return (x / peak * 0.8).astype(np.float32)


def _write_tags(path: Path, fmt: str, tags: dict) -> None:
    import mutagen
    from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1

    cover = tags.get("cover")
    if fmt == "flac":
        from mutagen.flac import FLAC, Picture
        f = FLAC(path)
        for k in ("artist", "title", "album"):
            if tags.get(k):
                f[k] = [tags[k]]
        if cover:
            pic = Picture()
            pic.type, pic.mime, pic.desc, pic.data = 3, "image/png", "cover", cover
            pic.width = pic.height = 8
            pic.depth = 8
            f.add_picture(pic)
        f.save()
        return
    f = mutagen.File(path)
    if f is None:
        raise ValueError(f"mutagen cannot open {path}")
    if f.tags is None:
        f.add_tags()
    id3: ID3 = f.tags
    if tags.get("artist"):
        id3.add(TPE1(encoding=3, text=[tags["artist"]]))
    if tags.get("title"):
        id3.add(TIT2(encoding=3, text=[tags["title"]]))
    if tags.get("album"):
        id3.add(TALB(encoding=3, text=[tags["album"]]))
    if cover:
        id3.add(APIC(encoding=3, mime="image/png", type=3, desc="cover", data=cover))
    if fmt == "mp3":
        f.save(v2_version=3)
    else:
        f.save()


_L3_KBPS_MPEG1 = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)


def strip_mp3_info_frame(path) -> bool:
    """Remove the Xing/Info/VBRI frame (the first MPEG frame, written by LAME) of an MP3 file, so the
    header no longer says whether it is CBR or VBR. Returns True when a frame was removed."""
    path = Path(path)
    data = path.read_bytes()
    pos = 0
    if data[:3] == b"ID3":
        pos = 10 + (((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) | ((data[8] & 0x7F) << 7) | (data[9] & 0x7F))
    b1, b2 = data[pos + 1], data[pos + 2]
    if data[pos] != 0xFF or (b1 & 0xE0) != 0xE0 or (b1 >> 3) & 3 != 3 or (b1 >> 1) & 3 != 1:
        return False                                   # only MPEG-1 Layer III (what libsndfile writes here)
    kbps = _L3_KBPS_MPEG1[(b2 >> 4) & 0xF]
    sr = (44100, 48000, 32000)[(b2 >> 2) & 3]
    length = 144000 * kbps // sr + ((b2 >> 1) & 1)
    head = data[pos:pos + 64]
    if not (b"Xing" in head or b"Info" in head or b"VBRI" in head):
        return False
    path.write_bytes(data[:pos] + data[pos + length:])
    return True


def make_track(path, *, fmt: str, seconds: float, samplerate: int = 44100, bitdepth: int = 16,
               lowpass_hz: float | None = None, mp3_kbps: int | None = None, vbr: bool = False,
               tags: dict | None = None, truncate_to_s: float | None = None, seed: int = 0,
               channels: int = 2, low_treble: bool = False, float_pcm: bool = False,
               mp3_info_frame: bool = True, subtype: str | None = None) -> Path:
    """Write one synthetic file. `fmt` is the real container: flac|wav|aiff|mp3.

    mp3_info_frame=False drops LAME's Xing/Info frame: mutagen then reports an UNKNOWN bitrate mode
    and only the first frame's bitrate (a VBR file of this generator starts with a 320 kbps frame).
    subtype (WAV/AIFF/FLAC) forces libsndfile's codec, e.g. "ULAW" or "IMA_ADPCM": a lossy WAV/AIFF."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = fmt.lower()
    x = make_signal(seconds, samplerate, channels=channels, seed=seed, lowpass_hz=lowpass_hz,
                    low_treble=low_treble)
    if fmt == "mp3":
        kbps = mp3_kbps or 320
        sf.write(str(path), x, samplerate, format="MP3", subtype="MPEG_LAYER_III",
                 bitrate_mode="VARIABLE" if vbr else "CONSTANT",
                 compression_level=0.0 if vbr else _MP3_LEVEL_FOR_KBPS.get(kbps, 0.0))
        if not mp3_info_frame and not strip_mp3_info_frame(path):
            raise ValueError(f"no Xing/Info frame to remove in {path.name}")
    else:
        subtype = subtype or ("FLOAT" if float_pcm else _SUBTYPE[bitdepth])
        sf.write(str(path), x, samplerate, format={"flac": "FLAC", "wav": "WAV", "aiff": "AIFF"}[fmt],
                 subtype=subtype)
    if tags:
        _write_tags(path, fmt, tags)
    if truncate_to_s is not None and truncate_to_s < seconds:
        size = path.stat().st_size
        keep = max(64, int(size * (truncate_to_s / seconds)))
        with open(path, "r+b") as f:
            f.truncate(keep)
    return path


def make_low_treble_track(path, *, fmt: str = "flac", seconds: float = 20, **kw) -> Path:
    """Dub-techno-like file: very little treble, smooth roll-off, NOT a transcode."""
    return make_track(path, fmt=fmt, seconds=seconds, low_treble=True, **kw)
