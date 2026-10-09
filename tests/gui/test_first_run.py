"""Primer inicio: own account to the (fake) keyring only, folder, preset, port; both themes render.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import pytest

from tests.gui.conftest import TEST_PASS, TEST_USER
from tracklister.core.paths import app_paths
from tracklister.core.settings import load_settings
from tracklister.engine.credentials import CredentialStore

pytestmark = pytest.mark.gui


def _all_text_under(root) -> str:
    out = []
    for p in root.rglob("*"):
        if p.is_file():
            out.append(p.read_bytes().decode("utf-8", errors="replace"))
    return "\n".join(out)


def test_first_run_is_shown_and_nav_hidden(fresh_window):
    w = fresh_window
    assert w.current_page() == "first_run"
    assert not any(b.isVisible() for b in w.nav_buttons.values())
    w.go("settings")                      # cannot skip the setup
    assert w.current_page() == "first_run"


def test_validation_messages(fresh_window, fake_keyring):
    p = fresh_window.first_run
    assert p.submit() is False and "usuario" in p.error.text()
    p.user.setText(TEST_USER)
    assert p.submit() is False and "contraseña" in p.error.text()
    p.password.setText(TEST_PASS)
    p.port.setText("80")
    assert p.submit() is False and "puerto" in p.error.text()
    p.port.setText("49998")
    p.accept_box.setChecked(False)
    assert p.submit() is False and "Entendido" in p.error.text()
    assert CredentialStore().get() is None and fake_keyring.store == {}


def test_submit_saves_account_in_keyring_only(fresh_window, fake_keyring, tmp_path):
    w = fresh_window
    p = w.first_run
    lib = tmp_path / "Mi biblioteca"
    p.user.setText(TEST_USER)
    p.password.setText(TEST_PASS)
    p.folder.setText(str(lib))
    p.preset.set_value("cdj_antiguos")
    p.port.setValue(50123)
    p.accept_box.setChecked(True)
    assert p.submit() is True
    creds = CredentialStore().get()
    assert (creds.username, creds.password) == (TEST_USER, TEST_PASS)
    s = load_settings(app_paths().settings_file)
    assert s.first_run_done and s.share_notice_shown and s.legal_notice_accepted
    assert s.library_root == str(lib) and lib.is_dir()
    assert s.preset_id == "cdj_antiguos" and s.listen_port == 50123
    # the password and the account name never reach any file of the app
    text = _all_text_under(app_paths().config_dir.parent)
    assert TEST_PASS not in text and TEST_USER not in text
    assert p.password.text() == ""
    assert w.current_page() == "new_set"
    assert all(b.isVisible() for b in w.nav_buttons.values())


@pytest.mark.parametrize("tid", ["hormigon", "noche"])
def test_first_run_renders_in_both_themes(fresh_window, tid):
    fresh_window.themes.apply(tid)
    img = fresh_window.grab().toImage()
    assert not img.isNull() and img.width() >= 980
    bg = fresh_window.themes.theme.color("bg")
    assert img.pixelColor(10, img.height() // 2).name() == bg
