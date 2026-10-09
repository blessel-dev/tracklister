"""Dialogs: track already in the library, the lossy checklist, and the Prompter used by pages.

Owner: GUI step.
SPDX-License-Identifier: GPL-3.0-or-later

The Prompter is the only place that opens modal windows or file pickers; the tests swap it for a
scripted one (tests/gui/fakes.py), so no test ever blocks on a modal loop.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from tracklister.core.model import DuplicateChoice, LibraryEntry, ResultState, TrackRow
from tracklister.gui.models import fmt_clock, track_label
from tracklister.gui.theme import Theme, state_icon_rel, svg_pixmap
from tracklister.gui.widgets import button, label

REUSE_TEXT = "Usar el que ya tengo (copiar a este set)"
DOWNLOAD_TEXT = "Descargar de nuevo en este set"
APPLY_ALL_TEXT = "Aplicar a todos los repetidos de este set"


def _entry_text(e: LibraryEntry) -> str:
    bits = [f"set «{e.set_name}», pista {e.pos:02d}"]
    if e.format:
        bits.append(e.format.upper())
    if e.duration_s:
        bits.append(fmt_clock(e.duration_s))
    return " · ".join(bits)


class DuplicateDialog(QDialog):
    """A track of this set already exists in a previous set: ask EVERY time, both options."""

    def __init__(self, hit, theme: Theme, *, index: int = 1, total: int = 1, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Ya tienes esta pista")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.hit = hit
        self.choice: DuplicateChoice | None = None
        row: TrackRow = hit.row
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(svg_pixmap(state_icon_rel(ResultState.YA_EN_BIBLIOTECA),
                                theme.state_color(ResultState.YA_EN_BIBLIOTECA), 20, self.devicePixelRatioF()))
        head.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        self.title = label(f"{row.pos:02d}. {track_label(row)}", "h2", wrap=True)
        head.addWidget(self.title, 1)
        lay.addLayout(head)
        entries: list[LibraryEntry] = list(hit.entries)
        if len(entries) == 1:
            lay.addWidget(label(f"Ya está en tu biblioteca: {_entry_text(entries[0])}.", wrap=True))
        else:
            lay.addWidget(label(f"Ya está {len(entries)} veces en tu biblioteca. ¿Cuál uso?", wrap=True))
        self.entry_box = QComboBox()
        self.entry_box.setAccessibleName("Copia de la biblioteca")
        for e in entries:
            self.entry_box.addItem(_entry_text(e))
        self.entry_box.setVisible(len(entries) > 1)
        lay.addWidget(self.entry_box)
        self.path = label(entries[0].path if entries else "", "small", wrap=True, selectable=True, mono=True)
        self.entry_box.currentIndexChanged.connect(lambda i: self.path.setText(entries[i].path if entries else ""))
        lay.addWidget(self.path)
        lay.addWidget(label("¿Qué hago en este set?", "muted"))
        btns = QHBoxLayout()
        self.reuse_btn = button(REUSE_TEXT, "primary")
        self.download_btn = button(DOWNLOAD_TEXT)
        self.reuse_btn.clicked.connect(lambda: self._done(DuplicateChoice.REUSE))
        self.download_btn.clicked.connect(lambda: self._done(DuplicateChoice.DOWNLOAD))
        btns.addWidget(self.reuse_btn)
        btns.addWidget(self.download_btn)
        btns.addStretch(1)
        lay.addLayout(btns)
        self.apply_all = QCheckBox(APPLY_ALL_TEXT)
        self.apply_all.setVisible(total > 1)
        lay.addWidget(self.apply_all)
        if total > 1:
            lay.addWidget(label(f"Repetida {index} de {total} en este set.", "small"))
        self.reuse_btn.setDefault(True)

    def entry(self) -> LibraryEntry | None:
        entries = list(self.hit.entries)
        if not entries:
            return None
        return entries[max(0, self.entry_box.currentIndex())]

    def _done(self, choice: DuplicateChoice) -> None:
        self.choice = choice
        self.accept()

    def result_tuple(self) -> tuple[DuplicateChoice, LibraryEntry | None, bool] | None:
        if self.choice is None:
            return None
        return self.choice, (self.entry() if self.choice == DuplicateChoice.REUSE else None), \
            self.apply_all.isChecked()


def lossless_words(preset) -> str:
    """'FLAC, WAV ni AIFF' from the non-lossy passes of a preset."""
    seen: list[str] = []
    for p in getattr(preset, "passes", ()):
        if p.lossy:
            continue
        for f in p.formats:
            f = "AIFF" if f in ("aif", "aiff") else f.upper()
            if f not in seen:
                seen.append(f)
    if not seen:
        return "lossless"
    return seen[0] if len(seen) == 1 else ", ".join(seen[:-1]) + " ni " + seen[-1]


def lossy_kbps(preset) -> int:
    for p in getattr(preset, "passes", ()):
        if p.lossy and p.min_bitrate:
            return int(p.min_bitrate)
    return 320


class LossyDialog(QDialog):
    """Asked once per set: which of these missing tracks may fall back to MP3 320."""

    def __init__(self, rows: list[TrackRow], preset, parent: QWidget | None = None):
        super().__init__(parent)
        kbps = lossy_kbps(preset)
        self.setWindowTitle(f"¿Buscar en MP3 {kbps}?")
        self.setModal(True)
        self.setMinimumSize(560, 380)
        self.rows = list(rows)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        lay.addWidget(label(f"Estas pistas no están en {lossless_words(preset)}", "h2", wrap=True))
        lay.addWidget(label(f"¿Las busco en MP3 {kbps} kbps? Solo se buscan las marcadas. El MP3 se comprueba "
                            "en la cabecera del archivo (CBR, sin VBR).", "muted", wrap=True))
        self.list = QListWidget()
        self.list.setAccessibleName("Pistas que se buscarían en MP3")
        for r in self.rows:
            it = QListWidgetItem(f"{r.pos:02d}. {track_label(r)}")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            it.setData(Qt.ItemDataRole.UserRole, r.uid)
            self.list.addItem(it)
        lay.addWidget(self.list, 1)
        sel = QHBoxLayout()
        all_btn = button("Marcar todas")
        none_btn = button("Desmarcar todas")
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn.clicked.connect(lambda: self._set_all(False))
        sel.addWidget(all_btn)
        sel.addWidget(none_btn)
        sel.addStretch(1)
        lay.addLayout(sel)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.no_btn = button("No, dejarlas sin descargar")
        self.yes_btn = button(f"Buscar en MP3 {kbps} las marcadas", "primary")
        self.no_btn.clicked.connect(self.reject)
        self.yes_btn.clicked.connect(self.accept)
        btns.addWidget(self.no_btn)
        btns.addWidget(self.yes_btn)
        lay.addLayout(btns)
        self.yes_btn.setDefault(True)

    def _set_all(self, on: bool) -> None:
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def checked_uids(self) -> set[str]:
        out = set()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.add(it.data(Qt.ItemDataRole.UserRole))
        return out


class Prompter:
    """Every modal question of the window. Pages call these; tests replace the whole object."""

    def __init__(self, parent: QWidget, theme_provider):
        self.parent = parent
        self.theme_provider = theme_provider

    def _box(self, icon, title: str, text: str) -> QMessageBox:
        box = QMessageBox(icon, title, text, QMessageBox.StandardButton.NoButton, self.parent)
        box.setTextFormat(Qt.TextFormat.PlainText)
        return box

    def inform(self, title: str, text: str) -> None:
        box = self._box(QMessageBox.Icon.Information, title, text)
        box.addButton("Aceptar", QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    def error(self, title: str, text: str) -> None:
        box = self._box(QMessageBox.Icon.Warning, title, text)
        box.addButton("Aceptar", QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    def confirm(self, title: str, text: str, ok: str = "Sí", cancel: str = "Cancelar") -> bool:
        box = self._box(QMessageBox.Icon.Question, title, text)
        yes = box.addButton(ok, QMessageBox.ButtonRole.AcceptRole)
        box.addButton(cancel, QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(yes)
        box.exec()
        return box.clickedButton() is yes

    def choose(self, title: str, text: str, options: list[str]) -> int | None:
        """Buttons in order; returns the index pressed, or None (Escape/close)."""
        box = self._box(QMessageBox.Icon.Question, title, text)
        btns: list[QPushButton] = [box.addButton(o, QMessageBox.ButtonRole.ActionRole) for o in options]
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        return btns.index(clicked) if clicked in btns else None

    def pick_folder(self, title: str, start: str | None = None) -> str | None:
        d = QFileDialog.getExistingDirectory(self.parent, title, start or str(Path.home()))
        return d or None

    def pick_file(self, title: str, start: str | None = None,
                  filters: str = "Tracklists (*.csv *.CSV *.xlsx *.xlsm *.txt);;Todos los archivos (*)") -> str | None:
        f, _ = QFileDialog.getOpenFileName(self.parent, title, start or str(Path.home()), filters)
        return f or None

    def ask_duplicate(self, hit, index: int, total: int):
        dlg = DuplicateDialog(hit, self.theme_provider(), index=index, total=total, parent=self.parent)
        dlg.exec()
        return dlg.result_tuple()

    def ask_lossy(self, rows: list[TrackRow], preset) -> set[str]:
        dlg = LossyDialog(rows, preset, parent=self.parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.checked_uids()
        return set()
