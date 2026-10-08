"""Runs ONE engine process for one pass, streams redacted progress events, collects outcomes.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

- subprocess.Popen(argv list, shell=False, CREATE_NO_WINDOW); stdout+stderr merged, UTF-8.
- Every line goes through a Redactor (own username/password) before it reaches on_event or
  stdout.txt; engine.log (which the engines write themselves, including the login username) is
  rewritten redacted when the process ends. The unredacted argv is never stored or logged.
- Cancel kills the whole process tree.
"""
from __future__ import annotations

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
from tracklister.engine.outputs import EngineEvent, ItemOutcome, collect_outputs, match_snum, parse_progress_line
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.spec import EngineSpec

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0


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
        n = max(1, len(manifest))

        def emit(ev: EngineEvent) -> None:
            try:
                on_event(ev)
            except Exception:  # noqa: BLE001 - a UI callback must never kill the run
                pass

        wait = self.budget.wait_time(n)
        while wait > 0:
            emit(EngineEvent("log", None, f"Esperando {int(wait) + 1} s para no superar el limite de "
                                          "busquedas de Soulseek..."))
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

        def reader() -> None:
            with open(job.stdout_path, "w", encoding="utf-8", newline="\n") as out:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    line = redactor.redact(raw.rstrip("\r\n"))
                    out.write(line + "\n")
                    out.flush()
                    ev = parse_progress_line(self.spec.dialect, line)
                    if ev is None:
                        continue
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
                               job.log_path, job.stdout_path, argv_red)
