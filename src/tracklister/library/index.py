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
from tracklister.organize.naming import listing_key, win_long
from tracklister.verify.spectral import LEGACY_FLAG, STRONG_FLAG, SpectralClass, legacy_class

log = logging.getLogger("tracklister.library")

DURATION_TOL_S = 3.0
_LIBRARY_STATES = {ResultState.VERIFICADO, ResultState.REVISAR_CALIDAD, ResultState.YA_EN_BIBLIOTECA}
# The quality marks of a file, which travel with it when another set reuses it ("Usar el que ya tengo").
STRONG_SPECTRAL_FLAG = STRONG_FLAG                    # 1.0.1 (verify.spectral, class STRONG)
LEGACY_SPECTRAL_FLAG = LEGACY_FLAG                    # 1.0.0: any sharp cut, strong or not
CARRIED_FLAGS = (LEGACY_SPECTRAL_FLAG, STRONG_SPECTRAL_FLAG)


def carried_flags(flags: list[str], reasons: list[str]) -> list[str]:
    """The marks a library entry keeps. A 1.0.0 mark whose own text shows a cut that 1.0.1 classes as
    strong becomes the 1.0.1 mark, one that 1.0.1 no longer marks (~19.5-20.8 kHz) is dropped, and one
    without a readable cut stays as it is."""
    out = [f for f in CARRIED_FLAGS if f in flags]
    if LEGACY_FLAG in out:
        klass = legacy_class(reasons)
        if klass is not None:
            out.remove(LEGACY_FLAG)
            if klass == SpectralClass.STRONG and STRONG_FLAG not in out:
                out.append(STRONG_FLAG)
    return out


def library_key(artist: str, title: str, version: str | None) -> str:
    """'Kai Remix', 'Radio Edit' and 'Kai Remix - Radio Edit' are three keys (audit round 4, second
    review); 'Original Mix', 'Extended Mix' and none are one ('original'); '(Kai Remix) (Radio Edit)'
    and '(Radio Edit) (Kai Remix)' are one (1.0.1, version_key)."""
    parts = split_artists(artist)
    primary = parts[0] if parts else (artist or "")
    return f"{norm_key(primary)}|{norm_key(title)}|{version_key(version)}"


def row_key(row: TrackRow) -> str:
    return library_key(row.artist_display or row.search_artist, row.title, row.version)


def _on_disk(path: str) -> bool:
    """The entry's file is there. Only an absolute path of this system counts: an entry of a library.json
    copied from the other system ('C:\\...' on a Mac, '/Users/...' on a PC) would otherwise be looked up
    relative to the current folder or drive, and could find some other file there."""
    return os.path.isabs(path) and os.path.isfile(win_long(path))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


DAMAGED_COPY_NAME = "library-danado.json"     # like settings-danado.json (gui.services)


class LibraryIndex:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: list[LibraryEntry] = []
        self.updated_at: str | None = None
        # the last load() found a library.json it could not use (empty, cut, not an index, an unknown schema):
        # that is not the same as no library, and saving over it would keep only one set (barrido AG-03)
        self.damaged = False

    def load(self) -> None:
        self.damaged = False
        try:
            data = read_json(self.path, default=None)
        except ValueError:
            data = None
            self.damaged = True
        schema = data.get("schema") if isinstance(data, dict) else None
        if schema not in (LIBRARY_SCHEMA, LIBRARY_SCHEMA_V1):
            self.damaged = self.damaged or self.path.exists()
            self.entries = []
            return
        self.entries = [LibraryEntry.from_dict(e) for e in data.get("entries", [])]
        self.updated_at = data.get("updated_at")
        if schema == LIBRARY_SCHEMA_V1:
            self._rekey_v1()

    def _rekey_v1(self) -> None:
        """A 1.0.0 library: rebuild each set's entries from its own set.json, with the 1.0.1 keys. Nothing
        is written here; the next save() writes schema /2. A path that is not absolute on this system (a
        library.json copied from a PC to a Mac: 'C:\\...' is one relative name there) names no folder here:
        its entries keep their keys, and find() never offers them."""
        folders: list[Path] = []
        for e in self.entries:
            if not os.path.isabs(e.path):
                continue
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

    def keep_damaged_copy(self) -> None:
        """Set a damaged library.json aside as library-danado.json before the index is rebuilt (nothing is
        lost: the sets themselves are still in the library folder)."""
        target = self.path.with_name(DAMAGED_COPY_NAME)
        try:
            os.replace(self.path, target)
        except OSError as e:
            log.warning("library: the damaged index could not be set aside (%s)", type(e).__name__)
            return
        log.warning("library: the index was damaged; kept as %s and rebuilt from the set folders", target.name)

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
                flags=carried_flags(res.flags, res.reasons)))
            added += 1
        return added

    def find(self, row: TrackRow, *, exclude_set_id: str | None = None) -> list[LibraryEntry]:
        key = row_key(row)
        out = []
        for e in self.entries:
            if e.key != key or (exclude_set_id and e.set_id == exclude_set_id):
                continue
            if not _on_disk(e.path):
                continue
            if row.expected_duration_s and e.duration_s and abs(e.duration_s - row.expected_duration_s) > DURATION_TOL_S:
                continue
            out.append(e)
        return out

    def prune_missing(self) -> int:
        before = len(self.entries)
        self.entries = [e for e in self.entries if _on_disk(e.path)]
        return before - len(self.entries)

    def rebuild(self, library_root: Path) -> int:
        """Re-scan <library_root>/*/.tracklister/set.json. Returns the number of entries.

        The set folders are read in organize.naming.listing_key order, never in listing order: that order
        decides which folder wins when two hold the same set (a copied set folder) and which copy «Ya en
        biblioteca» offers first, and it must be the same on every platform (brief mac-1b)."""
        self.entries = []
        root = Path(library_root)
        if not root.is_dir():
            return 0
        for d in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: listing_key(p.name)):
            doc_path = set_doc_path(d)
            if not doc_path.is_file():
                continue
            try:
                doc = SetDoc.from_dict(read_json(doc_path))
            except (OSError, ValueError, KeyError, TypeError):
                continue                          # damaged or unreadable (locked, no permission): skipped
            self.add_from_set(d, doc)
        return len(self.entries)
