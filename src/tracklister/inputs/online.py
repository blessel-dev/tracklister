"""A YouTube or SoundCloud link -> the best tracklist among description, chapters and comments.

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

02 section 4 "Flujo de la ventana": show the chosen candidate, e.g. "Comentario de @travo1001 ·
22 pistas con tiempos · 11 likes", with a list to switch to another one. When the description
links an external tracklist, offer to open it and paste the text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from tracklister.core.model import SourceRef, TrackRow
from tracklister.inputs.clean import clean_rows
from tracklister.inputs.detect import InputKind, url_kind
from tracklister.inputs.importer import ImportResult, duplicate_warnings, now_iso, summary_es
from tracklister.inputs.tlparse import to_track_rows
from tracklister.inputs.tlselect import Candidate, choose, merge
from tracklister.inputs.ytdlp import YtDlp, YtDlpError, site_of

MIN_ROWS = 3
_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_TRACKLIST_WORD = re.compile(r"(?i)track\s?list|setlist|track\s?ids?\b")
_TRACKLIST_SITES = ("1001tracklists.com", "mixesdb.com", "trackid.net")


@dataclass
class CandidateView:
    """One entry of the "which tracklist?" list. Switching to it = use its `rows` and `source_ref`."""
    label_es: str
    n_rows: int
    has_times: bool
    likes: int
    source: str = ""                       # TrackRow.source of its rows, e.g. "youtube_comment:@x"
    score: float = 0.0
    rows: list[TrackRow] = field(default_factory=list)
    source_ref: SourceRef | None = None


def row_source(kind: InputKind, c: Candidate) -> str:
    prefix = "soundcloud" if kind == InputKind.SOUNDCLOUD else "youtube"
    if c.source == "comment":
        return f"{prefix}_comment:{c.author or '?'}"
    return f"{prefix}_{'chapters' if c.source == 'chapters' else 'description'}"


def label_es(c: Candidate, rows: list[TrackRow], has_times: bool) -> str:
    if c.source == "comment":
        head = f"Comentario de {c.author or 'alguien'}" + (" (fijado)" if c.pinned else "")
    elif c.source == "chapters":
        head = "Capítulos del vídeo"
    else:
        head = "Descripción"
    n = len(rows)
    parts = [head, f"{n} pista{'' if n == 1 else 's'} {'con' if has_times else 'sin'} tiempos"]
    if c.likes:
        parts.append(f"{c.likes} like{'' if c.likes == 1 else 's'}")
    return " · ".join(parts)


def external_tracklist_links(description: str | None) -> list[str]:
    """Links in the description that point to a tracklist ("Read the tracklist here: https://...")."""
    out: list[str] = []
    for line in (description or "").splitlines():
        prev_end = 0
        for m in _URL_IN_TEXT.finditer(line):
            url = m.group(0).rstrip(".,;:!")
            context = line[prev_end:m.start()]            # the words just before this link
            prev_end = m.end()
            if (_TRACKLIST_WORD.search(context) or any(s in url.lower() for s in _TRACKLIST_SITES)) \
                    and url not in out:
                out.append(url)
    return out


def result_from_meta(meta: dict, url: str) -> ImportResult:
    kind = url_kind(url)
    if kind not in (InputKind.YOUTUBE, InputKind.SOUNDCLOUD):
        kind = InputKind.YOUTUBE
    site = site_of(url)
    page = meta.get("webpage_url") or url
    best, ranked, merged = choose(meta, min_rows=MIN_ROWS)
    multi = [c for c in ranked if c.strong >= MIN_ROWS]
    views: list[CandidateView] = []
    for c in multi:
        lines = merged if c is best else merge(c, [o for o in multi if o is not c])
        src = row_source(kind, c)
        rows = clean_rows(to_track_rows(lines, src, page))
        timed = sum(1 for r in rows if r.ts_start is not None) >= 0.7 * max(1, len(rows))
        ref = SourceRef(kind=str(kind), ref=page, detail=f"{src} ({len(rows)} pistas)", imported_at=now_iso())
        views.append(CandidateView(label_es=label_es(c, rows, timed), n_rows=len(rows), has_times=timed,
                                   likes=c.likes, source=src, score=round(c.score, 2), rows=rows, source_ref=ref))
    links = external_tracklist_links(meta.get("description"))
    name = meta.get("title") or None
    if best is None:
        msg = f"No he encontrado una tracklist en la descripción ni en los comentarios de {site}."
        if links:
            msg += " La descripción enlaza una tracklist: ábrela, cópiala y pégala aquí."
        elif views:
            msg += f" Hay {len(views)} lista{'s' if len(views) > 1 else ''} dudosa{'s' if len(views) > 1 else ''}: " \
                   "elige una en el desplegable o pega la tracklist aquí."
        else:
            msg += " Si la conoces, cópiala y pégala aquí."
        return ImportResult(kind=kind, rows=[], sources=[], message_es=msg, candidates=views, chosen=None,
                            suggested_name=name, links=links)
    chosen = views[0]
    msg = f"{site}: {chosen.label_es} ({summary_es(chosen.rows)}). Revisa la tabla antes de descargar."
    if len(views) > 1:
        msg += f" Hay {len(views) - 1} alternativa{'s' if len(views) > 2 else ''} en el desplegable."
    return ImportResult(kind=kind, rows=chosen.rows, sources=[chosen.source_ref], message_es=msg,
                        warnings_es=duplicate_warnings(chosen.rows), candidates=views, chosen=0,
                        suggested_name=name, links=links)


def import_from_url(url: str, ytdlp: YtDlp) -> ImportResult:
    kind = url_kind(url)
    try:
        meta = ytdlp.fetch_meta(url)
    except YtDlpError as e:
        return ImportResult(kind=kind, rows=[], sources=[], message_es=str(e))
    return result_from_meta(meta, url)
