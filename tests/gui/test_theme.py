"""Theme: QSS and palette come from the brand tokens; fonts load; state icons are tinted.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QFontDatabase, QIcon, QPalette

from tracklister.assets import load_tokens
from tracklister.core.model import ResultState
from tracklister.gui.theme import (ThemeManager, build_palette, build_qss, indicator_files, load_theme,
                                   register_fonts, state_icon, svg_pixmap, ui_icon)

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("tid", ["hormigon", "noche"])
def test_qss_and_palette_use_the_tokens(app, tmp_path, tid):
    theme = load_theme(tid, register_fonts())
    colors = load_tokens()["themes"][tid]["colors"]
    qss = build_qss(theme, indicator_files(theme, tmp_path))
    for key in ("bg", "surface", "ink", "ink_muted", "line_strong", "accent", "on_accent", "focus", "selection",
                "on_selection", "disabled_ink"):
        assert colors[key] in qss, key
    assert "$" not in qss                       # every placeholder substituted
    assert "radius" not in qss.replace("border-radius: 8px", "")   # brutalist: only the radio dot is round
    pal = build_palette(theme)
    assert pal.color(QPalette.ColorRole.Window).name() == colors["bg"]
    assert pal.color(QPalette.ColorRole.Text).name() == colors["ink"]
    assert pal.color(QPalette.ColorRole.Highlight).name() == colors["selection"]
    for p in indicator_files(theme, tmp_path).values():
        assert p.endswith(".svg") and (tmp_path / p.rsplit("/", 1)[-1]).is_file()


def test_fonts_are_registered(app):
    fams = register_fonts()
    assert fams == {"ui": "Inter", "mono": "JetBrains Mono"}
    assert {"Inter", "JetBrains Mono"} <= set(QFontDatabase.families())


@pytest.mark.parametrize("tid", ["hormigon", "noche"])
def test_state_icons_are_tinted_per_state(app, tid):
    theme = load_theme(tid)
    for st in ResultState:
        icon = state_icon(theme, st)
        assert isinstance(icon, QIcon) and not icon.isNull()
        assert not icon.pixmap(16, 16).isNull()
    # the verificado icon is a filled square: its corner area carries the state colour
    pm = svg_pixmap("icons/state-verificado.svg", theme.state_color(ResultState.VERIFICADO), 24)
    c = pm.toImage().pixelColor(5, 5)
    assert c.alpha() > 200 and c.name() == theme.state_color(ResultState.VERIFICADO)
    assert not ui_icon(theme, "copiar").isNull()


def test_theme_manager_switches_and_rebinds(app, tmp_path):
    from PySide6.QtWidgets import QLabel
    tm = ThemeManager(app, "hormigon", tmp_path)
    seen = []
    lb = QLabel()
    tm.bind(lb, lambda w, t: seen.append(t.id))
    assert app.styleSheet() and load_tokens()["themes"]["hormigon"]["colors"]["bg"] in app.styleSheet()
    tm.apply("noche")
    assert tm.theme.id == "noche" and tm.theme.is_dark
    assert load_tokens()["themes"]["noche"]["colors"]["bg"] in app.styleSheet()
    assert seen == ["hormigon", "noche"]
    tm.apply("no-existe")                       # unknown -> the brand default
    assert tm.theme.id == load_tokens()["default_theme"]
    lb.deleteLater()
