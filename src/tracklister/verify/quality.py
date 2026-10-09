"""Does the downloaded file meet the preset? Real container, MP3 CBR >= N kbps, CDJ limits.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

from dataclasses import dataclass, field

from tracklister.engine.presets import AcceptRule
from tracklister.verify.audioinfo import LOSSLESS_CONTAINERS, AudioInfo

_LABEL = {"flac": "FLAC", "wav": "WAV", "aiff": "AIFF", "mp3": "MP3", "m4a": "M4A/AAC", "ogg": "OGG",
          "opus": "Opus", "unknown": "desconocido"}


@dataclass(frozen=True)
class QualityCheck:
    ok: bool
    needs_conversion: bool
    reasons_es: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def check_quality(info: AudioInfo, accept: AcceptRule, *, lossy_allowed: bool) -> QualityCheck:
    reasons: list[str] = []
    flags: list[str] = []
    c = info.container
    if not info.ext_matches and c != "unknown":
        flags.append("extension_distinta")
        reasons.append(f"El archivo se llama {info.path.suffix or '(sin extensión)'} pero por dentro es "
                       f"{_LABEL.get(c, c)}.")
    if c == "unknown" or (info.decoded_duration_s is None and c != "m4a"):
        return QualityCheck(False, False, reasons + ["No se puede leer el audio del archivo (formato "
                                                     "desconocido o archivo dañado)."], flags + ["ilegible"])
    if c == "mp3":
        if not lossy_allowed or accept.mp3_min_kbps is None:
            return QualityCheck(False, False, reasons + ["Es un MP3 y este preset pide lossless."],
                                flags + ["mp3_no_permitido"])
        mode = info.bitrate_mode or "unknown"
        if mode in ("vbr", "abr"):
            return QualityCheck(False, False, reasons + [
                f"MP3 {mode.upper()} (unos {info.bitrate_kbps or '?'} kbps): solo vale MP3 CBR de "
                f"{accept.mp3_min_kbps} kbps o más."], flags + ["mp3_vbr"])
        if (info.bitrate_kbps or 0) < accept.mp3_min_kbps:
            return QualityCheck(False, False, reasons + [
                f"MP3 de {info.bitrate_kbps or '?'} kbps: se pide {accept.mp3_min_kbps} kbps o más."],
                flags + ["mp3_bajo_bitrate"])
        if mode == "unknown":
            flags.append("mp3_modo_desconocido")
        return QualityCheck(True, False, reasons, flags)
    if c not in LOSSLESS_CONTAINERS:
        return QualityCheck(False, False, reasons + [f"Formato {_LABEL.get(c, c)} no permitido en este preset."],
                            flags + ["formato_no_permitido"])
    if c not in accept.containers and c not in accept.convert_to_aiff:
        return QualityCheck(False, False, reasons + [f"Formato {_LABEL[c]} no permitido en este preset."],
                            flags + ["formato_no_permitido"])
    needs = c in accept.convert_to_aiff
    over_sr = bool(accept.max_samplerate and (info.samplerate or 0) > accept.max_samplerate)
    over_bd = bool(accept.max_bitdepth and (info.bitdepth or 0) > accept.max_bitdepth)
    if accept.converts:
        if over_sr or over_bd or info.is_aifc or info.is_float:
            needs = True
            if over_sr or over_bd:
                flags.append("reducido_48k_24b")
                reasons.append(f"{info.samplerate or '?'} Hz / {info.bitdepth or '?'} bits: se baja a como mucho "
                               f"{accept.max_samplerate} Hz / {accept.max_bitdepth} bits para CDJ antiguos.")
            if info.is_aifc or info.is_float:
                flags.append("aiff_c_o_float")
                reasons.append("AIFF-C o coma flotante: se convierte a AIFF PCM para CDJ antiguos.")
        return QualityCheck(True, needs, reasons, flags)
    if over_sr or over_bd:
        return QualityCheck(False, False, reasons + [
            f"{info.samplerate or '?'} Hz / {info.bitdepth or '?'} bits supera el máximo elegido "
            f"({accept.max_samplerate or '-'} Hz / {accept.max_bitdepth or '-'} bits)."], flags + ["supera_maximo"])
    return QualityCheck(True, needs, reasons, flags)
