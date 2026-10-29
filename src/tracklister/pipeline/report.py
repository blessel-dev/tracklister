"""Per-set results report and the 'Copiar tracklist' text (Spanish, plain text).

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

from collections import Counter

from tracklister.core.layout import DUDOSOS, ORIGINALES
from tracklister.core.model import DoubtKind, ResultState, RowResult, SetDoc, TrackRow
from tracklister.organize.naming import pad_width
from tracklister.verify.spectral import LEGACY_FLAG, MARK_ES, STRONG_FLAG, SpectralClass, legacy_class

STATE_ES = {
    ResultState.PENDIENTE: "Pendiente", ResultState.EN_CURSO: "En curso", ResultState.VERIFICADO: "Verificado",
    ResultState.REVISAR_CALIDAD: "Verificado \u00b7 revisar calidad",
    ResultState.DUDOSO: "Dudoso", ResultState.NO_ENCONTRADO: "No encontrado",
    ResultState.NO_CUMPLE_FORMATO: "No cumple formato", ResultState.FALLIDA: "Fallida",
    ResultState.YA_EN_BIBLIOTECA: "Ya en biblioteca", ResultState.OMITIDA: "Omitida",
}
STRAY_TITLE_ES = ("Archivos de la carpeta que ya no son de ninguna pista de la tabla (filas borradas o intentos "
                  "anteriores; no se ha borrado ninguno):")
DOUBT_ES = {
    DoubtKind.IDENTIDAD: f"otra canción (en {DUDOSOS})", DoubtKind.VERSION: f"otra versión (en {DUDOSOS})",
    DoubtKind.DURACION: f"duración que no cuadra (en {DUDOSOS})",
    # only in sets of 1.0.0 that 1.0.1 has not checked again yet (pipeline.session._upgrade_results)
    DoubtKind.ESPECTRO: "marca de espectro de la versión 1.0.0 (se queda en el set)",
    DoubtKind.REVISAR: "revisar (se queda en el set)",
}
# the order of the summary line: «Verificado · revisar calidad» right after «Verificado», apart from «Dudoso»
SUMMARY_ORDER = [ResultState.VERIFICADO, ResultState.REVISAR_CALIDAD, ResultState.YA_EN_BIBLIOTECA,
                 ResultState.DUDOSO, ResultState.NO_ENCONTRADO, ResultState.NO_CUMPLE_FORMATO, ResultState.FALLIDA,
                 ResultState.OMITIDA, ResultState.PENDIENTE, ResultState.EN_CURSO]


def has_quality_mark(res: RowResult) -> bool:
    """The file carries the strong spectral mark ("probable MP3 convertido"). A 1.0.0 mark counts unless its
    own text shows a cut that 1.0.1 no longer marks (~19.5-20.8 kHz: also genuine masters)."""
    if STRONG_FLAG in res.flags:
        return True
    if LEGACY_FLAG in res.flags:
        return legacy_class(res.reasons) in (None, SpectralClass.STRONG)
    return False


def fmt_time(s: int | None) -> str:
    if s is None:
        return ""
    s = int(s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def row_label(row: TrackRow) -> str:
    who = row.artist_display or row.search_artist
    title = row.title_with_version or ("ID" if row.is_id else "")
    return f"{who} - {title}" if who else title


def tracklist_text(doc: SetDoc) -> str:
    """'01. 00:00 Artista - Titulo (Version) [Sello]'; the time is omitted when unknown."""
    width = pad_width(len(doc.rows))           # the same NN width as the file names (CL-31)
    lines = []
    for r in sorted(doc.rows, key=lambda x: x.pos):
        t = fmt_time(r.ts_start)
        label = f" [{r.label}]" if r.label else ""
        lines.append(f"{r.pos:0{width}d}. " + (f"{t} " if t else "") + row_label(r) + label)
    return "\n".join(lines) + "\n"


def report_text(doc: SetDoc, *, preset_label: str, engine_id: str | None = None,
                stray_files: list[str] | None = None) -> str:
    """`stray_files`: audio files of the folder that belong to no current row (organize.finalize)."""
    rows = sorted(doc.rows, key=lambda x: x.pos)
    width = pad_width(len(rows))               # the same NN width as the file names (CL-31)
    counts = Counter(doc.results[r.uid].state for r in rows if r.uid in doc.results)
    out = [f"Informe de Tracklister - {doc.name}", "",
           f"Preset: {preset_label}" + (f"   Motor: {engine_id}" if engine_id else ""),
           f"Actualizado: {doc.updated_at or '-'}", ""]
    out.append("Resumen: " + ", ".join(f"{STATE_ES[s].lower()} {counts[s]}" for s in SUMMARY_ORDER if counts.get(s)))
    out.append("")
    for r in rows:
        res = doc.results.get(r.uid)
        state = res.state if res else ResultState.PENDIENTE
        head = f"{r.pos:0{width}d}. {row_label(r)}  [{STATE_ES[state]}"
        if res and res.doubt:
            head += f": {DOUBT_ES[res.doubt]}"
        if res and res.score is not None and state in (ResultState.VERIFICADO, ResultState.REVISAR_CALIDAD,
                                                       ResultState.DUDOSO):
            head += f", confianza {res.score}/100"
        out.append(head + "]")
        if res:
            if res.file:
                out.append(f"    Archivo: {res.file}")
            if res.original_file:
                out.append(f"    Original: {res.original_file}")
            for reason in res.reasons:
                out.append(f"    - {reason}")
            if has_quality_mark(res):
                out.append(f"    ! {MARK_ES}")
    if stray_files:
        out += ["", STRAY_TITLE_ES]
        out += [f"    {f}" for f in stray_files]
    out += ["", f"Las dudas de identidad, versión o duración están en la carpeta {DUDOSOS}.",
            f"Los FLAC originales convertidos para CDJ antiguos están en {ORIGINALES}."]
    return "\n".join(out) + "\n"
