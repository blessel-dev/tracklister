"""Verdict for one downloaded file against its row (brief section 8; DECISIONES C.4 and C.5).

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Fixed rules, in order:
1. quality check fails                                  -> NO_CUMPLE_FORMATO (not placed in the set)
2. truncated (decoded > 2 s shorter than the header)    -> DUDOSO/DURACION, flag "truncado"
3. artist < 60, another artist with a similar name, or title < 70
                                                        -> DUDOSO/IDENTIDAD (a title with other numbers,
   "Dust 1" / "Dust 2", or with a word more or less, "Feel It" / "Feel It All", is capped at 50; a
   partial artist only counts with 2+ words; the artist must match word by word, so 'Adam Port' is not
   'Adam Beyer' and 'Ken Faki' is not 'Len Faki': identity.py)
3b. the name only fits after leaving words out or cutting without ' - ' (IdentityScore.unconfirmed_es),
   and neither the artist+title tags nor a duration within duration_ok_s confirm it
                                                        -> DUDOSO/IDENTIDAD, flag "nombre_sin_confirmar"
   (1.0.1, Addendum 10: 'underworld_-_born_slippy-nuxx' is «Born Slippy» only without 'nuxx')
4. versions_compatible() is False                      -> DUDOSO/VERSION
5. |duration - expected| > duration_review_s            -> DUDOSO/DURACION
6. score = round(0.35*artist + 0.45*title + 20*d): >= 80 VERIFICADO, 50-79 DUDOSO/REVISAR,
   < 50 DUDOSO/IDENTIDAD (d = 1 / 0.5 / 0.75 without an expected duration)
7. spectrum, on VERIFICADO/REVISAR lossless files only (1.0.1, R6; verify.spectral):
   - STRONG ("probable MP3 convertido"): VERIFICADO becomes REVISAR_CALIDAD («Verificado · revisar
     calidad»), with doubt None and the same score (it measures identity); a REVISAR file stays REVISAR.
     Both get the flag "probable_mp3_convertido" and the reason. The file stays in the set with its
     number (A.4): only identity doubts go to _dudosos.
   - AMBIGUOUS (a cut at ~19.5-20.8 kHz): no mark, no cap and no state change; one neutral line.
Every failed check adds its Spanish reason; the doubt kind is the first rule that fired.
A DUDOSO verdict never carries a score at or above the acceptance threshold: rules 2-5 (and 3b) cap it
at 49 (DECISIONES N.6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tracklister.core.model import DoubtKind, ResultState, TrackRow
from tracklister.engine.presets import AcceptRule
from tracklister.verify.audioinfo import AudioInfo, probe
from tracklister.verify.identity import ARTIST_MIN, TITLE_MIN, duration_confirms, identity_score
from tracklister.verify.quality import check_quality
from tracklister.verify.spectral import STRONG_FLAG, SpectralClass, SpectralResult, fake_lossless_check

TRUNCATION_TOLERANCE_S = 2.0
ACCEPT_SCORE, REVIEW_SCORE = 80, 50
HARD_DOUBT_MAX_SCORE = REVIEW_SCORE - 1       # rules 2-5: capped at 49, never inside the 50-79 band
UNCONFIRMED_FLAG = "nombre_sin_confirmar"     # Addendum 10 (rule 3b)
UNCONFIRMED_ES = "{why}: puede ser otra canción u otra versión, y ni las etiquetas ni la duración lo confirman."
__all__ = ["ACCEPT_SCORE", "ARTIST_MIN", "HARD_DOUBT_MAX_SCORE", "REVIEW_SCORE", "TITLE_MIN", "UNCONFIRMED_ES",
           "UNCONFIRMED_FLAG", "Verdict", "verify_file"]


@dataclass(frozen=True)
class Verdict:
    state: ResultState
    doubt: DoubtKind | None
    score: int
    reasons_es: list[str]
    flags: list[str]
    info: AudioInfo
    needs_conversion: bool = False
    identity: object | None = field(default=None, compare=False)
    spectral: SpectralResult | None = field(default=None, compare=False)   # None = not analysed


def _fmt_s(x: float | None) -> str:
    return "?" if x is None else f"{x:.0f}"


def verify_file(row: TrackRow, path: Path, accept: AcceptRule, *, lossy_allowed: bool,
                source_path_tail: str | None, duration_ok_s: int = 3, duration_review_s: int = 10,
                spectral: bool = True) -> Verdict:
    info = probe(Path(path))
    reasons: list[str] = []
    flags: list[str] = []
    q = check_quality(info, accept, lossy_allowed=lossy_allowed)
    flags += q.flags
    if not q.ok:
        return Verdict(ResultState.NO_CUMPLE_FORMATO, None, 0, list(q.reasons_es), flags, info)
    reasons += q.reasons_es

    doubt: DoubtKind | None = None
    ident = identity_score(row, info, source_path_tail)
    if not info.has_tags:
        flags.append("sin_tags")
        reasons.append("Sin etiquetas: identificado por el nombre del archivo.")

    hdr, dec = info.duration_s, info.decoded_duration_s
    if hdr is not None and dec is not None and hdr - dec > TRUNCATION_TOLERANCE_S:
        flags.append("truncado")
        reasons.append(f"Archivo incompleto: se puede escuchar {_fmt_s(dec)} s pero su cabecera dice "
                       f"{_fmt_s(hdr)} s.")
        doubt = doubt or DoubtKind.DURACION

    duration = dec if dec is not None else hdr
    expected = row.expected_duration_s
    if ident.artist < ARTIST_MIN or not ident.same_artist or ident.title < TITLE_MIN:
        if ident.artist < ARTIST_MIN:
            reasons.append(f"Otro artista: '{ident.got_artist or '?'}' (se buscaba '{row.artist_display}', "
                           f"coincide {ident.artist:.0f}%).")
        elif not ident.same_artist:
            reasons.append(f"Otro artista: '{ident.got_artist or '?'}' no es '{row.artist_display}' (el nombre "
                           f"se parece un {ident.artist:.0f}%, pero no coincide palabra por palabra).")
        if ident.title < TITLE_MIN and not ident.numbers_ok:
            reasons.append(f"Otro título: '{ident.got_title or '?'}' no lleva los mismos números que "
                           f"'{row.title}', así que es otra pista.")
        elif ident.title < TITLE_MIN and not ident.title_words_ok:
            reasons.append(f"Otro título: '{ident.got_title or '?'}' no tiene las mismas palabras que "
                           f"'{row.title}', así que es otra pista.")
        elif ident.title < TITLE_MIN:
            reasons.append(f"Otro título: '{ident.got_title or '?'}' (se buscaba '{row.title}', "
                           f"coincide {ident.title:.0f}%).")
        doubt = doubt or DoubtKind.IDENTIDAD
    elif ident.unconfirmed_es and not duration_confirms(expected, duration, duration_ok_s):
        # Addendum 10: the name only fits after leaving words out (or cutting without ' - '), and neither the
        # artist and title tags nor a duration within duration_ok_s confirm it
        why = ident.unconfirmed_es
        reasons.append(UNCONFIRMED_ES.format(why=why[:1].upper() + why[1:]))
        flags.append(UNCONFIRMED_FLAG)
        doubt = doubt or DoubtKind.IDENTIDAD

    if not ident.version_ok:
        reasons.append(f"Otra versión: {ident.version_reason_es}.")
        doubt = doubt or DoubtKind.VERSION

    if expected and duration is not None:
        diff = abs(duration - expected)
        if diff <= duration_ok_s:
            d = 1.0
        elif diff <= duration_review_s:
            d = 0.5
            reasons.append(f"Duración {_fmt_s(duration)} s; se esperaban {expected} s ({diff:.0f} s de diferencia).")
        else:
            d = 0.0
            reasons.append(f"Duración {_fmt_s(duration)} s; se esperaban {expected} s ({diff:.0f} s de diferencia): "
                           "puede ser otra versión (radio edit, extended...).")
            doubt = doubt or DoubtKind.DURACION
    else:
        d = 0.75
        flags.append("sin_duracion_esperada")
        reasons.append("Sin duración esperada: no se pudo comprobar la duración.")

    score = int(round(0.35 * ident.artist + 0.45 * ident.title + 20 * d))
    if doubt is not None:
        # A hard doubt (other song, other version, duration, truncated) never shows a high confidence:
        # the score is capped below the "revisar" band (DECISIONES N.6).
        score = min(score, HARD_DOUBT_MAX_SCORE)
        return Verdict(ResultState.DUDOSO, doubt, score, reasons, flags, info, q.needs_conversion, ident)
    if score >= ACCEPT_SCORE:
        state, doubt = ResultState.VERIFICADO, None
    elif score >= REVIEW_SCORE:
        state, doubt = ResultState.DUDOSO, DoubtKind.REVISAR
        reasons.append(f"Confianza {score}/100: revísalo (se queda en el set).")
    else:
        state, doubt = ResultState.DUDOSO, DoubtKind.IDENTIDAD
        reasons.append(f"Confianza {score}/100: probablemente no es la canción pedida.")
    sp: SpectralResult | None = None
    if spectral and info.is_lossless and doubt in (None, DoubtKind.REVISAR):
        sp = fake_lossless_check(info.path)
        if sp.klass == SpectralClass.STRONG:
            # a quality mark, not an identity doubt: the identity score stays (plan D2)
            if state == ResultState.VERIFICADO:
                state = ResultState.REVISAR_CALIDAD
            flags.append(STRONG_FLAG)
            reasons.append(sp.reason_es or "Probable MP3 convertido.")
        elif sp.klass == SpectralClass.AMBIGUOUS and sp.reason_es:
            reasons.append(sp.reason_es)
    return Verdict(state, doubt, score, reasons, flags, info, q.needs_conversion, ident, sp)
