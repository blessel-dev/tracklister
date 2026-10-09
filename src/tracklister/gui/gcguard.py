"""Run Python's cyclic garbage collector only in the GUI thread.

Owner: GUI step.
SPDX-License-Identifier: GPL-3.0-or-later

Background work (engine passes, verification, imports) runs Python code in other threads. If the
automatic collector fires there, it may destroy Qt objects that ended up in reference cycles, and
Qt objects destroyed outside the GUI thread crash the process (seen in the GUI tests: an access
violation while "Garbage-collecting" in a worker thread). So the automatic collector is switched
off and the same generational thresholds are checked from a QTimer in the GUI thread.
"""
from __future__ import annotations

import gc

from PySide6.QtCore import QObject, QTimer

_GUARD: "MainThreadGC | None" = None


class MainThreadGC(QObject):
    def __init__(self, parent: QObject | None = None, interval_ms: int = 500):
        super().__init__(parent)
        self.threshold = gc.get_threshold()
        gc.disable()
        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self.check)
        self.timer.start()

    def check(self) -> None:
        c0, c1, c2 = gc.get_count()
        t0, t1, t2 = self.threshold
        if c0 > t0:
            gen = 2 if (c1 > t1 and c2 > t2) else 1 if c1 > t1 else 0
            gc.collect(gen)

    def stop(self) -> None:
        self.timer.stop()
        gc.enable()


def install(app) -> MainThreadGC:
    """Idempotent: one guard per process, owned by the QApplication."""
    global _GUARD
    if _GUARD is None:
        _GUARD = MainThreadGC(app)
    return _GUARD


def uninstall() -> None:
    """Back to the automatic collector (tests leaving the GUI package)."""
    global _GUARD
    if _GUARD is not None:
        try:
            _GUARD.stop()
        except RuntimeError:          # the QApplication (its parent) is already gone
            gc.enable()
        _GUARD = None
    else:
        gc.enable()
