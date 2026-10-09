"""Brand tokens -> Qt: palette, style sheet (QSS), fonts and tinted SVG icons.

Owner: GUI step.
SPDX-License-Identifier: GPL-3.0-or-later

Everything visual comes from tracklister.assets (tokens.json plus the files it names). The GUI
never hard-codes a colour: build_qss() and build_palette() read the theme tokens, and the
monochrome SVG icons (one path, fill #000000) are tinted at runtime with CompositionMode_SourceIn.
States always get an icon AND a text label, never colour alone.
"""
from __future__ import annotations

import weakref
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Callable

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QImage, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

from tracklister.assets import asset_path, load_tokens
from tracklister.core.model import ResultState

THEME_LABELS_ES = {"hormigon": "Hormigón (claro)", "noche": "Noche (oscuro)"}
ICON_PIXEL_SIZES = (16, 20, 24, 32, 40, 48, 64)
_FILE_KEYS = ("logo", "logo_2x", "lockup", "lockup_2x", "wordmark", "wordmark_2x", "header_texture")


@dataclass(frozen=True)
class Theme:
    id: str
    label_es: str
    colors: dict
    files: dict
    type_scale: dict
    ui_family: str = "Inter"
    mono_family: str = "JetBrains Mono"

    def color(self, key: str) -> str:
        return self.colors[key]

    def qcolor(self, key: str) -> QColor:
        return QColor(self.colors[key])

    def state_color(self, state: ResultState | str) -> str:
        return self.colors[f"state_{ResultState(state).value}"]

    def px(self, step: str) -> int:
        return int(self.type_scale[step])

    @property
    def is_dark(self) -> bool:
        return QColor(self.colors["bg"]).lightnessF() < 0.5


def theme_ids() -> list[str]:
    return list(load_tokens()["themes"])


def default_theme_id() -> str:
    return str(load_tokens()["default_theme"])


def load_theme(theme_id: str | None, families: dict[str, str] | None = None) -> Theme:
    tok = load_tokens()
    tid = theme_id if theme_id in tok["themes"] else tok["default_theme"]
    t = tok["themes"][tid]
    fams = families or {}
    return Theme(id=tid, label_es=THEME_LABELS_ES.get(tid, t.get("label_es", tid)), colors=dict(t["colors"]),
                 files={k: t[k] for k in _FILE_KEYS if k in t}, type_scale=dict(tok["type_scale_px"]),
                 ui_family=fams.get("ui", tok["fonts"]["ui"]["family"]),
                 mono_family=fams.get("mono", tok["fonts"]["mono"]["family"]))


# ---- fonts --------------------------------------------------------------------------------
_FAMILIES: dict[str, str] = {}


def register_fonts() -> dict[str, str]:
    """Register the bundled OFL fonts with Qt (idempotent; needs a QGuiApplication).

    Returns {"ui": family, "mono": family}. Must run before widgets are created, so the
    headless screenshots never fall back to a system font.
    """
    if _FAMILIES:
        return dict(_FAMILIES)
    tok = load_tokens()
    for key, fam in tok["fonts"].items():
        family = fam["family"]
        for rel in fam["files"]:
            fid = QFontDatabase.addApplicationFont(str(asset_path(rel)))
            if fid >= 0:
                names = QFontDatabase.applicationFontFamilies(fid)
                if names:
                    family = names[0]
        _FAMILIES[key] = family
    return dict(_FAMILIES)


def ui_font(theme: Theme, step: str = "base", *, weight: QFont.Weight | None = None) -> QFont:
    f = QFont(theme.ui_family)
    f.setPixelSize(theme.px(step))
    if weight is not None:
        f.setWeight(weight)
    return f


def mono_font(theme: Theme, step: str = "sm") -> QFont:
    f = QFont(theme.mono_family)
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPixelSize(theme.px(step))
    return f


# ---- tinted SVG icons -----------------------------------------------------------------------
_PIXMAPS: dict[tuple, QPixmap] = {}


def svg_pixmap(rel: str, color: str, size: int, dpr: float = 1.0) -> QPixmap:
    """Render a monochrome asset SVG at `size` logical px and tint it with `color`."""
    key = (rel, color, int(size), round(float(dpr), 2))
    pm = _PIXMAPS.get(key)
    if pm is not None:
        return pm
    n = max(1, int(round(size * dpr)))
    img = QImage(n, n, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(str(asset_path(rel)))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(p, QRectF(0, 0, n, n))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(img.rect(), QColor(color))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    _PIXMAPS[key] = pm
    return pm


_ICONS: dict[tuple, QIcon] = {}


def tinted_icon(rel: str, color: str, disabled_color: str | None = None) -> QIcon:
    """QIcon with every pixel size rendered directly. The Selected mode reuses the same tint so
    a selected table row keeps the state colour (>= 3:1 on `selection`, see the brand doc)."""
    key = (rel, color, disabled_color)
    cached = _ICONS.get(key)
    if cached is not None:
        return cached
    icon = QIcon()
    for s in ICON_PIXEL_SIZES:
        pm = svg_pixmap(rel, color, s)
        for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected):
            icon.addPixmap(pm, mode)
        if disabled_color:
            icon.addPixmap(svg_pixmap(rel, disabled_color, s), QIcon.Mode.Disabled)
    _ICONS[key] = icon
    return icon


def state_icon_rel(state: ResultState | str) -> str:
    return load_tokens()["states"][ResultState(state).value]["icon"]


def state_label_es(state: ResultState | str) -> str:
    return load_tokens()["states"][ResultState(state).value]["label_es"]


def state_icon(theme: Theme, state: ResultState | str) -> QIcon:
    return tinted_icon(state_icon_rel(state), theme.state_color(state))


def ui_icon(theme: Theme, name: str, color_key: str = "ink") -> QIcon:
    rel = load_tokens()["ui_icons"][name]
    return tinted_icon(rel, theme.color(color_key), theme.color("disabled_ink"))


# ---- palette and style sheet --------------------------------------------------------------
def build_palette(theme: Theme) -> QPalette:
    c = theme.qcolor
    pal = QPalette()
    R = QPalette.ColorRole
    for role, key in ((R.Window, "bg"), (R.WindowText, "ink"), (R.Base, "surface"), (R.AlternateBase, "surface_alt"),
                      (R.Text, "ink"), (R.Button, "surface"), (R.ButtonText, "ink"), (R.Highlight, "selection"),
                      (R.HighlightedText, "on_selection"), (R.ToolTipBase, "ink"), (R.ToolTipText, "bg"),
                      (R.PlaceholderText, "ink_muted"), (R.Link, "accent"), (R.LinkVisited, "accent"),
                      (R.BrightText, "on_accent"), (R.Light, "surface"), (R.Midlight, "surface_alt"),
                      (R.Mid, "line"), (R.Dark, "line_strong"), (R.Shadow, "line_strong")):
        pal.setColor(role, c(key))
    for role in (R.Text, R.WindowText, R.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, c("disabled_ink"))
    return pal


def indicator_files(theme: Theme, out_dir: Path) -> dict[str, str]:
    """Small SVGs the QSS needs (check mark, radio dot, combo chevron), in the theme colours.

    They live in the per-user cache (the assets folder is hashed by the brand manifest)."""
    c = theme.colors
    svgs = {
        "check": ('<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14">'
                  f'<path fill="none" stroke="{c["surface"]}" stroke-width="2" stroke-linecap="square" '
                  'd="M3.4 7.3 5.9 9.8 10.6 4.3"/></svg>'),
        "radio": ('<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14">'
                  f'<circle cx="7" cy="7" r="3.2" fill="{c["ink"]}"/></svg>'),
        "chevron": ('<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
                    f'<path fill="none" stroke="{c["ink"]}" stroke-width="1.6" d="M2 4.3 6 8.3 10 4.3"/></svg>'),
        "chevron_off": ('<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
                        f'<path fill="none" stroke="{c["disabled_ink"]}" stroke-width="1.6" d="M2 4.3 6 8.3 10 4.3"/>'
                        '</svg>'),
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, svg in svgs.items():
        p = out_dir / f"{name}-{theme.id}.svg"
        try:
            if not p.is_file() or p.read_text(encoding="utf-8") != svg:
                p.write_text(svg, encoding="utf-8")
        except OSError:
            pass
        files[name] = p.resolve().as_posix()
    return files


_QSS = Template("""
QWidget { color: $ink; }
QMainWindow, QDialog, QWidget#Page, QWidget#PageBody, QStackedWidget#Pages { background: $bg; }
QScrollArea { background: $bg; border: none; }
QScrollArea > QWidget > QWidget#PageBody { background: $bg; }
QLabel { background: transparent; }
QLabel[role="title"] { font-size: ${xl}px; font-weight: 700; }
QLabel[role="h2"] { font-size: ${md}px; font-weight: 700; }
QLabel[role="muted"] { color: $ink_muted; }
QLabel[role="small"] { color: $ink_muted; font-size: ${sm}px; }
QLabel[role="error"] { color: $state_fallida; font-weight: 600; }
QLabel[role="ok"] { color: $state_verificado; font-weight: 600; }
QLabel[mono="true"], QPlainTextEdit[mono="true"], QLineEdit[mono="true"], QSpinBox[mono="true"] {
    font-family: "$mono_family"; }
QFrame[card="true"] { background: $surface; border: 1px solid $line; }
QFrame[card="true"] QLabel, QFrame[card="true"] QCheckBox, QFrame[card="true"] QRadioButton { background: transparent; }
QFrame[rule="true"] { background: $line; border: none; max-height: 1px; min-height: 1px; }
QFrame#DropZone { background: $surface; border: 2px dashed $line_strong; }
QFrame#DropZone[dragOver="true"] { background: $surface_alt; border: 2px solid $accent; }
QFrame[banner="info"], QFrame[banner="ok"], QFrame[banner="warn"], QFrame[banner="error"] {
    background: $surface; border: 1px solid $line; }
QFrame[banner="info"] { border-left: 4px solid $accent; }
QFrame[banner="ok"] { border-left: 4px solid $state_verificado; }
QFrame[banner="warn"] { border-left: 4px solid $state_dudoso; }
QFrame[banner="error"] { border-left: 4px solid $state_fallida; }

QPushButton { background: $surface; color: $ink; border: 1px solid $line_strong; padding: 6px 14px;
    min-height: 18px; }
QPushButton:hover { background: $surface_alt; }
QPushButton:pressed { background: $line; }
QPushButton:focus { border: 2px solid $focus; padding: 5px 13px; }
QPushButton:disabled { color: $disabled_ink; border: 1px solid $line; background: $surface; padding: 6px 14px; }
QPushButton[kind="primary"] { background: $accent; color: $on_accent; border: 1px solid $accent; font-weight: 700; }
QPushButton[kind="primary"]:hover { background: $ink; color: $bg; border: 1px solid $ink; }
QPushButton[kind="primary"]:focus { border: 2px solid $ink; padding: 5px 13px; }
QPushButton[kind="primary"]:disabled { background: $surface_alt; color: $disabled_ink; border: 1px solid $line; }
QPushButton[kind="nav"] { background: transparent; color: $ink; border: 1px solid transparent; padding: 6px 12px;
    font-weight: 600; }
QPushButton[kind="nav"]:hover { border: 1px solid $line_strong; }
QPushButton[kind="nav"]:focus { border: 2px solid $focus; padding: 5px 11px; }
QPushButton[kind="nav"]:checked { background: $ink; color: $bg; border: 1px solid $ink; }
QPushButton[kind="nav"]:disabled { color: $disabled_ink; border: 1px solid transparent; background: transparent; }
QPushButton[kind="link"] { background: transparent; border: none; color: $accent; padding: 2px 4px;
    text-decoration: underline; }
QPushButton[kind="link"]:focus { border: 1px solid $focus; padding: 1px 3px; }
QPushButton[kind="ghost"] { background: transparent; border: 1px solid transparent; padding: 2px 8px; }
QPushButton[kind="ghost"]:hover { border: 1px solid $line_strong; }

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox { background: $surface; color: $ink;
    border: 1px solid $line_strong; padding: 5px 8px; selection-background-color: $selection;
    selection-color: $on_selection; }
QPlainTextEdit, QTextEdit { padding: 6px; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border: 2px solid $focus; padding: 4px 7px; }
QPlainTextEdit:focus, QTextEdit:focus { border: 2px solid $focus; padding: 5px; }
QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QComboBox:disabled { color: $disabled_ink;
    border: 1px solid $line; }
QLineEdit:read-only { background: $surface_alt; }
QLineEdit[invalid="true"] { border: 2px solid $state_fallida; padding: 4px 7px; }
QAbstractSpinBox QLineEdit, QComboBox QLineEdit, QAbstractSpinBox QLineEdit:focus, QComboBox QLineEdit:focus {
    background: transparent; border: none; padding: 0px; margin: 0px; }
QSpinBox { min-height: 20px; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: url("$chevron"); width: 12px; height: 12px; }
QComboBox::down-arrow:disabled { image: url("$chevron_off"); }
QComboBox QAbstractItemView { background: $surface; color: $ink; border: 1px solid $line_strong;
    selection-background-color: $selection; selection-color: $on_selection; outline: none; }

QCheckBox, QRadioButton { spacing: 8px; background: transparent; }
QCheckBox:disabled, QRadioButton:disabled { color: $disabled_ink; }
QCheckBox::indicator, QTableView::indicator, QListView::indicator { width: 14px; height: 14px;
    border: 1px solid $line_strong; background: $surface; }
QCheckBox::indicator:checked, QTableView::indicator:checked, QListView::indicator:checked {
    background: $ink; border: 1px solid $ink; image: url("$check"); }
QCheckBox::indicator:focus { border: 2px solid $focus; }
QCheckBox::indicator:disabled, QTableView::indicator:disabled { border: 1px solid $line; background: $surface_alt; }
QRadioButton::indicator { width: 14px; height: 14px; border: 1px solid $line_strong; border-radius: 8px;
    background: $surface; }
QRadioButton::indicator:checked { image: url("$radio"); }
QRadioButton::indicator:focus { border: 2px solid $focus; }

QTableView, QListView, QListWidget { background: $surface; alternate-background-color: $surface_alt; color: $ink;
    gridline-color: $line; border: 1px solid $line_strong; selection-background-color: $selection;
    selection-color: $on_selection; outline: none; }
QTableView:focus, QListView:focus { border: 1px solid $focus; }
QListView::item, QListWidget::item { padding: 4px 6px; }
QHeaderView { background: $surface_alt; border: none; }
QHeaderView::section { background: $surface_alt; color: $ink; border: none; border-right: 1px solid $line;
    border-bottom: 2px solid $line_strong; padding: 6px 8px; font-weight: 700; }
QTableCornerButton::section { background: $surface_alt; border: none; border-bottom: 2px solid $line_strong; }

QProgressBar { background: $surface; border: 1px solid $line_strong; min-height: 10px; max-height: 10px;
    text-align: center; color: $ink; }
QProgressBar::chunk { background: $accent; }

QScrollBar:vertical { background: $surface; width: 12px; margin: 0; border-left: 1px solid $line; }
QScrollBar:horizontal { background: $surface; height: 12px; margin: 0; border-top: 1px solid $line; }
QScrollBar::handle:vertical { background: $line; min-height: 28px; }
QScrollBar::handle:horizontal { background: $line; min-width: 28px; }
QScrollBar::handle:hover { background: $ink_muted; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; background: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

QToolTip { background: $ink; color: $bg; border: 1px solid $ink; padding: 4px 6px; }
QStatusBar { background: $surface_alt; color: $ink; border-top: 1px solid $line; }
QStatusBar QLabel { color: $ink; }
QMenu { background: $surface; color: $ink; border: 1px solid $line_strong; }
QMenu::item:selected { background: $selection; color: $on_selection; }
QSplitter::handle { background: $line; }
QMessageBox { background: $bg; }
""")


def build_qss(theme: Theme, indicator: dict[str, str]) -> str:
    values = dict(theme.colors)
    values.update({k: str(v) for k, v in theme.type_scale.items()})
    values.update(indicator)
    values["mono_family"] = theme.mono_family
    return _QSS.substitute(values)


class ThemeManager(QObject):
    """Applies a theme to the whole app and re-themes bound widgets when it changes."""

    changed = Signal(object)   # Theme

    def __init__(self, app, theme_id: str | None, cache_dir: Path, parent: QObject | None = None):
        super().__init__(parent)
        self.app = app
        self.cache_dir = Path(cache_dir)
        self.theme: Theme = load_theme(theme_id)
        self._bindings: list[tuple[weakref.ref, Callable]] = []
        self.apply(theme_id)

    def apply(self, theme_id: str | None) -> Theme:
        fams = register_fonts()
        theme = load_theme(theme_id, fams)
        files = indicator_files(theme, self.cache_dir)
        font = ui_font(theme)
        self.app.setFont(font)
        self.app.setPalette(build_palette(theme))
        self.app.setStyleSheet(build_qss(theme, files))
        self.theme = theme
        alive = []
        for ref, fn in self._bindings:
            w = ref()
            if w is None:
                continue
            try:
                fn(w, theme)
            except RuntimeError:      # the C++ widget is gone
                continue
            alive.append((ref, fn))
        self._bindings = alive
        self.changed.emit(theme)
        return theme

    def bind(self, widget, fn: Callable) -> None:
        """Call fn(widget, theme) now and after every theme change, while the widget lives."""
        self._bindings.append((weakref.ref(widget), fn))
        fn(widget, self.theme)

    def bind_icon(self, button, name: str, color_key: str = "ink") -> None:
        self.bind(button, lambda b, t: b.setIcon(ui_icon(t, name, color_key)))

    def bind_state_icon(self, label, state: ResultState, px: int = 16) -> None:
        self.bind(label, lambda w, t: w.setPixmap(svg_pixmap(state_icon_rel(state), t.state_color(state), px,
                                                              w.devicePixelRatioF())))
