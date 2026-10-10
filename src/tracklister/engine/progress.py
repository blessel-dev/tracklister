"""Per-row download progress for the Estado column of the Descarga screen (1.0.1, R11).

Owner: gui-integration step (the engine side is kept small; DECISIONES X, ENGINE-FACTS.md section 8).
SPDX-License-Identifier: GPL-3.0-or-later

The engines keep running with --no-progress, so every reader of the plain lines stays as it was
(row states, peer credit, fatal errors, bans, redaction before anything is shown). Sockseek's
--progress-json was not adopted: its download-progress events carry only a job id that no other JSON
event names, and one 500 ms throttle is shared by all jobs (see ENGINE-FACTS.md section 8).

- The PHASE of a row comes from the lines the adapter already reads: searching -> buscando; 3.x
  'queued (r)' / 'queued (l)' / 'initialising' -> cola; a download start (3.x 'downloading', 2.x
  'Initialize') -> descargando; a second start for the same row with another file -> otra_copia (its
  bytes start again); succeeded -> descargado; not found -> sin_resultados; failed -> sin_descargar.
- The BYTES are the size of the row's incomplete file, polled every POLL_S seconds: 3.x writes
  in/.sockseek-staging/<job>/<file name>.incomplete (Sockseek.Core/Transfers/Downloads/Completion/
  OutputFinalizer.cs:47-48 and Downloader.cs:85), 2.x in/<file name>.incomplete (slsk-batchdl/Services/
  FileManager.cs:23-45 and Downloader.cs:54). The file is told apart by its name, the last part of the
  path its download line shows; when two active rows download files with the same name, neither gets
  bytes (never a wrong bar).
- The TOTAL: sldl 2.6.0 prints the size in its 'Initialize:' display ('[325s/44.1kHz/41.0MB]',
  Utilities/Printing.cs:20-29, Models/DownloadWrapper.cs:44). Sockseek 3.0.5's plain lines carry none
  (Sockseek.Api/JobActivityLogFormatter.cs:305-319 shows the path only), so its bar is indeterminate and
  the text says the MB received so far.
- 2.x lines name no query: its 'Initialize' line goes to the one row of the pass that is searching and
  whose title words are all in the file name (the engine's --strict-title guarantees them), else nowhere.

Nothing here writes to disk, and the events carry no peer name.
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from tracklister.core.textnorm import norm_key
from tracklister.engine.csvwriter import ManifestItem
from tracklister.engine.outputs import INCOMPLETE_SUFFIXES, STAGING_DIRS, EngineEvent, _info_mb, _long
from tracklister.engine.spec import EngineDialect

POLL_S = 0.5                       # bytes are measured at most twice a second per row

PHASE_SEARCHING = "buscando"
PHASE_QUEUED = "cola"
PHASE_DOWNLOADING = "descargando"
PHASE_ANOTHER_COPY = "otra_copia"
PHASE_DOWNLOADED = "descargado"
PHASE_NOT_FOUND = "sin_resultados"
PHASE_FAILED = "sin_descargar"
ACTIVE = (PHASE_DOWNLOADING, PHASE_ANOTHER_COPY)

_QUEUED_STATUS = ("queued (r)", "queued (l)", "initialising")
_INVALID = re.compile(r'[<>:"/\\|?*]')
_INFO = re.compile(r"\s+\[[^\]]*\]\s*$")


def _size_now(path: str) -> int:
    """The size of a file another process is still writing. On Windows the size a directory listing reports
    (DirEntry.stat) stays at what it was when the writer opened the file; a stat of the path gives the real
    end. Never open the file to read it: a handle without delete sharing would make the engine's own rename
    of the finished .incomplete file fail, and that download with it (attribute-only access, as os.stat
    uses, takes no part in the sharing checks)."""
    return os.stat(path).st_size


def _name_key(name: str) -> str:
    """A file name as both engines write it to disk (Windows-invalid characters become spaces)."""
    return _INVALID.sub(" ", name).strip(" .").casefold()


def remote_name(display: str) -> str | None:
    """The file name at the end of a download display ('peer\\..\\a\\b\\x.flac [325s/.../41.0MB]')."""
    s = _INFO.sub("", display.strip())
    parts = [p for p in s.replace("/", "\\").split("\\") if p and p != ".."]
    return parts[-1] if len(parts) >= 2 else None


@dataclass
class _Row:
    phase: str = ""
    name: str | None = None        # _name_key of the file being downloaded
    total: int | None = None
    done: int | None = None
    sent: tuple = ()               # the last (phase, done, total) emitted


class ProgressTracker:
    def __init__(self, dialect: EngineDialect, out_dir: Path, manifest: Sequence[ManifestItem],
                 clock: Callable[[], float] = time.monotonic):
        self.dialect = dialect
        self.out_dir = Path(out_dir)
        self.items = {m.snum: m for m in manifest}
        self.rows: dict[int, _Row] = {m.snum: _Row() for m in manifest}
        self._title_words = {m.snum: set(norm_key(m.title, drop_original=False).split()) for m in manifest}
        self._lock = threading.Lock()
        self._clock = clock
        self._last_poll = float("-inf")

    # ---- lines --------------------------------------------------------------------------------------
    def on_event(self, ev: EngineEvent, snum: int | None) -> list[EngineEvent]:
        """The progress events (0 or 1) that a parsed engine line means."""
        with self._lock:
            if ev.kind in ("downloading", "succeeded", "failed") and snum is None:
                snum = self._attribute(ev)
            row = self.rows.get(snum) if snum is not None else None
            if row is None:
                return []
            if ev.kind == "searching":
                row.phase, row.name, row.total, row.done = PHASE_SEARCHING, None, None, None
            elif ev.kind == "downloading" and ev.status in _QUEUED_STATUS:
                if row.phase not in ACTIVE:
                    row.phase = PHASE_QUEUED
            elif ev.kind == "downloading":
                name = remote_name(self._display(ev))
                key = _name_key(name) if name else None
                another = row.name is not None and key != row.name
                mb = _info_mb(self._display(ev)) if self.dialect == EngineDialect.SLDL2 else None
                row.phase = PHASE_ANOTHER_COPY if another else PHASE_DOWNLOADING
                row.name, row.done = key, 0
                row.total = int(mb * 1024 * 1024) if mb else None
            elif ev.kind == "succeeded":
                row.phase = PHASE_DOWNLOADED
                row.done = row.total if row.total else row.done
            elif ev.kind == "not_found":
                row.phase = PHASE_NOT_FOUND
            elif ev.kind == "failed":
                row.phase = PHASE_FAILED
            else:
                return []
            return self._emit(snum, row)

    def _display(self, ev: EngineEvent) -> str:
        """The download display of a line: after 'Artist - Title: ' in 3.x, the whole subject in 2.x."""
        if self.dialect == EngineDialect.SOCKSEEK3:
            i = ev.subject.rfind(": ")
            return ev.subject[i + 2:] if i >= 0 else ""
        return ev.subject

    def _attribute(self, ev: EngineEvent) -> int | None:
        """2.x lines carry no query: a download start goes to the one searching row whose title words are
        all in the file name; a later line of that download goes to the row downloading that file."""
        name = remote_name(self._display(ev))
        if not name:
            return None
        key = _name_key(name)
        if ev.kind == "downloading" and ev.status not in _QUEUED_STATUS:
            words = set(norm_key(name.rsplit(".", 1)[0], drop_original=False).split())
            fits = [s for s, r in self.rows.items() if r.phase in (PHASE_SEARCHING, PHASE_QUEUED, PHASE_FAILED)
                    and self._title_words[s] and self._title_words[s] <= words]
            return fits[0] if len(fits) == 1 else None
        fits = [s for s, r in self.rows.items() if r.name == key and r.phase in ACTIVE]
        return fits[0] if len(fits) == 1 else None

    # ---- the growing files ------------------------------------------------------------------------------
    def due(self) -> bool:
        return self._clock() - self._last_poll >= POLL_S

    def poll(self) -> list[EngineEvent]:
        """Bytes of every downloading row whose incomplete file can be told apart (at most every POLL_S)."""
        with self._lock:
            now = self._clock()
            if now - self._last_poll < POLL_S:
                return []
            self._last_poll = now
            active = {s: r for s, r in self.rows.items() if r.phase in ACTIVE and r.name}
            if not active:
                return []
            sizes = self._incomplete_sizes()
            names = [r.name for r in active.values()]
            out: list[EngineEvent] = []
            for s, r in active.items():
                found = sizes.get(r.name)
                if names.count(r.name) > 1 or found is None or len(found) != 1:
                    continue
                done = found[0]
                if r.total:
                    done = min(done, r.total)
                if done != r.done:
                    r.done = done
                    if r.phase == PHASE_ANOTHER_COPY and done > 0:
                        r.phase = PHASE_DOWNLOADING
                    out += self._emit(s, r)
            return out

    def _incomplete_sizes(self) -> dict[str, list[int]]:
        """name key -> sizes of the incomplete files under in/: in/, in/<snum>/ and the staging folders."""
        out: dict[str, list[int]] = {}
        folders = [self.out_dir]
        for sub in self._subdirs(self.out_dir):
            if sub.name in STAGING_DIRS:
                folders += self._subdirs(sub)
            else:
                folders.append(sub)
        for d in folders:
            try:
                # \\?\ form (as outputs._files_in): a long remote name in in/<snum>/ passes Windows' 260
                # characters on a PC with LongPathsEnabled=0, and its stat must still see it (audit v101-1 N2)
                with os.scandir(_long(d)) as it:
                    entries = [(e.name, e.path) for e in it if e.is_file()]
            except OSError:
                continue
            for name, path in entries:
                low = name.lower()
                suffix = next((x for x in INCOMPLETE_SUFFIXES if low.endswith(x)), None)
                if suffix is None:
                    continue
                try:
                    size = _size_now(path)
                except OSError:
                    continue
                out.setdefault(_name_key(name[: -len(suffix)]), []).append(size)
        return out

    @staticmethod
    def _subdirs(d: Path) -> list[Path]:
        try:
            with os.scandir(_long(d)) as it:
                return [Path(e.path) for e in it if e.is_dir()]
        except OSError:
            return []

    def _emit(self, snum: int, row: _Row) -> list[EngineEvent]:
        key = (row.phase, row.done, row.total)
        if key == row.sent:
            return []
        row.sent = key
        return [EngineEvent("progress", snum, "", phase=row.phase, bytes_done=row.done, bytes_total=row.total)]
