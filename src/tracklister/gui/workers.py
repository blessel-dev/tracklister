"""Background work for the window: generic tasks and the set-session runner (QThread).

Owner: GUI step.
SPDX-License-Identifier: GPL-3.0-or-later

SetSession.run calls its callback from the engine reader thread and from the session thread;
every callback becomes a Qt signal, so the widgets are only touched in the GUI thread. The
lossy question (asked once per run, inside the session thread) is answered by the GUI through
answer_lossy(); cancelling also releases a pending question.

Short jobs (import, enrichment, update check, yt-dlp, reorder, Diagnostico) are Tasks on daemon
threads; the set session is a QThread that the window waits for before closing.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from typing import Callable, Iterable

from PySide6.QtCore import QObject, QThread, Signal

from tracklister.core.model import DuplicateChoice, LibraryEntry, ResultState, RowResult, TrackRow

log = logging.getLogger("tracklister.gui")


def error_text(e: BaseException) -> str:
    """Spanish user-facing text: the module's own msg_es when there is one."""
    msg = getattr(e, "msg_es", None)
    if msg:
        return str(msg)
    if isinstance(e, OSError):
        where = f" ({e.filename})" if getattr(e, "filename", None) else ""
        return f"No se pudo leer o escribir un archivo{where}: {e.strerror or e}."
    return f"Error inesperado ({type(e).__name__}): {e}"


class Task(QObject):
    """Runs fn(task) in a daemon thread; fn may use task.progress.emit, task.message.emit and
    task.cancel. Signals reach the GUI thread queued. A daemon thread (not a QThread) so that a
    slow network call can never block or crash the app when the window closes."""

    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)
    message = Signal(str)
    finished = Signal()

    def __init__(self, fn: Callable[["Task"], object], parent: QObject | None = None):
        super().__init__(parent)
        self._fn = fn
        self.cancel = threading.Event()
        self._thread = threading.Thread(target=self._run, name="tracklister-task", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def isRunning(self) -> bool:  # noqa: N802 - same name as QThread's
        return self._thread.is_alive()

    def wait(self, ms: int) -> bool:
        self._thread.join(max(0, ms) / 1000)
        return not self._thread.is_alive()

    def _run(self) -> None:
        try:
            result = self._fn(self)
        except Exception as e:  # noqa: BLE001 - reported to the user, never silently lost
            log.error("task failed: %s", traceback.format_exc())
            self.failed.emit(error_text(e))
        else:
            self.succeeded.emit(result)
        finally:
            self.finished.emit()


class TaskPool(QObject):
    """Keeps every task referenced until its thread has finished and its signals were delivered."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._tasks: set[Task] = set()

    def start(self, fn: Callable[[Task], object], *, on_ok: Callable | None = None,
              on_error: Callable[[str], None] | None = None,
              on_progress: Callable[[int, int], None] | None = None,
              on_message: Callable[[str], None] | None = None) -> Task:
        t = Task(fn)
        if on_ok:
            t.succeeded.connect(on_ok)
        if on_error:
            t.failed.connect(on_error)
        if on_progress:
            t.progress.connect(on_progress)
        if on_message:
            t.message.connect(on_message)
        self._tasks.add(t)
        t.finished.connect(lambda t=t: self._done(t))
        t.start()
        return t

    def _done(self, t: Task) -> None:
        self._tasks.discard(t)
        t.wait(1000)            # the thread is only returning from its last emit
        t.deleteLater()

    def busy(self) -> bool:
        return any(t.isRunning() for t in self._tasks)

    def cancel_all(self) -> None:
        for t in list(self._tasks):
            t.cancel.set()

    def wait_all(self, ms: int = 20000) -> None:
        """Wait (at most ms in total) for running tasks; their late signals are then dropped."""
        end = time.monotonic() + ms / 1000
        for t in list(self._tasks):
            t.wait(int(max(0.0, end - time.monotonic()) * 1000))


class SessionWorker(QThread):
    """Runs one SetSession pass sequence ('run', 'retry' or 'continue') and then finalize()."""

    session_event = Signal(object, object)   # SessionEvent, RowResult snapshot | None
    lossy_requested = Signal(list)           # list[TrackRow]
    completed = Signal(str)                  # "" = ok, else Spanish error

    def __init__(self, session, *, runner_factory: Callable, creds, library_factory: Callable,
                 mode: str = "run", choices: Iterable[tuple[str, DuplicateChoice, LibraryEntry | None]] = (),
                 parent: QObject | None = None):
        super().__init__(parent)
        self.session = session
        self.runner_factory = runner_factory
        self.creds = creds
        self.library_factory = library_factory
        self.mode = mode
        self.choices = list(choices)
        self.cancel = threading.Event()
        self._answer: set[str] = set()
        self._answered = threading.Event()

    # -- called from the GUI thread
    def stop(self) -> None:
        self.cancel.set()
        self._answered.set()

    def answer_lossy(self, uids: Iterable[str]) -> None:
        self._answer = set(uids)
        self._answered.set()

    # -- worker side
    def _on_event(self, ev) -> None:
        snap = None
        # a final state also without a counter: the 1.0.0 upgrade at the start of a run moves a file or measures
        # a mark again, and the row shows its new reason and file at once (CL-27). The in-flight events («En
        # cola», «Buscando...», «Descargando...») are EN_CURSO and carry none.
        if ev.uid and ev.kind == "row_state" and (ev.done or ev.state not in (None, ResultState.EN_CURSO)):
            res = self.session.doc.results.get(ev.uid)
            if res is not None:
                snap = RowResult.from_dict(res.to_dict())
        self.session_event.emit(ev, snap)

    def _ask_lossy(self, rows: list[TrackRow]) -> set[str]:
        self._answer = set()
        self._answered.clear()
        self.lossy_requested.emit([TrackRow.from_dict(r.to_dict()) for r in rows])
        while not self._answered.wait(0.1):
            if self.cancel.is_set():
                return set()
        return set() if self.cancel.is_set() else set(self._answer)

    def run(self) -> None:
        err = ""
        try:
            for uid, choice, entry in self.choices:
                self.session.apply_duplicate_choice(uid, choice, entry)
                if choice == DuplicateChoice.REUSE:
                    res = self.session.doc.results.get(uid)
                    snap = RowResult.from_dict(res.to_dict()) if res is not None else None
                    from tracklister.pipeline.session import SessionEvent
                    # a copy that no longer fits the set's format is downloaded instead: say so
                    msg = snap.reasons[0] if snap is not None and snap.reasons else "Copiado de tu biblioteca"
                    self.session_event.emit(SessionEvent("row_state", uid, snap.state if snap else None,
                                                         msg, 1, 1), snap)
            runner = self.runner_factory()
            if self.mode == "retry":
                self.session.retry_failed(runner, self.creds, self._on_event, self.cancel)
            else:
                self.session.run(runner, self.creds, self._on_event, self.cancel, self._ask_lossy)
        except Exception as e:  # noqa: BLE001
            log.error("session failed: %s", traceback.format_exc())
            err = error_text(e)
        try:
            self.session.finalize(self.library_factory())
        except Exception as e:  # noqa: BLE001
            log.error("finalize failed: %s", traceback.format_exc())
            err = err or ("No se pudo terminar de ordenar la carpeta del set: " + error_text(e))
        self.completed.emit(err)
