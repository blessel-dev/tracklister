"""Library index: verified files of previous sets (%APPDATA%\\Tracklister\\library.json).

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Key = primary artist + base title + version ('original' for original/extended), normalised with
core.textnorm. A match also needs the file to still exist and, when both are known, durations
within 3 s. Only files in a set's root count (never _dudosos).
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from tracklister.core.jsonio import read_json, write_json
from tracklister.core.layout import set_doc_path
from tracklister.core.model import (
    LIBRARY_SCHEMA, DoubtKind, LibraryEntry, ResultState, SetDoc, TrackRow, VersionKind,
)
from tracklister.core.textnorm import classify_version, norm_key, split_artists
from tracklister.organize.naming import win_long

DURATION_TOL_S = 3.0
_LIBRARY_STATES = {ResultState.VERIFICADO, ResultState.YA_EN_BIBLIOTECA}


def library_key(artist: str, title: str, version: str | None) -> str:
    parts = split_artists(artist)
    primary = parts[0] if parts else (artist or "")
    kind = classify_version(version)
    v = "original" if kind in (VersionKind.ORIGINAL, VersionKind.EXTENDED) else norm_key(version, drop_original=False)
    return f"{norm_key(primary)}|{norm_key(title)}|{v}"


def row_key(row: TrackRow) -> str:
    return library_key(row.artist_display or row.search_artist, row.title, row.version)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class LibraryIndex:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: list[LibraryEntry] = []
        self.updated_at: str | None = None

    def load(self) -> None:
        try:
            data = read_json(self.path, default=None)
        except ValueError:
            data = None
        if not isinstance(data, dict) or data.get("schema") != LIBRARY_SCHEMA:
            self.entries = []
            return
        self.entries = [LibraryEntry.from_dict(e) for e in data.get("entries", [])]
        self.updated_at = data.get("updated_at")

    def save(self) -> None:
        self.updated_at = _now()
        write_json(self.path, {"schema": LIBRARY_SCHEMA, "updated_at": self.updated_at,
                               "entries": [e.to_dict() for e in self.entries]})

    def add_from_set(self, set_dir: Path, doc: SetDoc) -> int:
        """Replace this set's entries with its current root files. Returns how many were added."""
        set_dir = Path(set_dir)
        self.entries = [e for e in self.entries if e.set_id != doc.set_id]
        rows = {r.uid: r for r in doc.rows}
        added = 0
        for uid, res in doc.results.items():
            row = rows.get(uid)
            if row is None or not res.file or "/" in res.file.replace("\\", "/"):
                continue
            if res.state not in _LIBRARY_STATES and not (res.state == ResultState.DUDOSO and
                                                         res.doubt == DoubtKind.ESPECTRO):
                continue
            p = set_dir / res.file
            if not os.path.isfile(win_long(p)):
                continue
            artist = row.artist_display or row.search_artist
            parts = split_artists(artist)
            self.entries.append(LibraryEntry(
                key=row_key(row), artist_norm=norm_key(parts[0] if parts else artist), title_norm=norm_key(row.title),
                version_kind=str(classify_version(row.version)), path=os.path.abspath(str(p)), set_id=doc.set_id,
                set_name=doc.name, pos=row.pos, duration_s=res.duration_s, format=res.format,
                size=os.path.getsize(win_long(p)), added_at=_now()))
            added += 1
        return added

    def find(self, row: TrackRow, *, exclude_set_id: str | None = None) -> list[LibraryEntry]:
        key = row_key(row)
        out = []
        for e in self.entries:
            if e.key != key or (exclude_set_id and e.set_id == exclude_set_id):
                continue
            if not os.path.isfile(win_long(e.path)):
                continue
            if row.expected_duration_s and e.duration_s and abs(e.duration_s - row.expected_duration_s) > DURATION_TOL_S:
                continue
            out.append(e)
        return out

    def prune_missing(self) -> int:
        before = len(self.entries)
        self.entries = [e for e in self.entries if os.path.isfile(win_long(e.path))]
        return before - len(self.entries)

    def rebuild(self, library_root: Path) -> int:
        """Re-scan <library_root>/*/.tracklister/set.json. Returns the number of entries."""
        self.entries = []
        root = Path(library_root)
        if not root.is_dir():
            return 0
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            doc_path = set_doc_path(d)
            if not doc_path.is_file():
                continue
            try:
                doc = SetDoc.from_dict(read_json(doc_path))
            except (ValueError, KeyError, TypeError):
                continue
            self.add_from_set(d, doc)
        return len(self.entries)
