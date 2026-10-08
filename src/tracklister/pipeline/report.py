"""Per-set results report and the 'Copiar tracklist' text (Spanish, plain text).

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

from collections import Counter

from tracklister.core.layout import DUDOSOS, ORIGINALES
from tracklister.core.model import DoubtKind, ResultState, SetDoc, TrackRow

STATE_ES = {
    ResultState.PENDIENTE: "Pendiente", ResultState.EN_CURSO: "En curso", ResultState.VERIFICADO: "Verificado",
    ResultState.DUDOSO: "Dudoso", ResultState.NO_ENCONTRADO: "No encontrado",
    ResultState.NO_CUMPLE_FORMATO: "No cumple formato", ResultState.FALLIDA: "Fallida",
    ResultState.YA_EN_BIBLIOTECA: "Ya en biblioteca", ResultState.OMITIDA: "Omitida",
}
DOUBT_ES = {
    DoubtKind.IDENTIDAD: f"otra cancion (en {DUDOSOS})", DoubtKind.VERSION: f"otra version (en {DUDOSOS})",
    DoubtKind.DURACION: f"duracion que no cuadra (en {DUDOSOS})",
    DoubtKind.ESPECTRO: "posible lossless falso (se queda en el set)",
    DoubtKind.REVISAR: "revisar (se queda en el set)",
}


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
    width = 3 if len(doc.rows) > 99 else 2
    lines = []
    for r in sorted(doc.rows, key=lambda x: x.pos):
        t = fmt_time(r.ts_start)
        label = f" [{r.label}]" if r.label else ""
        lines.append(f"{r.pos:0{width}d}. " + (f"{t} " if t else "") + row_label(r) + label)
    return "\n".join(lines) + "\n"


def report_text(doc: SetDoc, *, preset_label: str, engine_id: str | None = None) -> str:
    rows = sorted(doc.rows, key=lambda x: x.pos)
    width = 3 if len(rows) > 99 else 2
    counts = Counter(doc.results[r.uid].state for r in rows if r.uid in doc.results)
    out = [f"Informe de Tracklister - {doc.name}", "",
           f"Preset: {preset_label}" + (f"   Motor: {engine_id}" if engine_id else ""),
           f"Actualizado: {doc.updated_at or '-'}", ""]
    order = [ResultState.VERIFICADO, ResultState.YA_EN_BIBLIOTECA, ResultState.DUDOSO, ResultState.NO_ENCONTRADO,
             ResultState.NO_CUMPLE_FORMATO, ResultState.FALLIDA, ResultState.OMITIDA, ResultState.PENDIENTE,
             ResultState.EN_CURSO]
    out.append("Resumen: " + ", ".join(f"{STATE_ES[s].lower()} {counts[s]}" for s in order if counts.get(s)))
    out.append("")
    for r in rows:
        res = doc.results.get(r.uid)
        state = res.state if res else ResultState.PENDIENTE
        head = f"{r.pos:0{width}d}. {row_label(r)}  [{STATE_ES[state]}"
        if res and res.doubt:
            head += f": {DOUBT_ES[res.doubt]}"
        if res and res.score is not None and state in (ResultState.VERIFICADO, ResultState.DUDOSO):
            head += f", confianza {res.score}/100"
        out.append(head + "]")
        if res:
            if res.file:
                out.append(f"    Archivo: {res.file}")
            if res.original_file:
                out.append(f"    Original: {res.original_file}")
            for reason in res.reasons:
                out.append(f"    - {reason}")
            if "posible_falso_lossless" in res.flags:
                out.append("    ! Marca: posible lossless falso. Escuchalo antes de pincharlo.")
    out += ["", f"Las dudas de identidad, version o duracion estan en la carpeta {DUDOSOS}.",
            f"Los FLAC originales convertidos para CDJ antiguos estan en {ORIGINALES}."]
    return "\n".join(out) + "\n"
