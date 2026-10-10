"""One engine process at a time: a download never starts while the Diagnostico runs, and the other way round.

Both would log in with the same Soulseek account and listen port, and Soulseek drops one of them
(external audit N6). Also: a reused library file shows the mark it carries (audit N8).

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import threading

import pytest

from tests.fakes.scenarios import build_scenario
from tracklister.core.model import LibraryEntry, ResultState, RowResult
from tracklister.gui.dialogs import _entry_text

pytestmark = [pytest.mark.gui, pytest.mark.slow]

WAIT_DIAG = ("Diagnóstico en curso", "Espera a que termine el Diagnóstico (o cancélalo).")


class _FakeTask:
    """Stands in for the Diagnostico's Task (gui.workers.Task) while its engine process runs."""

    def __init__(self):
        self.running = True
        self.cancel = threading.Event()

    def isRunning(self) -> bool:  # noqa: N802 - same name as Task/QThread
        return self.running


class _FakeWorker:
    def isRunning(self) -> bool:  # noqa: N802
        return True

    def stop(self) -> None:
        pass

    def wait(self, ms: int = 0) -> bool:
        return True


def _wait_done(qtbot, window, timeout=120000):
    qtbot.waitUntil(lambda: not window.worker_running() and window.results.phase.text() == "Terminado.",
                    timeout=timeout)


def test_download_and_retry_wait_for_a_running_diagnostic(window, qtbot, ready_services, prompter, tmp_path):
    rows, net = build_scenario("correcto", tmp_path / "net")
    ready_services.network = net
    task = _FakeTask()
    window.diagnostic.task = task
    try:
        assert window.engine_busy_es() == WAIT_DIAG
        assert window.start_download("Set", rows, []) is False
        assert window.worker is None and window.session is None              # no SessionWorker was made
        assert prompter.calls[-1] == ("inform",) + WAIT_DIAG
        window.session = ready_services.create_session("Set", rows, [])
        for mode in ("retry", "continue"):
            n = len(prompter.calls)
            window.run_again(mode)
            assert window.worker is None and prompter.calls[n:] == [("inform",) + WAIT_DIAG]
        window.session = None
        # the Diagnostico has finished: now the download starts (one engine at a time)
        task.running = False
        assert window.engine_busy_es() is None
        assert window.start_download("Set", rows, []) is True
        assert window.worker is not None
        _wait_done(qtbot, window)
        m = window.results.model
        assert [m.state_of(r.uid) for r in m.rows()] == [ResultState.VERIFICADO, ResultState.VERIFICADO]
    finally:
        window.diagnostic.task = None


def test_diagnostic_waits_for_a_running_download(window, tmp_path):
    rows, _ = build_scenario("correcto", tmp_path / "net")
    page = window.diagnostic
    window.go("diagnostic")
    page.set_tracklist(rows, "set.csv")
    window.worker = _FakeWorker()
    try:
        page.start()
        assert page.task is None
        assert page.banner.message() == "Espera a que termine la descarga actual (o cancélala)."
    finally:
        window.worker = None


def test_reused_file_shows_its_fake_lossless_mark(window, tmp_path):
    # 1.0.1 (R6): the mark a reused file carries reads «probable MP3 convertido» (the 1.0.0 flag too)
    m = window.results.model
    res = RowResult(uid="u", pos=1, state=ResultState.YA_EN_BIBLIOTECA, flags=["reutilizado", "posible_falso_lossless"])
    assert m.state_text(res) == "Ya en biblioteca · probable MP3 convertido"
    new = RowResult(uid="w", pos=3, state=ResultState.YA_EN_BIBLIOTECA, flags=["reutilizado", "probable_mp3_convertido"])
    assert m.state_text(new) == "Ya en biblioteca · probable MP3 convertido"
    plain = RowResult(uid="v", pos=2, state=ResultState.YA_EN_BIBLIOTECA, flags=["reutilizado"])
    assert m.state_text(plain) == "Ya en biblioteca"
    e = LibraryEntry(key="k", artist_norm="dj dextro", title_norm="covil dos abutres", version_kind="original",
                     path=str(tmp_path / "x.flac"), set_id="a", set_name="Set A", pos=1, format="flac",
                     flags=["posible_falso_lossless"])
    assert _entry_text(e).endswith("marcado: probable MP3 convertido")
