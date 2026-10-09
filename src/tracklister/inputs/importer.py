"""One entry point for every input: a dropped file, a pasted link or a pasted text.

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

import_source() never raises for user input problems: it returns rows=[] and a Spanish
status-bar message that says what happened and what to do (02 section 4, principle 2).
Every source goes through inputs.clean.clean_rows before it reaches the review table.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from tracklister import config
from tracklister.core.model import RowStatus, SourceRef, TrackRow
from tracklister.inputs.clean import clean_rows
from tracklister.inputs.detect import InputKind, as_path, detect, normalize_url
from tracklister.inputs.mapping import ColumnMapping, guess_mapping, refine_mapping, rows_from_table
from tracklister.inputs.tabular import RawTable, TableError, decode_bytes, read_table
from tracklister.inputs.text import parse_pasted_text
from tracklister.inputs.trackid import GAP_TITLE, parse_trackid

if TYPE_CHECKING:
    from tracklister.inputs.online import CandidateView
    from tracklister.inputs.ytdlp import YtDlp

log = logging.getLogger(__name__)

MSG_TRACKID_URL = ("trackid.net no permite la lectura automática: abre la página del set, pulsa Export "
                   "y arrastra aquí el CSV.")
MSG_PASTE_ONLY = ("{site} no permite la lectura automática: abre la página, copia la tracklist "
                  "(Ctrl+A, Ctrl+C) y pégala aquí.")
MSG_OTHER_URL = ("No sé leer ese enlace. Pega un enlace de YouTube o SoundCloud, arrastra el CSV de "
                 "trackid.net o copia la tracklist y pégala aquí.")
MSG_NO_YTDLP = ("yt-dlp no está disponible, así que no puedo leer {site}. Actualiza yt-dlp en Ajustes "
                "o vuelve a descomprimir Tracklister; mientras tanto, copia la tracklist y pégala aquí.")
MSG_NO_TEXT_ROWS = ("No he encontrado pistas en el texto. Cada línea debe tener 'Artista - Título', "
                    "con o sin tiempo delante (00:00).")
SITE_NAMES = {"1001tracklists.com": "1001tracklists", "mixesdb.com": "MixesDB"}


@dataclass
class ImportResult:
    kind: InputKind
    rows: list[TrackRow]
    sources: list[SourceRef]
    message_es: str                       # status-bar text, incl. what to do on failure
    warnings_es: list[str] = field(default_factory=list)
    candidates: list["CandidateView"] = field(default_factory=list)   # YouTube/SoundCloud only
    chosen: int | None = None
    suggested_name: str | None = None     # set name (CSV file stem / video title)
    links: list[str] = field(default_factory=list)   # pages to offer with "Abrir enlace"


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def summary_es(rows: list[TrackRow]) -> str:
    """'17 pistas, 4 filas ID (sin descargar), 1 por revisar'."""
    real = [r for r in rows if not r.is_id]
    ids = len(rows) - len(real)
    review = sum(1 for r in real if r.status == RowStatus.REVISAR)
    parts = [f"{len(real)} pista" + ("" if len(real) == 1 else "s")]
    if ids:
        parts.append(f"{ids} fila{'' if ids == 1 else 's'} ID (sin descargar)")
    if review:
        parts.append(f"{review} por revisar")
    return ", ".join(parts)


def duplicate_warnings(rows: list[TrackRow]) -> list[str]:
    out = []
    for r in rows:
        for n in r.notes:
            if n.startswith("repetida (fila "):
                out.append(f"La fila {r.pos} ({r.artist_display} - {r.title}) está {n}.")
    return out


def _result(kind: InputKind, raw_rows: list[TrackRow], source: SourceRef, message: str, *,
            warnings: list[str] | None = None, name: str | None = None) -> ImportResult:
    """Clean the rows; '{summary}' in the message becomes summary_es(cleaned rows)."""
    rows = clean_rows(raw_rows)
    warns = list(warnings or []) + duplicate_warnings(rows)
    return ImportResult(kind=kind, rows=rows, sources=[source] if rows else [],
                        message_es=message.replace("{summary}", summary_es(rows)), warnings_es=warns,
                        suggested_name=name)


def _fail(kind: InputKind, message: str, *, links: list[str] | None = None) -> ImportResult:
    return ImportResult(kind=kind, rows=[], sources=[], message_es=message, links=list(links or []))


# ---------------------------------------------------------------- files


def _headerless(t: RawTable) -> tuple[RawTable, ColumnMapping, str]:
    width = max(len(t.headers), *(len(r) for r in t.rows)) if t.rows else len(t.headers)
    rows = [t.headers + [""] * (width - len(t.headers))] + [r + [""] * (width - len(r)) for r in t.rows]
    t2 = RawTable(headers=[f"col{i + 1}" for i in range(width)], rows=rows, encoding=t.encoding,
                  delimiter=t.delimiter, sheet=t.sheet)
    if width >= 2:
        return t2, ColumnMapping(artist=0, title=1), ("No encontré los nombres de las columnas: uso la 1.ª "
                                                      "como artista y la 2.ª como título. Revísalo.")
    return t2, ColumnMapping(artist=None, title=None, combined=0), ""


def _import_table(path: Path, kind: InputKind, gap_threshold_s: int) -> ImportResult:
    t = read_table(path)
    ref = SourceRef(kind=str(kind), ref=path.name, imported_at=now_iso())
    if kind == InputKind.TRACKID_CSV:
        rows = parse_trackid(t, gap_threshold_s=gap_threshold_s)
        gaps = sum(1 for r in rows if r.title == GAP_TITLE)
        ref.detail = f"trackid.net CSV ({len(rows) - gaps} pistas, {gaps} huecos)"
        if not rows:
            return _fail(kind, f"{path.name} tiene las columnas de trackid.net pero ninguna pista.")
        return _result(kind, rows, ref, "trackid.net: {summary}. Revisa la tabla antes de descargar.",
                       name=path.stem)
    warnings = []
    m = refine_mapping(t, guess_mapping(t.headers))
    if not m.is_usable():
        t, m, warn = _headerless(t)
        if warn:
            warnings.append(warn)
    rows = rows_from_table(t, m)
    ref.detail = f"tabla{' hoja ' + t.sheet if t.sheet else ''} ({len(rows)} filas)"
    if not rows:
        return _fail(kind, f"{path.name} no tiene pistas. Pon una columna 'Artista' y otra 'Título'.")
    return _result(kind, rows, ref, path.name + ": {summary}. Revisa la tabla antes de descargar.",
                   warnings=warnings, name=path.stem)


def _import_text_file(path: Path) -> ImportResult:
    text, _ = decode_bytes(path.read_bytes())
    rows = parse_pasted_text(text)
    if not rows:
        return _fail(InputKind.TEXT, f"{path.name}: " + MSG_NO_TEXT_ROWS)
    ref = SourceRef(kind=str(InputKind.TEXT), ref=path.name, detail=f"texto ({len(rows)} filas)",
                    imported_at=now_iso())
    return _result(InputKind.TEXT, rows, ref, path.name + ": {summary}.", name=path.stem)


def _import_file(path: Path, kind: InputKind, gap_threshold_s: int) -> ImportResult:
    if path.is_dir():
        return _fail(kind, f"'{path.name}' es una carpeta. Para ordenar una carpeta descargada con la "
                           "herramienta antigua usa 'Reordenar carpeta existente'.")
    if not path.is_file():
        return _fail(kind, f"No encuentro el archivo {path.name}.")
    try:
        if kind == InputKind.TEXT:
            return _import_text_file(path)
        return _import_table(path, kind, gap_threshold_s)
    except TableError as e:
        return _fail(kind, str(e))
    except OSError as e:
        return _fail(kind, f"No se pudo leer {path.name}: {e.strerror or e}.")


# ---------------------------------------------------------------- links and text


def _import_online(url: str, kind: InputKind, ytdlp: "YtDlp | None") -> ImportResult:
    site = "YouTube" if kind == InputKind.YOUTUBE else "SoundCloud"
    if ytdlp is None or not ytdlp.available():
        return _fail(kind, MSG_NO_YTDLP.format(site=site))
    from tracklister.inputs.online import import_from_url   # needs yt-dlp; loaded on demand
    return import_from_url(url, ytdlp)


def _import_text(text: str) -> ImportResult:
    rows = parse_pasted_text(text)
    if not rows:
        return _fail(InputKind.TEXT, MSG_NO_TEXT_ROWS)
    ref = SourceRef(kind=str(InputKind.TEXT), ref="texto", detail=f"texto pegado ({len(rows)} filas)",
                    imported_at=now_iso())
    timed = sum(1 for r in rows if r.ts_start is not None)
    extra = f" ({timed} con tiempo)" if timed else ""
    return _result(InputKind.TEXT, rows, ref, "Texto: {summary}" + extra + ".")


def import_source(source: str | Path, *, ytdlp: "YtDlp | None" = None, gap_threshold_s: int = 90) -> ImportResult:
    try:
        kind = detect(source)
        path = as_path(source)
        if path is not None:
            return _import_file(path, kind, gap_threshold_s)
        url = normalize_url(str(source))
        if kind in (InputKind.YOUTUBE, InputKind.SOUNDCLOUD):
            return _import_online(url, kind, ytdlp)
        if kind == InputKind.TRACKID_URL:
            return _fail(kind, MSG_TRACKID_URL, links=[url or config.TRACKID_URL])
        if kind == InputKind.PASTE_ONLY_URL:
            site = next((v for k, v in SITE_NAMES.items() if k in (url or "")), "Esa web")
            return _fail(kind, MSG_PASTE_ONLY.format(site=site), links=[url] if url else [])
        if kind == InputKind.OTHER_URL:
            return _fail(kind, MSG_OTHER_URL)
        return _import_text(str(source))
    except Exception as e:  # a bug must not take the window down; the log keeps the traceback
        log.exception("import_source failed")
        return _fail(InputKind.TEXT, f"No se pudo importar: {e}. Prueba a copiar la tracklist y pegarla aquí.")
