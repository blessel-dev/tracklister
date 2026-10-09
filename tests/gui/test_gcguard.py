"""The cyclic garbage collector runs only in the GUI thread while the window exists.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import gc
import threading

import pytest

from tracklister.gui import gcguard

pytestmark = pytest.mark.gui


class _Cycle:
    def __init__(self):
        self.me = self


def test_automatic_gc_is_off_and_the_gui_timer_collects(app, qtbot):
    guard = gcguard.install(app)
    assert guard is gcguard.install(app)                       # one per process
    assert not gc.isenabled() and guard.timer.isActive()
    collected_in = []

    def worker():
        for _ in range(5 * gc.get_threshold()[0]):             # far past the gen-0 threshold
            _Cycle()
        collected_in.append(gc.get_count()[0])
    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert collected_in[0] > gc.get_threshold()[0]             # nothing was collected in the worker
    qtbot.waitUntil(lambda: gc.get_count()[0] < gc.get_threshold()[0], timeout=5000)


def test_uninstall_restores_the_automatic_collector(app):
    gcguard.uninstall()
    assert gc.isenabled()
    gcguard.install(app)
    assert not gc.isenabled()
