"""Fixed names inside a set folder. Owner: core (frozen during the parallel phase).

<library_root>/<set name>/
    01 - Artista - Titulo (Version).flac      <- verified/marked files, NN from TrackRow.pos
    _dudosos/                                 <- identity/version/duration doubts (+ reason in report)
    _originales/                              <- original FLACs kept by the "CDJ antiguos" preset
    Informe - <set name>.txt                  <- results report (Spanish)
    Tracklist - <set name>.txt                <- "Copiar tracklist" text with timestamps
    .tracklister/set.json                     <- SetDoc
    .tracklister/journal.json                 <- reversible file ops (undo)
"""
from __future__ import annotations

from pathlib import Path

META_DIR = ".tracklister"
SET_DOC = "set.json"
JOURNAL = "journal.json"
DUDOSOS = "_dudosos"
ORIGINALES = "_originales"
REPORT_TEMPLATE = "Informe - {name}.txt"
TRACKLIST_TEMPLATE = "Tracklist - {name}.txt"


def set_doc_path(set_dir: Path) -> Path:
    return Path(set_dir) / META_DIR / SET_DOC


def journal_path(set_dir: Path) -> Path:
    return Path(set_dir) / META_DIR / JOURNAL


def is_reserved_subdir(name: str) -> bool:
    """Folders the reorder/library scanners must never treat as tracks."""
    return name in (META_DIR, DUDOSOS, ORIGINALES)
