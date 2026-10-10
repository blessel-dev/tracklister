"""Library index: verified files of previous sets (%APPDATA%\\Tracklister\\library.json).

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Key = primary artist + base title + version ('original' for original/extended), normalised with
core.textnorm (the version through version_key: its groups sorted, so their order never matters).
A match also needs the file to still exist and, when both are known, durations within 3 s. Only
files in a set's root count (never _dudosos).

1.0.1 (DECISIONES X): library.json is schema /2. A /1 file, written by 1.0.0, is still read: its
entries are re-keyed from each set's own set.json (add_from_set), so its verified files are still
offered as duplicates. An entry whose set.json cannot be read keeps its old key.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from tracklister.core.jsonio import read_json, write_json
from tracklister.core.layout import set_doc_path
from tracklister.core.model import (
    LIBRARY_SCHEMA, LIBRARY_SCHEMA_V1, DoubtKind, LibraryEntry, ResultState, SetDoc, TrackRow,
)
from tracklister.core.textnorm import classify_version, norm_key, split_artists, version_key
from tracklister.organize.naming import win_long

log = logging.getLogger("tracklister.library")

DURATION_TOL_S = 3.0
_LIBRARY_STATES = {ResultState.VERIFICADO, ResultState.REVISAR_CALIDAD, ResultState.YA_EN_BIBLIOTECA}
# The quality marks of a file, which travel with it when another set reuses it ("Usar el que ya tengo").
STRONG_SPECTRAL_FLAG = "probable_mp3_convertido"      # 1.0.1 (verify.spectral, class STRONG)
LEGACY_SPECTRAL_FLAG = "posible_falso_lossless"       # 1.0.0: any sharp cut, strong or not
CARRIED_FLAGS = (LEGACY_SPECTRAL_FLAG, STRONG_SPECTRAL_FLAG)


def library_key(artist: str, title: str, version: str | None) -> str:
    """'Kai Remix', 'Radio Edit' and 'Kai Remix - Radio Edit' are three keys (audit round 4, second
    review); 'Original Mix', 'Extended Mix' and none are one ('original'); '(Kai Remix) (Radio Edit)'
    and '(Radio Edit) (Kai Remix)' are one (1.0.1, version_key)."""
    parts = split_artists(artist)
    primary = parts[0] if parts else (artist or "")
    return f"{norm_key(primary)}|{norm_key(title)}|{version_key(version)}"


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
        schema = data.get("schema") if isinstance(data, dict) else None
        if schema not in (LIBRARY_SCHEMA, LIBRARY_SCHEMA_V1):
            self.entries = []
            return
        self.entries = [LibraryEntry.from_dict(e) for e in data.get("entries", [])]
        self.updated_at = data.get("updated_at")
        if schema == LIBRARY_SCHEMA_V1:
            self._rekey_v1()

    def _rekey_v1(self) -> None:
        """A 1.0.0 library: rebuild each set's entries from its own set.json, with the 1.0.1 keys. Nothing
        is written here; the next save() writes schema /2."""
        folders: list[Path] = []
        for e in self.entries:
            d = Path(e.path).parent
            if d not in folders:
                folders.append(d)
        for d in folders:
            try:
                data = read_json(set_doc_path(d), default=None)
                if not isinstance(data, dict):
                    continue                      # no set.json there any more: keep the old entries
                doc = SetDoc.from_dict(data)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                log.warning("library: a 1.0.0 set could not be re-keyed (%s); its entries keep their keys",
                            type(exc).__name__)
                continue
            self.add_from_set(d, doc)

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
                size=os.path.getsize(win_long(p)), added_at=_now(),
                flags=[f for f in CARRIED_FLAGS if f in res.flags]))
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
