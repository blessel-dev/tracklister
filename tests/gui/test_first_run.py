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


def test_settings_show_the_first_run_choices(fresh_window, fake_keyring, tmp_path):
    """Barrido CL-13: Ajustes is built before the first run, and its refresh() updated neither the preset nor the
    port: after choosing «CDJ antiguos» and 50123 it still showed «Lossless» and 49998 until a restart (the
    downloads did use the choice)."""
    w = fresh_window
    p = w.first_run
    p.user.setText(TEST_USER)
    p.password.setText(TEST_PASS)
    p.folder.setText(str(tmp_path / "Mi biblioteca"))
    p.preset.set_value("cdj_antiguos")
    p.port.setValue(50123)
    p.accept_box.setChecked(True)
    assert p.submit() is True
    w.go("settings")
    assert w.settings_page.preset.value() == "cdj_antiguos"
    assert w.settings_page.port.value() == 50123


def test_r2_n8_updates_are_checked_once_the_first_run_is_done(fresh_window, qtbot, services, tmp_path):
    p = fresh_window.first_run
    p.user.setText(TEST_USER)
    p.password.setText(TEST_PASS)
    p.folder.setText(str(tmp_path / "biblioteca nueva"))
    p.accept_box.setChecked(True)
    qtbot.wait(300)
    assert services.update_calls == []                       # never while the first-run screen is up
    assert p.submit() is True
    qtbot.waitUntil(lambda: services.update_calls == [False], timeout=5000)   # but this session checks too


def test_port_help_names_the_engine_the_firewall_asks_about(as_windows):
    from tracklister.gui.pages.first_run import PORT_HELP, port_help
    assert "«sockseek.exe»" in PORT_HELP and "«sldl.exe»" in PORT_HELP and "Firewall de Windows" in PORT_HELP
    assert "permite Tracklister" not in PORT_HELP
    assert port_help() is PORT_HELP


def test_mac_port_help_names_sockseek_and_the_macos_firewall(as_macos):
    from tracklister.gui.pages.first_run import PORT_HELP_MAC, port_help
    assert port_help() is PORT_HELP_MAC
    assert PORT_HELP_MAC == (
        "Si las descargas no arrancan, abre este puerto TCP en el router hacia este Mac y, si tienes activado el "
        "firewall de macOS, permite las conexiones entrantes de «sockseek», el motor de descarga de Tracklister "
        "(Ajustes del Sistema > Red > Firewall > Opciones). Si un amigo usa Tracklister en tu misma red, usad "
        "puertos distintos.")
    assert "«sockseek»" in PORT_HELP_MAC and "firewall de macOS" in PORT_HELP_MAC
    assert ".exe" not in PORT_HELP_MAC and "sldl" not in PORT_HELP_MAC and "Windows" not in PORT_HELP_MAC


def _labels(widget) -> list[str]:
    from PySide6.QtWidgets import QLabel
    return [lb.text() for lb in widget.findChildren(QLabel)]


def test_windows_first_run_texts_are_those_of_1_0(as_windows, fresh_window):
    from tracklister.gui.pages.first_run import PORT_HELP
    texts = _labels(fresh_window.first_run)
    assert ("De una tracklist a una carpeta ordenada de música verificada. Tres datos y listo: todo se guarda solo "
            "en este PC.") in texts
    assert any(t.startswith("Se guarda en el Administrador de credenciales de Windows, nunca en un archivo. Si aún "
                            "no tienes cuenta,") for t in texts)
    assert PORT_HELP in texts


def test_mac_first_run_texts(as_macos, fresh_window):
    from tracklister.gui.pages.first_run import PORT_HELP_MAC
    texts = _labels(fresh_window.first_run)
    assert ("De una tracklist a una carpeta ordenada de música verificada. Tres datos y listo: todo se guarda solo "
            "en este Mac.") in texts
    assert any(t.startswith("Se guarda en el Llavero de macOS, nunca en un archivo. Si aún no tienes cuenta,")
               for t in texts)
    assert PORT_HELP_MAC in texts
    assert not any("Windows" in t or "este PC" in t or ".exe" in t for t in texts)


@pytest.mark.parametrize("tid", ["hormigon", "noche"])
def test_first_run_renders_in_both_themes(fresh_window, tid):
    fresh_window.themes.apply(tid)
    img = fresh_window.grab().toImage()
    assert not img.isNull() and img.width() >= 980
    bg = fresh_window.themes.theme.color("bg")
    assert img.pixelColor(10, img.height() // 2).name() == bg
