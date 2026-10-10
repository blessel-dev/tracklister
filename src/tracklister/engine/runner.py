"""Runs ONE engine process for one pass, streams redacted progress events, collects outcomes.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

- subprocess.Popen(argv list, shell=False, CREATE_NO_WINDOW); stdout+stderr merged, UTF-8.
- Every line goes through a Redactor (own username/password) before it reaches on_event or
  stdout.txt; engine.log (which the engines write themselves, including the login username) is
  rewritten redacted when the process ends. The unredacted argv is never stored or logged.
- Cancel kills the whole process tree.
- Search budget: one search per item, DESPERATE_SEARCHES_PER_ITEM per item with --desperate (1.0.1, R4).
- --print json-all (Diagnóstico): the JSON array is also read from the RAW line, in memory only
  (EngineRunResult.json_all), before the line is redacted for stdout.txt. Redacting first broke the JSON
  when the account was called like one of its words: a username 'file', a password 'true' (audit r4-3 N7).
  Nothing unredacted is written to disk or sent as an event.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from tracklister.diagnostics.redact import Redactor
from tracklister.engine.cli import EngineJob, build_command, redact_argv
from tracklister.engine.credentials import Credentials
from tracklister.engine.csvwriter import ManifestItem
from tracklister.engine.outputs import (
    EngineEvent, ItemOutcome, collect_outputs, fatal_reason_es, match_snum, parse_progress_line,
)
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.spec import EngineSpec

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0

# --desperate: when an item's searches find nothing, both engines search again (3.x Sockseek.Core/Search/
# Searcher.cs:596-648, 2.x Services/Searcher.cs:739-811): artist + album, artist + title without the length
# condition, album, title only and artist only; plus the base search and its no-diacritics twin (3.x :581-584).
# Up to 7 searches per item, all counted against the app-wide budget before the process starts.
DESPERATE_SEARCHES_PER_ITEM = 7


def searches_for(job: EngineJob, manifest: list[ManifestItem]) -> int:
    """Searches to reserve in the app-wide budget for one engine process (at least 1)."""
    return max(1, len(manifest)) * (DESPERATE_SEARCHES_PER_ITEM if job.desperate else 1)


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


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                       creationflags=CREATE_NO_WINDOW, check=False)
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
        try:
            proc = subprocess.Popen(argv, shell=False, cwd=str(work), env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
        except OSError as e:
            raise EngineError(f"No se pudo arrancar el motor ({type(e).__name__}). "
                              "Revisa Ajustes > Motor o reinstala Tracklister.") from None
        del argv  # the unredacted argv (with the password) is not kept around

        banned = threading.Event()
        fatal: list[str] = []
        arrays: list[list] = []

        def reader() -> None:
            with open(job.stdout_path, "w", encoding="utf-8", newline="\n") as out:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    if job.print_json_all and raw.lstrip().startswith("["):
                        try:
                            parsed = json.loads(raw)
                        except ValueError:
                            parsed = None
                        if isinstance(parsed, list):
                            arrays.append(parsed)
                    line = redactor.redact(raw.rstrip("\r\n"))
                    out.write(line + "\n")
                    out.flush()
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
                    emit(EngineEvent(ev.kind, snum, ev.text, ev.subject))

        t = threading.Thread(target=reader, name="engine-stdout", daemon=True)
        t.start()
        cancelled = False
        while proc.poll() is None:
            if cancel.wait(0.2):
                cancelled = True
                _kill_tree(proc)
                break
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
