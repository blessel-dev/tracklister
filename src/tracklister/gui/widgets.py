"""Shared widgets: header with the concrete texture, banners, drop zone, cards, state chips.

Owner: GUI step.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Iterable

from PySide6.QtCore import QEvent, QFileSystemWatcher, QMimeData, QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QIntValidator, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from tracklister.assets import asset_path
from tracklister.core.model import ResultState
from tracklister.gui.theme import Theme, ThemeManager, state_icon_rel, state_label_es, svg_pixmap

HEADER_HEIGHT = 64


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def label(text: str = "", role: str | None = None, *, wrap: bool = False, selectable: bool = False,
          mono: bool = False) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    if mono:
        lb.setProperty("mono", True)
    lb.setWordWrap(wrap)
    if selectable:
        lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lb


def button(text: str, kind: str | None = None, *, tooltip: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def card(title: str | None = None, subtitle: str | None = None, *, spacing: int = 8) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setProperty("card", True)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 16)
    lay.setSpacing(spacing)
    if title:
        lay.addWidget(label(title, "h2"))
    if subtitle:
        lay.addWidget(label(subtitle, "muted", wrap=True))
    return f, lay


def rule() -> QFrame:
    f = QFrame()
    f.setProperty("rule", True)
    return f


def scroll_page(body: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    body.setObjectName("PageBody")
    sa.setWidget(body)
    return sa


class Header(QWidget):
    """Concrete-texture band with the 'Tracklister by Blessel' lockup and the navigation."""

    def __init__(self, themes: ThemeManager, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(HEADER_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._texture: QPixmap | None = None
        self._line = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 16, 2)
        lay.setSpacing(4)
        self.lockup = QLabel()
        self.lockup.setAccessibleName("Tracklister by Blessel")
        self.lockup.setToolTip("Tracklister by Blessel")
        lay.addWidget(self.lockup, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addStretch(1)
        self.nav = QHBoxLayout()
        self.nav.setSpacing(4)
        lay.addLayout(self.nav)
        themes.bind(self, Header._apply_theme)

    def event(self, e) -> bool:  # noqa: D401 - Qt override
        # moving to a screen with another scale: pick the matching lockup again
        if e.type() == QEvent.Type.DevicePixelRatioChange and getattr(self, "_theme", None) is not None:
            self._apply_theme(self._theme)
        return super().event(e)

    def _apply_theme(self, theme: Theme) -> None:
        # the brand renders the lockup at 1x and 2x: use the one that matches the screen, never rescale text
        self._theme = theme
        hi = self.devicePixelRatioF() > 1.25
        pm = QPixmap(str(asset_path(theme.files["lockup_2x" if hi else "lockup"])))
        pm.setDevicePixelRatio(2.0 if hi else 1.0)
        self.lockup.setPixmap(pm)
        self.lockup.setFixedSize(pm.deviceIndependentSize().toSize())
        self._texture = QPixmap(str(asset_path(theme.files["header_texture"])))
        self._line = theme.qcolor("line_strong")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        r = self.rect()
        if self._texture is not None and not self._texture.isNull():
            tw, th = self._texture.width(), self._texture.height()
            target_ratio = r.width() / max(1, r.height())
            if tw / th > target_ratio:            # texture wider: crop the sides
                sw, sh = th * target_ratio, th
            else:                                 # crop top and bottom
                sw, sh = tw, tw / target_ratio
            src = QRectF((tw - sw) / 2, (th - sh) / 2, sw, sh)
            p.drawPixmap(QRectF(r), self._texture, src)
        if self._line is not None:
            p.fillRect(0, r.height() - 2, r.width(), 2, self._line)
        p.end()


class Banner(QFrame):
    """One-line notice: info / ok / warn / error, an optional icon, actions and a close button."""

    ICONS = {"ok": ResultState.VERIFICADO, "warn": ResultState.DUDOSO, "error": ResultState.FALLIDA}

    def __init__(self, themes: ThemeManager, parent: QWidget | None = None):
        super().__init__(parent)
        self.themes = themes
        self.kind = "info"
        self.setProperty("banner", "info")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 8, 8)
        lay.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(18, 18)
        self.text = label("", wrap=True, selectable=True)
        self.text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        self.close_btn = button("Cerrar", "ghost")
        self.close_btn.setAccessibleName("Cerrar aviso")
        self.close_btn.clicked.connect(self.hide)
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.text, 1)
        lay.addLayout(self.actions)
        lay.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        themes.bind(self, Banner._apply_theme)
        self.hide()

    def _apply_theme(self, theme: Theme) -> None:
        st = self.ICONS.get(self.kind)
        if st is None:
            self.icon.clear()
            self.icon.hide()
        else:
            self.icon.setPixmap(svg_pixmap(state_icon_rel(st), theme.state_color(st), 18, self.devicePixelRatioF()))
            self.icon.show()

    def show_message(self, text: str, kind: str = "info",
                     actions: Iterable[tuple[str, Callable[[], None]]] = (), closable: bool = True) -> None:
        self.kind = kind
        self.setProperty("banner", kind)
        self.text.setText(text)
        while self.actions.count():
            item = self.actions.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for text_, fn in actions:
            b = button(text_)
            # clicked(bool) must not reach fn: its default arguments (lambda url=...) would get False
            b.clicked.connect(lambda _checked=False, fn=fn: fn())
            self.actions.addWidget(b)
        self.close_btn.setVisible(closable)
        self._apply_theme(self.themes.theme)
        repolish(self)
        self.show()

    def message(self) -> str:
        return self.text.text() if self.isVisible() else ""


def source_from_mime(mime: QMimeData) -> str | None:
    """A dropped local file -> its path; a dropped web link -> the URL; plain text -> the text."""
    if mime.hasUrls():
        for url in mime.urls():
            if url.isLocalFile():
                return url.toLocalFile()
            if url.scheme() in ("http", "https"):
                return url.toString()
    if mime.hasText() and mime.text().strip():
        return mime.text()
    return None


class DropZone(QFrame):
    """Drop target for the trackid.net CSV, an Excel/CSV file or a dragged link."""

    dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setProperty("dragOver", False)
        self.setAccessibleName("Zona para soltar archivos")

    def _set_over(self, on: bool) -> None:
        self.setProperty("dragOver", on)
        repolish(self)

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if source_from_mime(e.mimeData()):
            e.acceptProposedAction()
            self._set_over(True)
        else:
            e.ignore()

    def dragMoveEvent(self, e) -> None:  # noqa: N802
        if source_from_mime(e.mimeData()):
            e.acceptProposedAction()

    def dragLeaveEvent(self, e) -> None:  # noqa: N802
        self._set_over(False)

    def dropEvent(self, e) -> None:  # noqa: N802
        self._set_over(False)
        src = source_from_mime(e.mimeData())
        if src:
            e.acceptProposedAction()
            self.dropped.emit(src)


class StateChips(QWidget):
    """Counts per state, each with its icon AND its label (never colour alone)."""

    def __init__(self, themes: ThemeManager, parent: QWidget | None = None):
        super().__init__(parent)
        self.themes = themes
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(16)
        self._counts: dict = {}
        themes.bind(self, lambda w, t: w._render())

    def set_counts(self, counts: dict) -> None:
        self._counts = dict(counts)
        self._render()

    def chips(self) -> list[str]:
        out = []
        for i in range(self.lay.count()):
            w = self.lay.itemAt(i).widget()
            if w is not None and w.property("chip"):
                out.append(w.property("chip"))
        return out

    def _render(self) -> None:
        while self.lay.count():
            item = self.lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        theme = self.themes.theme
        order = [ResultState.VERIFICADO, ResultState.YA_EN_BIBLIOTECA, ResultState.DUDOSO, ResultState.NO_ENCONTRADO,
                 ResultState.NO_CUMPLE_FORMATO, ResultState.FALLIDA, ResultState.EN_CURSO, ResultState.PENDIENTE,
                 ResultState.OMITIDA]
        for st in order:
            n = self._counts.get(st, 0)
            if not n:
                continue
            chip = QWidget()
            text = f"{state_label_es(st)} {n}"
            chip.setProperty("chip", text)
            chip.setAccessibleName(text)
            h = QHBoxLayout(chip)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            ic = QLabel()
            ic.setPixmap(svg_pixmap(state_icon_rel(st), theme.state_color(st), 16, self.devicePixelRatioF()))
            tx = QLabel(text)
            tx.setStyleSheet(f"color: {theme.state_color(st)}; font-weight: 600;")
            h.addWidget(ic)
            h.addWidget(tx)
            self.lay.addWidget(chip)
        self.lay.addStretch(1)


class DownloadsWatcher(QObject):
    """Watches the Downloads folder for NEW trackid.net CSV exports (DECISIONES B.4)."""

    found = Signal(str)

    def __init__(self, folder: Path, is_candidate: Callable[[Path], bool], parent: QObject | None = None):
        super().__init__(parent)
        self.folder = Path(folder)
        self.is_candidate = is_candidate
        self._seen: set[str] = set()
        self._since = time.time()
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._schedule)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(1200)       # let the browser finish renaming the download
        self._timer.timeout.connect(self.scan)

    def start(self) -> bool:
        self._since = time.time() - 2
        self._seen = {str(p) for p in self._csvs()}
        if self.folder.is_dir():
            return self._watcher.addPath(str(self.folder))
        return False

    def stop(self) -> None:
        paths = self._watcher.directories()
        if paths:
            self._watcher.removePaths(paths)
        self._timer.stop()

    def _csvs(self) -> list[Path]:
        try:
            return [p for p in self.folder.iterdir() if p.suffix.lower() == ".csv" and p.is_file()]
        except OSError:
            return []

    def _schedule(self, *_args) -> None:
        self._timer.start()

    def scan(self) -> None:
        for p in sorted(self._csvs()):
            key = str(p)
            if key in self._seen:
                continue
            try:
                if p.stat().st_mtime < self._since:
                    self._seen.add(key)
                    continue
            except OSError:
                continue
            self._seen.add(key)
            if self.is_candidate(p):
                self.found.emit(key)


class IntField(QLineEdit):
    """Whole-number field (port, row count). A QLineEdit, not a QSpinBox: the mouse wheel never
    changes it by accident while scrolling a page, and it styles cleanly with the QSS."""

    def __init__(self, value: int, lo: int, hi: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.lo, self.hi = int(lo), int(hi)
        self.setValidator(QIntValidator(self.lo, self.hi, self))
        self.setProperty("mono", True)
        self.setValue(value)

    def setValue(self, v: int) -> None:  # noqa: N802
        self.setText(str(max(self.lo, min(self.hi, int(v)))))

    def value(self) -> int:
        try:
            v = int(self.text().strip())
        except ValueError:
            return self.lo
        return max(self.lo, min(self.hi, v))


class SourcePicker(QFrame):
    """'Which tracklist?' box shared by Reordenar and Diagnostico."""

    use_table = Signal()
    open_file = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.summary = label("Sin tracklist.", "muted")
        self.btn_table = button("Usar la tabla de Nuevo set")
        self.btn_file = button("Abrir tracklist…")
        self.btn_table.clicked.connect(self.use_table)
        self.btn_file.clicked.connect(self.open_file)
        lay.addWidget(self.summary, 1)
        lay.addWidget(self.btn_table)
        lay.addWidget(self.btn_file)

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)


def page_layout(page: QWidget, title: str, subtitle: str | None = None) -> QVBoxLayout:
    """Standard page: title, muted subtitle, then the content (returned layout)."""
    page.setObjectName("Page")
    lay = QVBoxLayout(page)
    lay.setContentsMargins(28, 22, 28, 18)
    lay.setSpacing(12)
    page.page_title = label(title, "title")
    page.page_title.setWordWrap(True)
    lay.addWidget(page.page_title)
    if subtitle:
        lay.addWidget(label(subtitle, "muted", wrap=True))
    return lay
