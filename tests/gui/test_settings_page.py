"""Ajustes: theme selector, presets, folders, port/engine, checks, account, yt-dlp and update notice.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLabel

from tests.gui.conftest import TEST_PASS
from tests.gui.fakes import FakeUpdate
from tracklister.assets import load_tokens
from tracklister.core.paths import app_paths
from tracklister.core.settings import load_settings
from tracklister.engine.credentials import CredentialStore

pytestmark = pytest.mark.gui


def _saved():
    return load_settings(app_paths().settings_file)


def test_theme_selector_applies_live_and_persists(window, app):
    window.go("settings")
    sp = window.settings_page
    assert set(sp.theme_buttons) == {"hormigon", "noche"}
    assert sp.theme_buttons["hormigon"].text() == "Hormigón (claro)"
    sp.theme_buttons["noche"].setChecked(True)
    assert window.themes.theme.id == "noche"
    assert load_tokens()["themes"]["noche"]["colors"]["bg"] in app.styleSheet()
    assert _saved().theme == "noche"
    sp.theme_buttons["hormigon"].setChecked(True)
    assert window.themes.theme.id == "hormigon" and _saved().theme == "hormigon"


def test_fresh_settings_show_hormigon(window, app):
    """User-confirmed default (DECISIONES M.1): a settings file without a theme opens in Hormigón."""
    assert load_tokens()["default_theme"] == "hormigon"
    assert _saved().theme is None
    assert window.themes.theme.id == "hormigon" and not window.themes.theme.is_dark
    assert load_tokens()["themes"]["hormigon"]["colors"]["bg"] in app.styleSheet()
    window.go("settings")
    sp = window.settings_page
    assert sp.theme_buttons["hormigon"].isChecked() and not sp.theme_buttons["noche"].isChecked()


def test_noche_persists_after_a_restart(window, app, qtbot, prompter, tmp_path):
    from tests.gui.conftest import _make_window
    from tests.gui.fakes import FakeServices
    window.go("settings")
    window.settings_page.theme_buttons["noche"].setChecked(True)
    assert window.themes.theme.id == "noche" and _saved().theme == "noche"
    window.close()
    # "restart": new services read the settings file again, new window
    again = FakeServices(library_root=tmp_path / "biblioteca")
    assert again.settings.theme == "noche"
    w2 = _make_window(qtbot, app, again, prompter)
    try:
        assert w2.themes.theme.id == "noche" and w2.themes.theme.is_dark
        assert load_tokens()["themes"]["noche"]["colors"]["bg"] in app.styleSheet()
        w2.go("settings")
        assert w2.settings_page.theme_buttons["noche"].isChecked()
    finally:
        w2.pool.cancel_all()
        w2.pool.wait_all(10000)


def test_presets_and_custom_options(window):
    window.go("settings")
    sp = window.settings_page
    assert not sp.custom.isVisible()
    sp.preset.buttons["cdj_antiguos"].setChecked(True)
    assert _saved().preset_id == "cdj_antiguos"
    sp.preset.buttons["personalizado"].setChecked(True)
    assert _saved().preset_id == "personalizado" and sp.custom.isVisible()
    sp.fmt_boxes["mp3"].setChecked(True)
    sp.fmt_boxes["wav"].setChecked(False)
    sp.max_sr.setCurrentIndex(sp.max_sr.findData(48000))
    sp.max_bits.setCurrentIndex(sp.max_bits.findData(24))
    sp.kbps.setCurrentIndex(sp.kbps.findData(256))
    sp.lossy_fallback.setChecked(True)
    cp = _saved().custom_preset
    assert cp.formats == ["flac", "aiff", "mp3"] and cp.max_samplerate == 48000 and cp.max_bitdepth == 24
    assert cp.min_mp3_kbps == 256 and cp.allow_lossy_fallback is True
    window.go("new_set")
    assert "Personalizado" in window.new_set.preset_label.text()


def test_port_engine_and_checks(as_windows, window, tmp_path):
    window.go("settings")
    sp = window.settings_page
    sp.port.setText("50001")
    assert _saved().listen_port == 50001
    sp.port.setText("70000")                                 # out of range: not saved
    assert _saved().listen_port == 50001
    window.go("new_set")                                     # leaving Ajustes shows the saved port again
    assert sp.port.text() == "50001"
    window.go("settings")
    sp.engine.setCurrentIndex(sp.engine.findData("sldl-2.6.0"))
    assert _saved().engine_id == "sldl-2.6.0"
    sp.enrich_box.setChecked(True)
    sp.spectral_box.setChecked(False)
    s = _saved()
    assert s.enrichment_enabled is True and s.spectral_check_enabled is False


def test_library_folder_and_rebuild(window, qtbot, prompter, tmp_path):
    window.go("settings")
    sp = window.settings_page
    new_root = tmp_path / "Otra biblioteca"
    prompter.folders = [str(new_root)]
    sp.change_root()
    assert _saved().library_root == str(new_root) and new_root.is_dir()
    assert sp.root.text() == str(new_root)
    sp.rebuild_library()
    qtbot.waitUntil(lambda: "Índice reconstruido" in sp.library_info.text(), timeout=10000)


def test_account_change_and_clear(window, prompter, fake_keyring):
    window.go("settings")
    sp = window.settings_page
    assert "usuario-prueba" in sp.account.text()
    sp.save_account()
    assert "Escribe el usuario" in sp.banner.message()
    sp.user.setText("otra-cuenta")
    sp.password.setText("otra-clave")
    sp.save_account()
    creds = CredentialStore().get()
    assert (creds.username, creds.password) == ("otra-cuenta", "otra-clave")
    assert sp.password.text() == "" and "otra-cuenta" in sp.account.text()
    text = app_paths().settings_file.read_text(encoding="utf-8")
    assert "otra-clave" not in text and TEST_PASS not in text and "otra-cuenta" not in text
    prompter.confirm_answer = False
    sp.clear_account()
    assert CredentialStore().get() is not None
    prompter.confirm_answer = True
    sp.clear_account()
    assert CredentialStore().get() is None and "No hay ninguna cuenta" in sp.account.text()


def test_ytdlp_version_and_update(window, qtbot, ready_services):
    window.go("settings")
    sp = window.settings_page
    qtbot.waitUntil(lambda: sp.ytdlp_label.text() == "yt-dlp: 2026.09.30", timeout=5000)
    sp.ytdlp_btn.click()
    qtbot.waitUntil(lambda: ready_services.ytdlp_updates == 1 and "actualizado" in sp.banner.message(),
                    timeout=5000)


def test_update_notice_with_link(window, qtbot, ready_services):
    window.check_updates()
    qtbot.waitUntil(lambda: ready_services.update_calls == [False], timeout=5000)
    qtbot.wait(50)
    assert not window.update_holder.isVisible()                      # nothing new: no notice
    ready_services.update_info = FakeUpdate("1.0.1", "https://github.com/x/tracklister/releases/tag/v1.0.1",
                                            "Tracklister 1.0.1 ya está disponible")
    window.go("settings")
    window.settings_page.update_btn.click()
    qtbot.waitUntil(lambda: window.update_holder.isVisible(), timeout=5000)
    assert ready_services.update_calls[-1] is True                   # 'Buscar actualizaciones' forces it
    assert window.update_banner.message().startswith("Tracklister 1.0.1 ya está disponible.")
    window.update_banner.actions.itemAt(0).widget().click()
    assert ready_services.opened_urls[-1].endswith("/v1.0.1")
    window.update_banner.close_btn.click()
    assert not window.update_holder.isVisible()


def _labels(widget) -> list[str]:
    return [lb.text() for lb in widget.findChildren(QLabel)]


@pytest.fixture
def sldl_saved(ready_services):
    """A settings.json that says sldl 2.6.0, as one copied from a PC would."""
    ready_services.settings.engine_id = "sldl-2.6.0"
    ready_services.save_settings()
    return ready_services


def test_windows_engine_selector_lists_both_engines(as_windows, sldl_saved, window):
    window.go("settings")
    sp = window.settings_page
    assert [sp.engine.itemData(i) for i in range(sp.engine.count())] == ["sockseek-3.0.5", "sldl-2.6.0"]
    assert [sp.engine.itemText(i) for i in range(sp.engine.count())] == ["Sockseek 3.0.5 (recomendado)",
                                                                         "sldl 2.6.0 (alternativa)"]
    assert sp.engine.currentData() == "sldl-2.6.0"


def test_mac_engine_selector_shows_only_sockseek(as_macos, sldl_saved, window):
    """sldl is not shipped on macOS (DECISIONES Y): one engine, and the effective one is selected."""
    window.go("settings")
    sp = window.settings_page
    assert [sp.engine.itemData(i) for i in range(sp.engine.count())] == ["sockseek-3.0.5"]
    assert sp.engine.currentData() == "sockseek-3.0.5"
    assert _saved().engine_id == "sldl-2.6.0"                 # nothing is rewritten until the user changes it


def test_windows_account_and_port_texts_are_those_of_1_0(as_windows, window):
    from tracklister.gui.pages.first_run import PORT_HELP
    window.go("settings")
    sp = window.settings_page
    texts = _labels(sp)
    assert "En el Administrador de credenciales de Windows, nunca en un archivo." in texts
    assert PORT_HELP in texts
    sp.user.setText("otra-cuenta")
    sp.password.setText("otra-clave")
    sp.save_account()
    assert sp.banner.message() == "Cuenta guardada en el Administrador de credenciales de Windows."


def test_mac_account_and_port_texts(as_macos, window):
    from tracklister.gui.pages.first_run import PORT_HELP_MAC
    window.go("settings")
    sp = window.settings_page
    texts = _labels(sp)
    assert "En el Llavero de macOS, nunca en un archivo." in texts and PORT_HELP_MAC in texts
    assert not any("Windows" in t or ".exe" in t for t in texts), [t for t in texts if "Windows" in t or ".exe" in t]
    sp.user.setText("otra-cuenta")
    sp.password.setText("otra-clave")
    sp.save_account()
    assert sp.banner.message() == "Cuenta guardada en el Llavero de macOS."


@pytest.mark.parametrize("tid", ["hormigon", "noche"])
def test_settings_render_in_both_themes(window, tid):
    window.go("settings")
    window.themes.apply(tid)
    img = window.grab().toImage()
    assert not img.isNull()
    assert img.pixelColor(10, img.height() // 2).name() == window.themes.theme.color("bg")
