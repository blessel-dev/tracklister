"""Spectral check (numpy only): a lossless file made from an MP3 shows a brick-wall cut.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Averages the magnitude spectrum of ~20 windows spread over the track and looks for a SHARP cut
between 15.5 and 21 kHz: a drop of >= 25 dB within about 1 kHz with nothing above it. A dark mix
(dub techno) with little treble but a smooth roll-off is NOT a cut. Only for lossless containers.

1.0.1 (R6, DECISIONES X): the cut is classified, calibrated with synthetic material in
tests/verify/test_spectral_calibration.py (the table is in DECISIONES):
- STRONG ("probable MP3 convertido"): a cut below STRONG_MAX_HZ, where MP3 at 256 kbps or less cuts
  (128 kbps: 16.5 kHz, 192: 18.5, 256: 19.25 with the suite's encoder). The file keeps its place in
  the set with its number; the verifier gives it its own state, «Verificado · revisar calidad».
- AMBIGUOUS: a cut between STRONG_MAX_HZ and AMBIGUOUS_MAX_HZ, where MP3 320 cuts (20.0 kHz) and so do
  genuine masters low-passed at 20-20.5 kHz (19.75 / 20.25). No mark and no cap: one neutral line.
- NONE: no sharp cut, or one above AMBIGUOUS_MAX_HZ (a master low-passed at 21 kHz, MP3 V0 of the
  suite's encoder). The check never rejects a file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable

import numpy as np
import soundfile as sf

CUT_LOW_HZ, CUT_HIGH_HZ = 15500.0, 21000.0      # detection window (was 15.5-20.5 kHz in 1.0.0)
MIN_DROP_DB = 25.0
BAND_HZ = 250.0
STRONG_MAX_HZ = 19500.0          # calibration: 256 kbps cuts at 19.25 kHz, a 20.0 kHz master at 19.75
STRONG_MIN_DROP_DB = 25.0        # = MIN_DROP_DB: every sharp cut below STRONG_MAX_HZ is strong
AMBIGUOUS_MAX_HZ = 20800.0       # calibration: MP3 320 at 20.0 kHz, a 20.5 kHz master at 20.25, 21.0 -> 21.0

STRONG_FLAG = "probable_mp3_convertido"      # RowResult/LibraryEntry flag of the strong mark (1.0.1)
LEGACY_FLAG = "posible_falso_lossless"       # the 1.0.0 flag: any sharp cut, strong or not

REASON_STRONG_ES = ("Probable MP3 convertido: corte brusco a {khz} kHz (cae {db} dB). Se queda en el set con su "
                    "número; «Reintentar fallos» busca otra copia.")
REASON_AMBIGUOUS_ES = ("Corte a {khz} kHz: habitual tanto en MP3 320 como en másters legítimos; no se puede saber "
                       "solo con el espectro.")
MARK_ES = ("Marca: probable MP3 convertido. Puede sonar igual y tener menos calidad; «Reintentar fallos» "
           "busca otra copia.")


class SpectralClass(StrEnum):
    NONE = "ninguno"
    AMBIGUOUS = "ambiguo"
    STRONG = "probable_mp3"


@dataclass(frozen=True)
class SpectralResult:
    suspicious: bool                 # == (klass is STRONG); kept for old callers
    cutoff_hz: float | None
    drop_db: float | None
    reason_es: str | None
    klass: SpectralClass = SpectralClass.NONE


def khz_es(hz: float) -> str:
    """16250 -> '16,2' (one decimal, decimal comma, as in the report)."""
    return f"{hz / 1000:.1f}".replace(".", ",")


def classify(cutoff_hz: float | None, drop_db: float | None) -> SpectralClass:
    """The class of a sharp cut (pure: the calibration test pins it, also on the user's measurements)."""
    if cutoff_hz is None or drop_db is None or drop_db < MIN_DROP_DB:
        return SpectralClass.NONE
    if cutoff_hz < STRONG_MAX_HZ and drop_db >= STRONG_MIN_DROP_DB:
        return SpectralClass.STRONG
    if cutoff_hz <= AMBIGUOUS_MAX_HZ:
        return SpectralClass.AMBIGUOUS
    return SpectralClass.NONE


def reason_for(klass: SpectralClass, cutoff_hz: float | None, drop_db: float | None) -> str | None:
    if klass == SpectralClass.STRONG:
        return REASON_STRONG_ES.format(khz=khz_es(cutoff_hz), db=f"{drop_db:.0f}")
    if klass == SpectralClass.AMBIGUOUS:
        return REASON_AMBIGUOUS_ES.format(khz=khz_es(cutoff_hz))
    return None


_LEGACY_REASON = re.compile(r"corte brusco a (\d+(?:[.,]\d+)?) kHz \(cae (\d+(?:[.,]\d+)?) dB")


def legacy_cut(reasons: Iterable[str]) -> tuple[float, float] | None:
    """(cutoff Hz, drop dB) written by 1.0.0 in its reason 'Posible lossless falso: corte brusco a 18.8 kHz
    (cae 42 dB ...)', or None. The kHz there were rounded to one decimal."""
    for r in reasons or ():
        m = _LEGACY_REASON.search(r or "")
        if m:
            return float(m.group(1).replace(",", ".")) * 1000.0, float(m.group(2).replace(",", "."))
    return None


def legacy_class(reasons: Iterable[str]) -> SpectralClass | None:
    """The 1.0.1 class of a 1.0.0 spectral mark, from its reason text; None if the text says nothing."""
    cut = legacy_cut(reasons)
    return classify(*cut) if cut else None


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


def find_cut(path: Path, *, windows: int = 20, fft_size: int = 8192) -> tuple[float, float] | None:
    """(cutoff Hz, drop dB) of the sharpest brick-wall cut in the detection window, or None."""
    try:
        res = _average_spectrum(Path(path), windows, fft_size)
    except (RuntimeError, sf.LibsndfileError, OSError, ValueError):
        res = None
    if res is None:
        return None
    power, sr = res
    freqs = np.fft.rfftfreq(fft_size, 1.0 / sr)
    nyq = sr / 2.0
    top = min(nyq - 200.0, 22000.0)
    edges = np.arange(1000.0, top, BAND_HZ)
    if len(edges) < 8:
        return None
    band_db = []
    for lo in edges:
        sel = (freqs >= lo) & (freqs < lo + BAND_HZ)
        band_db.append(10 * np.log10(power[sel].mean() + 1e-20) if np.any(sel) else -200.0)
    band_db = np.array(band_db)
    centers = edges + BAND_HZ / 2
    ref = np.percentile(band_db[(centers > 1000) & (centers < 8000)], 75) if np.any(centers < 8000) else band_db.max()
    if ref < -140:   # silence
        return None
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
        return None
    # report the lowest edge whose drop is close to the strongest one (the actual cut frequency)
    max_drop = max(d for _, d in found)
    fc, drop = min((x for x in found if x[1] >= max_drop - 10), key=lambda x: x[0])
    return float(fc), float(drop)


def fake_lossless_check(path: Path, *, windows: int = 20, fft_size: int = 8192) -> SpectralResult:
    cut = find_cut(path, windows=windows, fft_size=fft_size)
    if cut is None:
        return SpectralResult(False, None, None, None, SpectralClass.NONE)
    fc, drop = cut
    klass = classify(fc, drop)
    return SpectralResult(klass == SpectralClass.STRONG, fc, drop, reason_for(klass, fc, drop), klass)
