"""Runs ONE engine process for one pass, streams redacted progress events, collects outcomes.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

- subprocess.Popen(argv list, shell=False, CREATE_NO_WINDOW); stdout+stderr merged, UTF-8. On POSIX
  (macOS) the engine also starts its own session (start_new_session), so it leads its own process group.
- Every line goes through a Redactor (own username/password) before it reaches on_event or
  stdout.txt; engine.log (which the engines write themselves, including the login username) is
  rewritten redacted when the process ends. The unredacted argv is never stored or logged.
- Cancel kills the whole process tree: taskkill /T on Windows; on POSIX SIGTERM to the engine's process
  group, then SIGKILL if it is still there after KILL_GRACE_S.
- Search budget: one search per item (two when its query has a non-ASCII character: the engine's twin search
  without diacritics), DESPERATE_SEARCHES_PER_ITEM per item with --desperate (1.0.1, R4).
- --print json-all (Diagnóstico): the JSON array is also read from the RAW line, in memory only
  (EngineRunResult.json_all), before the line is redacted for stdout.txt. Redacting first broke the JSON
  when the account was called like one of its words: a username 'file', a password 'true' (audit r4-3 N7).
  Nothing unredacted is written to disk or sent as an event.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from tracklister.diagnostics.redact import Redactor
from tracklister.engine.cli import EngineJob, build_command, redact_argv
from tracklister.engine.credentials import Credentials
from tracklister.engine.csvwriter import ManifestItem
from tracklister.engine.outputs import (
    EngineEvent, ItemOutcome, collect_outputs, fatal_reason_es, match_snum, parse_progress_line,
)
from tracklister.engine.progress import ProgressTracker
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.spec import EngineSpec

log = logging.getLogger("tracklister.engine")

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
KILL_GRACE_S = 3.0                              # POSIX cancel: SIGTERM, then SIGKILL after this long
SIGKILL = getattr(signal, "SIGKILL", 9)         # Windows' signal module has no SIGKILL (never sent there)

# Every search of a query with a diacritic has a twin without them (3.x Sockseek.Core/Search/Searcher.cs:583-584,
# Common/Utils.cs:881-885): «Héctor Oaks - Tema» is 2 searches (barrido AG-05). Without --desperate an item whose
# artist or title has any non-ASCII character reserves 2 (more than the engine may use: the safe side, X.18).
# --desperate: when an item's searches find nothing, both engines search again (3.x Sockseek.Core/Search/
# Searcher.cs:596-648, 2.x Services/Searcher.cs:739-811): artist + album, artist + title without the length
# condition, album, title only and artist only; plus the base search and its no-diacritics twin (3.x :581-584).
# Up to 7 searches per item (the twin included), all counted against the app-wide budget before the process starts.
DESPERATE_SEARCHES_PER_ITEM = 7


def _has_twin_search(item: ManifestItem) -> bool:
    return any(ord(c) > 127 for c in f"{item.artist}{item.title}")


def searches_for(job: EngineJob, manifest: list[ManifestItem]) -> int:
    """Searches to reserve in the app-wide budget for one engine process (at least 1)."""
    if job.desperate:
        return max(1, len(manifest)) * DESPERATE_SEARCHES_PER_ITEM
    return max(1, sum(2 if _has_twin_search(m) else 1 for m in manifest))


class EngineError(Exception):
    """The engine process could not be started. `msg_es` is user-facing."""

    def __init__(self, msg_es: str):
        super().__init__(msg_es)
        self.msg_es = msg_es


@dataclass
class EngineRunResult:
    exit_code: int | None
    cancelled: bool
    banned: bool
    outcomes: dict[int, ItemOutcome]
    log_path: Path
    stdout_path: Path
    argv_redacted: list[str] = field(default_factory=list)
    fatal_es: str | None = None      # login failed, port busy... (Spanish, for every unfinished row)
    json_all: list | None = None     # --print json-all: the last JSON array, parsed before redaction (memory only)


def _kill_group(proc, killpg: Callable[[int, int], None]) -> None:
    """POSIX: the engine leads its own process group (start_new_session), so the group is the engine and
    anything it started. SIGTERM first; SIGKILL if the engine is still running after KILL_GRACE_S. A group
    that is already gone, or not ours to signal, is left alone."""
    try:
        killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        proc.wait(timeout=KILL_GRACE_S)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        killpg(proc.pid, SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                       creationflags=CREATE_NO_WINDOW, check=False)
    elif hasattr(os, "killpg"):
        _kill_group(proc, os.killpg)
    try:
        proc.kill()
    except OSError:
        pass


def _redact_file(path: Path, redactor: Redactor) -> None:
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        red = redactor.redact(text)
        if red != text:
            path.write_text(red, encoding="utf-8")
    except OSError:
        pass


class EngineRunner:
    def __init__(self, spec: EngineSpec, budget: SearchBudget, *, env: dict[str, str] | None = None):
        self.spec, self.budget, self.env = spec, budget, dict(env or {})

    def run(self, job: EngineJob, manifest: list[ManifestItem], creds: Credentials,
            on_event: Callable[[EngineEvent], None], cancel: threading.Event) -> EngineRunResult:
        work = Path(job.work_dir)
        work.mkdir(parents=True, exist_ok=True)
        job.out_dir.mkdir(parents=True, exist_ok=True)
        redactor = Redactor(secrets=[creds.username, creds.password])
        argv = build_command(self.spec, job, creds)
        argv_red = redact_argv(argv)
        n = searches_for(job, manifest)

        def emit(ev: EngineEvent) -> None:
            try:
                on_event(ev)
            except Exception:  # noqa: BLE001 - a UI callback must never kill the run
                pass

        wait = self.budget.wait_time(n)
        while wait > 0:
            emit(EngineEvent("log", None, f"Esperando {int(wait) + 1} s para no superar el límite de "
                                          "búsquedas de Soulseek..."))
            if cancel.wait(min(wait, 1.0)):
                return EngineRunResult(None, True, False, collect_outputs(job, manifest, self.spec.dialect),
                                       job.log_path, job.stdout_path, argv_red)
            wait = self.budget.wait_time(n)
        if cancel.is_set():
            return EngineRunResult(None, True, False, collect_outputs(job, manifest, self.spec.dialect),
                                   job.log_path, job.stdout_path, argv_red)
        self.budget.reserve(n)

        env = dict(os.environ)
        env.update(self.env)
        # POSIX: its own session and process group, so cancelling reaches everything it started (_kill_group)
        own_group = {"start_new_session": True} if os.name == "posix" else {}
        try:
            proc = subprocess.Popen(argv, shell=False, cwd=str(work), env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW,
                                    **own_group)
        except OSError as e:
            raise EngineError(f"No se pudo arrancar el motor ({type(e).__name__}). "
                              "Revisa Ajustes > Motor o reinstala Tracklister.") from None
        del argv  # the unredacted argv (with the password) is not kept around

        banned = threading.Event()
        fatal: list[str] = []
        arrays: list[list] = []
        # R11: per-row progress from the same plain lines and the growing incomplete files (no download in
        # the Diagnóstico's search-only mode, so no tracker there)
        tracker = None if job.print_json_all else ProgressTracker(self.spec.dialect, job.out_dir, manifest)

        def reader() -> None:
            # Whatever happens, this loop drains the engine's output to the end: if it stopped, the engine would
            # block on its next line and the pass would never end (barrido AG-04). stdout.txt is a convenience:
            # if it cannot be opened or written (a full disk), the run goes on without it.
            out = None
            try:
                out = open(job.stdout_path, "w", encoding="utf-8", newline="\n")
            except OSError as e:
                log.warning("stdout.txt not written (%s): the engine output is still read", type(e).__name__)
            bad_lines = 0
            try:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    try:
                        results_line = False
                        if job.print_json_all and raw.lstrip().startswith("["):
                            try:
                                parsed = json.loads(raw)
                            except ValueError:
                                parsed = None          # e.g. Sockseek's '[003] SongJob: …' lines: the normal path
                            if isinstance(parsed, list):
                                arrays.append(parsed)
                                results_line = True
                        line = redactor.redact(raw.rstrip("\r\n"))
                        if out is not None:
                            try:
                                out.write(line + "\n")
                                out.flush()
                            except OSError as e:
                                log.warning("stdout.txt no longer written (%s)", type(e).__name__)
                                try:
                                    out.close()
                                except OSError:
                                    pass
                                out = None
                        if results_line:
                            # --print json-all: the results of a search (ENGINE-FACTS 4) are data, not an engine
                            # message. No event (the line can be hundreds of KB of other users' names and folders),
                            # and never read as a fatal error or a kick: a result in a 'Soulseek Downloads\Kicked
                            # Inside' share folder is not Soulseek cutting the session (barrido AG-02)
                            continue
                        ev = parse_progress_line(self.spec.dialect, line)
                        if ev is None:
                            continue
                        if ev.kind in ("log", "ban") and not fatal:
                            why = fatal_reason_es(line)
                            if why:
                                fatal.append(why)
                        snum = match_snum(ev.subject, manifest) if ev.subject else None
                        if ev.kind == "ban":
                            banned.set()
                        emit(replace(ev, snum=snum))
                        if tracker is not None:
                            for pev in tracker.on_event(ev, snum):
                                emit(pev)
                    except Exception:  # noqa: BLE001 - one bad line never stops the draining
                        bad_lines += 1
                        if bad_lines == 1:
                            log.exception("an engine output line could not be handled")
            finally:
                if bad_lines > 1:
                    log.warning("%d more engine output lines could not be handled", bad_lines - 1)
                if out is not None:
                    try:
                        out.close()
                    except OSError:
                        pass

        t = threading.Thread(target=reader, name="engine-stdout", daemon=True)
        t.start()
        cancelled = False
        while proc.poll() is None:
            if cancel.wait(0.2):
                cancelled = True
                _kill_tree(proc)
                break
            if tracker is not None and tracker.due():
                for pev in tracker.poll():
                    emit(pev)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
        t.join(timeout=15)
        _redact_file(job.log_path, redactor)
        outcomes = collect_outputs(job, manifest, self.spec.dialect)
        return EngineRunResult(None if cancelled else proc.returncode, cancelled, banned.is_set(), outcomes,
                               job.log_path, job.stdout_path, argv_red, fatal[0] if fatal else None,
                               arrays[-1] if arrays else None)
