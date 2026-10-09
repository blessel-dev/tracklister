"""Lossless -> AIFF PCM for "CDJ antiguos" (soundfile + numpy + mutagen; no ffmpeg, no scipy).

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

- Keeps sample rate and bit depth when within the limits (exact sample copy).
- 96k/192k -> 48k and 88.2k/176.4k -> 44.1k (integer ratios); any other rate over the limit -> 48k.
  Resampling: windowed-sinc (Kaiser) FIR, rational L/M, FFT block convolution, streaming.
- More than 24 bits or float -> 24-bit with TPDF dither. Output is PCM_16 or PCM_24 AIFF only,
  never AIFF-C, never float.
- Tags and cover art are copied into an ID3v2.3 chunk with mutagen.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf

_BITS = {"PCM_S8": 8, "PCM_U8": 8, "PCM_16": 16, "PCM_24": 24, "PCM_32": 32, "FLOAT": 32, "DOUBLE": 64}
BLOCK = 1 << 15


@dataclass(frozen=True)
class ConvertResult:
    dst: Path
    samplerate: int
    bitdepth: int
    downconverted: bool
    warning_es: str | None


def target_samplerate(sr: int, max_samplerate: int) -> int:
    if sr <= max_samplerate:
        return sr
    if sr % 44100 == 0 and 44100 <= max_samplerate:
        return 44100
    if sr % 48000 == 0 and 48000 <= max_samplerate:
        return 48000
    return 48000 if max_samplerate >= 48000 else 44100


class _Resampler:
    """Streaming rational resampler: zero-stuff by L, low-pass FIR, keep every M-th sample."""

    def __init__(self, L: int, M: int, channels: int, taps_per_phase: int = 48):
        self.L, self.M, self.ch = L, M, channels
        r = max(L, M)
        n_taps = 2 * taps_per_phase * r + 1
        cutoff = 0.5 / r * 0.94
        n = np.arange(n_taps) - (n_taps - 1) / 2
        h = 2 * cutoff * np.sinc(2 * cutoff * n) * np.kaiser(n_taps, 9.0)
        self.h = h / h.sum() * L
        self.N = n_taps
        self.delay = (n_taps - 1) // 2
        self.tail = np.zeros((n_taps - 1, channels))
        self.pos = 0          # upsampled-stream index of the first sample of the next filtered block
        self.n_in = 0
        self.n_out = 0
        self._H: dict[int, np.ndarray] = {}

    def _filter(self, u: np.ndarray) -> np.ndarray:
        ext = np.vstack([self.tail, u])
        self.tail = ext[-(self.N - 1):]
        F = 1 << int(math.ceil(math.log2(len(ext) + self.N - 1)))
        if F not in self._H:
            self._H[F] = np.fft.rfft(self.h, F)[:, None]
        y = np.fft.irfft(np.fft.rfft(ext, F, axis=0) * self._H[F], F, axis=0)
        return y[self.N - 1: len(ext)]

    def _pick(self, y: np.ndarray) -> np.ndarray:
        start = self.pos
        self.pos += len(y)
        # outputs live at upsampled positions delay + M*i
        first = self.delay + self.M * max(0, math.ceil((start - self.delay) / self.M))
        idx = np.arange(first, start + len(y), self.M) - start
        return y[idx] if len(idx) else np.zeros((0, self.ch))

    def process(self, x: np.ndarray) -> np.ndarray:
        self.n_in += len(x)
        u = np.zeros((len(x) * self.L, self.ch))
        u[:: self.L] = x
        out = self._pick(self._filter(u))
        self.n_out += len(out)
        return out

    def flush(self) -> np.ndarray:
        want = math.ceil(self.n_in * self.L / self.M)
        pad = math.ceil((self.N - 1) / self.L) + self.M
        out = self._pick(self._filter(np.zeros((pad * self.L, self.ch))))
        out = out[: max(0, want - self.n_out)]
        self.n_out += len(out)
        return out


def _dither(y: np.ndarray, bits: int, rng: np.random.Generator) -> np.ndarray:
    lsb = 2.0 ** -(bits - 1)
    y = y + (rng.random(y.shape) - rng.random(y.shape)) * lsb
    return np.clip(y, -1.0, 1.0 - lsb)


def _id3_frames_from(src: Path) -> list:
    import mutagen
    from mutagen.flac import FLAC
    from mutagen.id3 import (APIC, COMM, TALB, TBPM, TCON, TDRC, TIT2, TKEY, TPE1, TPE2, TPOS, TPUB, TRCK,
                             TSRC)

    try:
        f = mutagen.File(str(src))
    except Exception:  # noqa: BLE001
        return []
    if f is None:
        return []
    frames: list = []
    if isinstance(f, FLAC):
        tags = f.tags or {}
        mapping = {"artist": TPE1, "title": TIT2, "album": TALB, "albumartist": TPE2, "tracknumber": TRCK,
                   "discnumber": TPOS, "date": TDRC, "year": TDRC, "genre": TCON, "label": TPUB,
                   "organization": TPUB, "bpm": TBPM, "isrc": TSRC, "initialkey": TKEY, "key": TKEY}
        seen = set()
        for key, cls in mapping.items():
            vals = tags.get(key) if hasattr(tags, "get") else None
            if vals and cls.__name__ not in seen:
                frames.append(cls(encoding=3, text=[str(v) for v in vals]))
                seen.add(cls.__name__)
        comment = tags.get("comment") if hasattr(tags, "get") else None
        if comment:
            frames.append(COMM(encoding=3, lang="eng", desc="", text=[str(comment[0])]))
        for pic in f.pictures:
            frames.append(APIC(encoding=3, mime=pic.mime or "image/jpeg", type=pic.type, desc=pic.desc or "",
                               data=pic.data))
        return frames
    tags = getattr(f, "tags", None)
    if tags is not None and hasattr(tags, "values"):
        try:
            return [fr for fr in tags.values() if hasattr(fr, "FrameID")]
        except Exception:  # noqa: BLE001
            return []
    return []


def _write_id3(dst: Path, frames: list) -> None:
    if not frames:
        return
    from mutagen.aiff import AIFF
    a = AIFF(str(dst))
    if a.tags is None:
        a.add_tags()
    for fr in frames:
        a.tags.add(fr)
    a.save(v2_version=3)


def to_aiff_pcm(src: Path, dst: Path, *, max_samplerate: int = 48000, max_bitdepth: int = 24) -> ConvertResult:
    src, dst = Path(src), Path(dst)
    info = sf.info(str(src))
    sr, ch, subtype = info.samplerate, info.channels, info.subtype
    src_bits = _BITS.get(subtype, 16)
    is_float = subtype in ("FLOAT", "DOUBLE")
    tsr = target_samplerate(sr, max_samplerate)
    tbits = 24 if (is_float or src_bits > 24) else max(16, src_bits)
    tbits = min(tbits, max_bitdepth if max_bitdepth >= 16 else 16)
    out_subtype = "PCM_24" if tbits == 24 else "PCM_16"
    exact = tsr == sr and tbits == src_bits and not is_float
    tmp = dst.with_name(dst.name + ".part")
    dst.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(12345)
    try:
        with sf.SoundFile(str(src)) as fin, sf.SoundFile(str(tmp), "w", samplerate=tsr, channels=ch,
                                                          subtype=out_subtype, format="AIFF") as fout:
            if exact:
                while True:
                    block = fin.read(BLOCK, dtype="int32", always_2d=True)
                    if len(block) == 0:
                        break
                    fout.write(block)
            elif tsr == sr:
                while True:
                    block = fin.read(BLOCK, dtype="float64", always_2d=True)
                    if len(block) == 0:
                        break
                    fout.write(_dither(block, tbits, rng))
            else:
                ratio = Fraction(tsr, sr).limit_denominator(1000)
                rs = _Resampler(ratio.numerator, ratio.denominator, ch)
                while True:
                    block = fin.read(BLOCK, dtype="float64", always_2d=True)
                    if len(block) == 0:
                        break
                    y = rs.process(block)
                    if len(y):
                        fout.write(_dither(y, tbits, rng))
                y = rs.flush()
                if len(y):
                    fout.write(_dither(y, tbits, rng))
        _write_id3(tmp, _id3_frames_from(src))
        os.replace(tmp, dst)
    finally:
        if tmp.exists():
            tmp.unlink()
    down = tsr != sr or tbits < src_bits
    warning = None
    if down:
        warning = (f"Convertido de {sr / 1000:g} kHz/{src_bits} bits a {tsr / 1000:g} kHz/{tbits} bits "
                   "para que lo lean los CDJ antiguos. El original está en _originales.")
    return ConvertResult(dst, tsr, tbits, down, warning)
