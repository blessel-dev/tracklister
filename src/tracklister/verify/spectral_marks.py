"""The spectral marks without the audio libraries: the flags, the classes and the 1.0.0 reason text.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

CL-19: the library index and the report read these marks, and both load when the window opens; the check itself
(verify/spectral.py, with numpy and soundfile) loads the first time a file is checked. verify/spectral.py imports
every name of this module back, so `from tracklister.verify.spectral import X` still works.
"""
from __future__ import annotations

import re
from enum import StrEnum
from typing import Iterable

MIN_DROP_DB = 25.0
STRONG_MAX_HZ = 19500.0          # calibration: 256 kbps cuts at 19.25 kHz, a 20.0 kHz master at 19.75
STRONG_MIN_DROP_DB = 25.0        # = MIN_DROP_DB: every sharp cut below STRONG_MAX_HZ is strong
AMBIGUOUS_MAX_HZ = 20800.0       # calibration: MP3 320 at 20.0 kHz, a 20.5 kHz master at 20.25, 21.0 -> 21.0

STRONG_FLAG = "probable_mp3_convertido"      # RowResult/LibraryEntry flag of the strong mark (1.0.1)
LEGACY_FLAG = "posible_falso_lossless"       # the 1.0.0 flag: any sharp cut, strong or not

MARK_ES = ("Marca: probable MP3 convertido. Puede sonar igual y tener menos calidad; «Reintentar fallos» "
           "busca otra copia.")


class SpectralClass(StrEnum):
    NONE = "ninguno"
    AMBIGUOUS = "ambiguo"
    STRONG = "probable_mp3"


def classify(cutoff_hz: float | None, drop_db: float | None) -> SpectralClass:
    """The class of a sharp cut (pure: the calibration test pins it, also on the user's measurements)."""
    if cutoff_hz is None or drop_db is None or drop_db < MIN_DROP_DB:
        return SpectralClass.NONE
    if cutoff_hz < STRONG_MAX_HZ and drop_db >= STRONG_MIN_DROP_DB:
        return SpectralClass.STRONG
    if cutoff_hz <= AMBIGUOUS_MAX_HZ:
        return SpectralClass.AMBIGUOUS
    return SpectralClass.NONE


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
