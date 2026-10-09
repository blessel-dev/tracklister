"""Pieces shared by several screens: preset texts, default folders, the preset chooser.

Owner: GUI step.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QRadioButton, QVBoxLayout, QWidget

from tracklister.gui.widgets import label

PRESETS = (
    ("lossless", "Lossless (recomendado)",
     "FLAC, WAV o AIFF. Si una pista solo está en MP3, te pregunto antes de bajarla en MP3 320."),
    ("cdj_antiguos", "CDJ antiguos",
     "Para CDJ anteriores al NXS2, que no leen FLAC: AIFF o WAV. Los FLAC se convierten a AIFF con el mismo "
     "sample rate y bits, tags y carátula (máximo 48 kHz/24 bit); el original se guarda en _originales."),
    ("solo_mp3_320", "Solo MP3 320",
     "MP3 de 320 kbps CBR, comprobado en la cabecera del archivo. El VBR no se acepta."),
    ("personalizado", "Personalizado", "Eliges tú los formatos y los límites (en Ajustes)."),
)
PRESET_LABEL_ES = {pid: name.replace(" (recomendado)", "") for pid, name, _ in PRESETS}


def default_library_root() -> Path:
    music = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MusicLocation)
    base = Path(music) if music else Path.home() / "Music"
    return base / "Tracklister"


def downloads_folder() -> Path:
    d = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
    return Path(d) if d else Path.home() / "Downloads"


class PresetChooser(QWidget):
    """Radio list of the four format presets, each with its one-line explanation."""

    changed = Signal(str)

    def __init__(self, current: str = "lossless", parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QRadioButton] = {}
        for pid, name, desc in PRESETS:
            rb = QRadioButton(name)
            rb.setAccessibleDescription(desc)
            self.group.addButton(rb)
            self.buttons[pid] = rb
            lay.addWidget(rb)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 6)
            row.addSpacing(24)
            row.addWidget(label(desc, "small", wrap=True), 1)
            lay.addLayout(row)
            rb.toggled.connect(lambda on, pid=pid: on and self.changed.emit(pid))
        self.set_value(current)

    def set_value(self, pid: str) -> None:
        (self.buttons.get(pid) or self.buttons["lossless"]).setChecked(True)

    def value(self) -> str:
        for pid, rb in self.buttons.items():
            if rb.isChecked():
                return pid
        return "lossless"
