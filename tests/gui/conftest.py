"""GUI test fixtures: offscreen Qt, the app theme, a window wired to fake services.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import gc
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from tests.gui.fakes import FakeServices, ScriptedPrompter, flush_deferred_deletes  # noqa: E402
from tracklister.engine.credentials import CredentialStore, Credentials  # noqa: E402

TEST_USER = "usuario-prueba"
TEST_PASS = "clave-prueba"


@pytest.fixture
def app(qapp):
    from tracklister.gui.app import prepare_app
    return prepare_app(qapp)


@pytest.fixture(autouse=True)
def _collect_garbage_in_the_gui_thread():
    """Windows and pages of the previous test are collected here, in the GUI thread, never by an
    automatic collection inside a worker thread (see tracklister.gui.gcguard). Torn down last: pytest-qt has
    closed the test's windows and the window fixtures have stopped their threads, so the windows are deleted
    now instead of piling up for the rest of the module."""
    yield
    flush_deferred_deletes()
    gc.collect()


@pytest.fixture(scope="package", autouse=True)
def _restore_automatic_gc():
    yield
    from tracklister.gui import gcguard
    gcguard.uninstall()


@pytest.fixture
def services(tmp_path):
    return FakeServices(library_root=tmp_path / "biblioteca")


@pytest.fixture
def ready_services(services):
    """First run already done, with a (fake keyring) account."""
    services.settings.first_run_done = True
    services.settings.legal_notice_accepted = True
    services.settings.enrichment_enabled = False
    services.settings.watch_downloads_folder = False
    services.save_settings()
    CredentialStore().set(Credentials(TEST_USER, TEST_PASS))
    return services


@pytest.fixture
def prompter():
    return ScriptedPrompter()


def _make_window(qtbot, app, services, prompter):
    from tracklister.gui.app import build_window
    w = build_window(services, app=app, prompter=prompter)
    qtbot.addWidget(w)
    w.resize(1280, 820)
    w.show()
    qtbot.waitExposed(w)
    return w


@pytest.fixture
def window(qtbot, app, ready_services, prompter):
    w = _make_window(qtbot, app, ready_services, prompter)
    yield w
    w.pool.cancel_all()
    w.pool.wait_all(10000)
    if w.worker is not None:
        w.worker.stop()
        w.worker.wait(30000)


@pytest.fixture
def fresh_window(qtbot, app, services, prompter):
    w = _make_window(qtbot, app, services, prompter)
    yield w
    w.pool.cancel_all()
    w.pool.wait_all(10000)
    if w.worker is not None:
        w.worker.stop()
        w.worker.wait(30000)
