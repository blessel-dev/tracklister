"""'Primer inicio': the user's OWN Soulseek account, the library folder and the format preset.

Owner: GUI step.
SPDX-License-Identifier: GPL-3.0-or-later

The account goes straight to Windows Credential Manager (engine.credentials); settings.json only
gets the folder, the preset, the port and the 'done' flags. Nothing is tested against Soulseek
here: the first download (or Diagnostico) shows a clear message if the login fails.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QHBoxLayout, QLineEdit, QSpinBox, QAbstractSpinBox,
                               QVBoxLayout, QWidget)

from tracklister import config
from tracklister.engine.credentials import CredentialError
from tracklister.gui.pages.common import PresetChooser, default_library_root
from tracklister.gui.widgets import button, card, label, repolish, scroll_page

SHARE_NOTICE = ("Tracklister descarga en modo honesto: no anuncia en Soulseek carpetas compartidas que no "
                "tienes. Soulseek funciona porque la gente comparte, así que cuando no uses Tracklister "
                "comparte tu música con Nicotine+. Si usas los dos a la vez, pon otra cuenta en Nicotine+.")
LEGAL_NOTICE = ("Descarga solo música que tengas derecho a descargar. Tracklister no incluye ninguna cuenta: "
                "cada persona usa la suya, y eres responsable de lo que descargas y compartes.")
PORT_HELP = ("Si las descargas no arrancan, abre este puerto TCP en el router hacia este PC y permite "
             "Tracklister en el Firewall de Windows (redes privadas). Si un amigo usa Tracklister en tu misma "
             "red, usad puertos distintos.")


class FirstRunPage(QWidget):
    completed = Signal()

    def __init__(self, window, parent: QWidget | None = None):
        super().__init__(parent)
        self.window = window
        self.services = window.services
        s = self.services.settings
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        outer.addWidget(scroll_page(body))
        col = QHBoxLayout(body)
        col.setContentsMargins(28, 22, 28, 22)
        col.addStretch(1)
        inner = QWidget()
        inner.setMaximumWidth(820)
        inner.setMinimumWidth(560)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        col.addWidget(inner, 4)
        col.addStretch(1)

        lay.addWidget(label("Bienvenido a Tracklister", "title"))
        lay.addWidget(label("De una tracklist a una carpeta ordenada de música verificada. Tres datos y "
                            "listo: todo se guarda solo en este PC.", "muted", wrap=True))

        # 1. Account
        c1, l1 = card("1. Tu cuenta de Soulseek",
                      "Se guarda en el Administrador de credenciales de Windows, nunca en un archivo. Si aún no "
                      "tienes cuenta, elige un usuario y una contraseña nuevos: Soulseek la crea la primera vez "
                      "que conectas. Usa tu propia cuenta: Tracklister no trae ninguna.")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(14)
        self.user = QLineEdit()
        self.user.setPlaceholderText("tu usuario de Soulseek")
        self.user.setAccessibleName("Usuario de Soulseek")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("tu contraseña")
        self.password.setAccessibleName("Contraseña de Soulseek")
        self.show_pw = QCheckBox("Mostrar")
        self.show_pw.toggled.connect(lambda on: self.password.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        pw_row = QHBoxLayout()
        pw_row.addWidget(self.password, 1)
        pw_row.addWidget(self.show_pw)
        form.addRow("Usuario", self.user)
        form.addRow("Contraseña", pw_row)
        l1.addLayout(form)
        lay.addWidget(c1)

        # 2. Folder
        c2, l2 = card("2. Carpeta de tu biblioteca",
                      "Aquí se crea una carpeta por set, con los archivos numerados en el orden de la tracklist.")
        row = QHBoxLayout()
        self.folder = QLineEdit(s.library_root or str(default_library_root()))
        self.folder.setAccessibleName("Carpeta de la biblioteca")
        pick = button("Elegir…")
        pick.clicked.connect(self._pick_folder)
        row.addWidget(self.folder, 1)
        row.addWidget(pick)
        l2.addLayout(row)
        lay.addWidget(c2)

        # 3. Preset
        c3, l3 = card("3. Formato", "Puedes cambiarlo cuando quieras en Ajustes.")
        self.preset = PresetChooser(s.preset_id)
        l3.addWidget(self.preset)
        lay.addWidget(c3)

        # Network
        c4, l4 = card("Red")
        prow = QHBoxLayout()
        prow.addWidget(label("Puerto de escucha"))
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(int(s.listen_port or config.DEFAULT_LISTEN_PORT))
        self.port.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.port.setAccessibleName("Puerto de escucha")
        self.port.setProperty("mono", True)
        self.port.setFixedWidth(110)
        prow.addWidget(self.port)
        prow.addStretch(1)
        l4.addLayout(prow)
        l4.addWidget(label(PORT_HELP, "small", wrap=True))
        lay.addWidget(c4)

        # Notices
        c5, l5 = card("Antes de empezar")
        l5.addWidget(label(SHARE_NOTICE, wrap=True))
        l5.addWidget(label(LEGAL_NOTICE, wrap=True))
        self.accept_box = QCheckBox("Entendido")
        self.accept_box.setChecked(bool(s.legal_notice_accepted))
        l5.addWidget(self.accept_box)
        lay.addWidget(c5)

        self.error = label("", "error", wrap=True)
        self.error.hide()
        lay.addWidget(self.error)
        foot = QHBoxLayout()
        foot.addStretch(1)
        self.start_btn = button("Empezar", "primary")
        self.start_btn.clicked.connect(self.submit)
        foot.addWidget(self.start_btn)
        lay.addLayout(foot)
        lay.addStretch(1)

    def focus_default(self) -> None:
        self.user.setFocus()

    def _pick_folder(self) -> None:
        d = self.window.prompter.pick_folder("Carpeta de tu biblioteca", self.folder.text())
        if d:
            self.folder.setText(str(Path(d)))

    def _fail(self, text: str, widget: QWidget | None = None) -> None:
        self.error.setText(text)
        self.error.show()
        for w in (self.user, self.password, self.folder):
            w.setProperty("invalid", w is widget)
            repolish(w)
        if widget is not None:
            widget.setFocus()

    def submit(self) -> bool:
        user, pw, folder = self.user.text().strip(), self.password.text(), self.folder.text().strip()
        if not user:
            self._fail("Escribe tu usuario de Soulseek.", self.user)
            return False
        if not pw:
            self._fail("Escribe tu contraseña de Soulseek.", self.password)
            return False
        if not folder:
            self._fail("Elige la carpeta de tu biblioteca.", self.folder)
            return False
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._fail(f"No se puede crear esa carpeta ({e.strerror or e}). Elige otra.", self.folder)
            return False
        if not self.accept_box.isChecked():
            self._fail("Marca «Entendido» para continuar.", None)
            self.accept_box.setFocus()
            return False
        try:
            self.services.save_credentials(user, pw)
        except CredentialError as e:
            self._fail(e.msg_es, None)
            return False
        s = self.services.settings
        s.library_root = str(Path(folder))
        s.preset_id = self.preset.value()
        s.listen_port = int(self.port.value())
        s.first_run_done = True
        s.share_notice_shown = True
        s.legal_notice_accepted = True
        self.services.save_settings()
        self.password.clear()
        self.error.hide()
        self.completed.emit()
        return True
