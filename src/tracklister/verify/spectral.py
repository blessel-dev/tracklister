"""Fake-lossless check (numpy only): a lossless file made from an MP3/AAC shows a brick-wall cut.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Averages the magnitude spectrum of ~20 windows spread over the track and looks for a SHARP cut
between 15.5 and 20.5 kHz: a drop of >= 25 dB within about 1 kHz with nothing above it. A dark
mix (dub techno) with little treble but a smooth roll-off is NOT flagged. The result only ever
marks a file "dudoso" (brief section 8); it never rejects it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

CUT_LOW_HZ, CUT_HIGH_HZ = 15500.0, 20500.0
MIN_DROP_DB = 25.0
BAND_HZ = 250.0


@dataclass(frozen=True)
class SpectralResult:
    suspicious: bool
    cutoff_hz: float | None
    drop_db: float | None
    reason_es: str | None


def _average_spectrum(path: Path, windows: int, fft_size: int) -> tuple[np.ndarray, int] | None:
    with sf.SoundFile(str(path)) as f:
        sr, n = f.samplerate, f.frames
        if sr < 32000 or n < fft_size * 2:
            return None
        start, stop = int(n * 0.05), int(n * 0.95) - fft_size
        if stop <= start:
            start, stop = 0, n - fft_size
        positions = np.linspace(start, stop, num=max(1, windows)).astype(int)
        win = np.hanning(fft_size)
        acc = np.zeros(fft_size // 2 + 1)
        used = 0
        for pos in positions:
            try:
                f.seek(int(pos))
                x = f.read(fft_size, dtype="float64", always_2d=True)
            except (RuntimeError, sf.LibsndfileError):
                break
            if len(x) < fft_size:
                continue
            mono = x.mean(axis=1)
            if not np.any(mono):
                continue
            acc += np.abs(np.fft.rfft(mono * win)) ** 2
            used += 1
        if used == 0:
            return None
        return acc / used, sr


def fake_lossless_check(path: Path, *, windows: int = 20, fft_size: int = 8192) -> SpectralResult:
    try:
        res = _average_spectrum(Path(path), windows, fft_size)
    except (RuntimeError, sf.LibsndfileError, OSError, ValueError):
        res = None
    if res is None:
        return SpectralResult(False, None, None, None)
    power, sr = res
    freqs = np.fft.rfftfreq(fft_size, 1.0 / sr)
    nyq = sr / 2.0
    top = min(nyq - 200.0, 22000.0)
    edges = np.arange(1000.0, top, BAND_HZ)
    if len(edges) < 8:
        return SpectralResult(False, None, None, None)
    band_db = []
    for lo in edges:
        sel = (freqs >= lo) & (freqs < lo + BAND_HZ)
        band_db.append(10 * np.log10(power[sel].mean() + 1e-20) if np.any(sel) else -200.0)
    band_db = np.array(band_db)
    centers = edges + BAND_HZ / 2
    ref = np.percentile(band_db[(centers > 1000) & (centers < 8000)], 75) if np.any(centers < 8000) else band_db.max()
    if ref < -140:   # silence
        return SpectralResult(False, None, None, None)
    found: list[tuple[float, float]] = []
    for i, c in enumerate(centers):
        fc = edges[i]                      # candidate cut at the lower edge of band i
        if fc < CUT_LOW_HZ or fc > CUT_HIGH_HZ:
            continue
        below = band_db[(centers >= fc - 1500) & (centers < fc - 250)]
        above = band_db[(centers > fc + 250) & (centers <= min(fc + 3000, top))]
        if len(below) < 3 or len(above) < 2:
            continue
        lvl_below = float(np.median(below))
        drop = lvl_below - float(np.median(above))
        nothing_above = float(np.max(band_db[centers > fc + 250])) <= lvl_below - MIN_DROP_DB + 5
        # the cut must be "sharp": the part just below it is still close to the music's level
        near_music = lvl_below >= ref - 45
        if drop >= MIN_DROP_DB and nothing_above and near_music:
            found.append((fc, drop))
    if not found:
        return SpectralResult(False, None, None, None)
    # report the lowest edge whose drop is close to the strongest one (the actual cut frequency)
    max_drop = max(d for _, d in found)
    fc, drop = min((x for x in found if x[1] >= max_drop - 10), key=lambda x: x[0])
    return SpectralResult(True, float(fc), float(drop),
                          f"Posible lossless falso: corte brusco a {fc / 1000:.1f} kHz "
                          f"(cae {drop:.0f} dB y no hay nada por encima). Se queda en el set, marcado.")
