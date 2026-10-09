"""Diagnostico: search-only run with the FAKE engine; the report is redacted and 'Copiar informe' copies it.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.fakes.scenarios import build_scenario
from tests.gui.conftest import TEST_PASS, TEST_USER
from tracklister.engine.credentials import CredentialStore

pytestmark = [pytest.mark.gui, pytest.mark.slow]


def test_report_is_redacted_saved_and_copied(window, qtbot, ready_services, tmp_path):
    rows, net = build_scenario("correcto", tmp_path / "net")
    ready_services.network = net
    window.go("diagnostic")
    page = window.diagnostic
    page.set_tracklist(rows, "set.csv")
    assert page.start_btn.isEnabled() and not page.copy_btn.isEnabled()
    page.start()
    assert page.cancel_btn.isVisible()
    qtbot.waitUntil(lambda: page.task is None, timeout=90000)
    rep = page.box.toPlainText()
    assert rep.startswith("Diagnostico de Tracklister")
    assert "peer-1" in rep and "peer-2" in rep
    for secret in (TEST_USER, TEST_PASS, "peerA", "peerB"):
        assert secret not in rep
    assert not page.download.isChecked()                                # search-only by default
    page.copy_btn.click()
    assert ready_services.copied[-1] == rep
    saved = Path(page.saved.text().removeprefix("Guardado también en ").strip())
    assert saved.is_file() and saved.read_text(encoding="utf-8") == rep
    assert saved.parent == ready_services.paths.logs_dir


def test_needs_an_account_and_rows(window):
    page = window.diagnostic
    window.go("diagnostic")
    assert not page.start_btn.isEnabled()                              # no tracklist yet
    page.set_tracklist(build_scenario("correcto", Path(window.services.paths.data_dir) / "n")[0], "x")
    CredentialStore().clear()
    page.start()
    assert "Falta tu cuenta" in page.banner.message() and page.task is None


def test_uses_the_new_set_table_when_shown(window):
    from tests.gui.fakes import sample_rows
    window.new_set.set_rows(sample_rows(), name="X")
    window.go("diagnostic")
    assert len(window.diagnostic.rows) == 4
    assert window.diagnostic.max_rows.value() == 5
    window.diagnostic.max_rows.setText("99")
    assert window.diagnostic.max_rows.value() == 20                    # clamped to the 1..20 range
    window.diagnostic.max_rows.setText("")
    assert window.diagnostic.max_rows.value() == 1
