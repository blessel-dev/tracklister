"""'Diagnóstico': search a few rows WITHOUT downloading and explain what Soulseek returned.

Owner: GUI step.
SPDX-License-Identifier: GPL-3.0-or-later

The report is built and REDACTED by tracklister.diagnostics (no own username/password/IP, peers as
peer-1, peer-2...). 'Copiar informe' copies exactly the text shown, for pasting back in the chat.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QAbstractSpinBox, QCheckBox, QHBoxLayout, QPlainTextEdit, QSpinBox, QWidget)

from tracklister.core.model import TrackRow
from tracklister.engine.credentials import CredentialError
from tracklister.gui.pages.common import downloads_folder
from tracklister.gui.widgets import Banner, SourcePicker, button, label, page_layout


class DiagnosticPage(QWidget):
    def __init__(self, window, parent: QWidget | None = None):
        super().__init__(parent)
        self.window = window
        self.services = window.services
        self.themes = window.themes
        self.rows: list[TrackRow] = []
        self.rows_from = ""
        self.task = None
        self.report = ""
        lay = page_layout(self, "Diagnóstico",
                          "Busca unas pocas pistas en Soulseek SIN descargarlas y explica qué candidatos aparecen "
                          "y por qué se aceptan o se rechazan. Úsalo en casa y pega el informe en el chat: no "
                          "lleva tu usuario, tu contraseña ni tu IP, y los demás usuarios salen como peer-1, "
                          "peer-2…")
        trow = QHBoxLayout()
        trow.addWidget(label("Tracklist"))
        self.source = SourcePicker()
        self.source.use_table.connect(self.use_table)
        self.source.open_file.connect(self.open_tracklist)
        trow.addWidget(self.source, 1)
        lay.addLayout(trow)

        orow = QHBoxLayout()
        orow.addWidget(label("Pistas que se buscan"))
        self.max_rows = QSpinBox()
        self.max_rows.setRange(1, 20)
        self.max_rows.setValue(5)
        self.max_rows.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.max_rows.setAccessibleName("Pistas que se buscan")
        self.max_rows.setFixedWidth(64)
        orow.addWidget(self.max_rows)
        orow.addSpacing(16)
        self.download = QCheckBox("Descargar también esas pistas (prueba completa, más lenta)")
        orow.addWidget(self.download)
        orow.addStretch(1)
        self.start_btn = button("Empezar diagnóstico", "primary")
        self.start_btn.clicked.connect(self.start)
        self.cancel_btn = button("Cancelar")
        self.cancel_btn.clicked.connect(self.cancel)
        self.cancel_btn.hide()
        orow.addWidget(self.cancel_btn)
        orow.addWidget(self.start_btn)
        lay.addLayout(orow)

        self.banner = Banner(self.themes)
        lay.addWidget(self.banner)
        self.status = label("", "small", wrap=True)
        lay.addWidget(self.status)
        self.box = QPlainTextEdit()
        self.box.setReadOnly(True)
        self.box.setProperty("mono", True)
        self.box.setAccessibleName("Informe del diagnóstico")
        self.box.setPlaceholderText("Aquí aparecerá el informe.")
        lay.addWidget(self.box, 1)
        foot = QHBoxLayout()
        self.saved = label("", "small", wrap=True, selectable=True)
        foot.addWidget(self.saved, 1)
        self.copy_btn = button("Copiar informe", "primary")
        self.themes.bind_icon(self.copy_btn, "copiar", "on_accent")
        self.copy_btn.clicked.connect(self.copy_report)
        foot.addWidget(self.copy_btn)
        lay.addLayout(foot)
        self._refresh()

    def _refresh(self) -> None:
        running = self.task is not None
        self.start_btn.setEnabled(bool(self.rows) and not running)
        self.cancel_btn.setVisible(running)
        self.copy_btn.setEnabled(bool(self.report))
        self.source.set_summary(f"{len(self.rows)} pistas ({self.rows_from})" if self.rows else
                                "Sin tracklist: usa la tabla de Nuevo set o abre un archivo.")

    def showEvent(self, e) -> None:  # noqa: N802
        if not self.rows and self.window.new_set.model.rowCount():
            self.use_table(quiet=True)
        super().showEvent(e)

    def set_tracklist(self, rows: list[TrackRow], origin: str) -> None:
        self.rows = [TrackRow.from_dict(r.to_dict()) for r in rows]
        self.rows_from = origin
        self._refresh()

    def use_table(self, quiet: bool = False) -> None:
        rows = self.window.new_set.model.rows()
        if not rows:
            if not quiet:
                self.banner.show_message("La tabla de Nuevo set está vacía: carga allí la tracklist primero.",
                                         "warn")
            return
        self.set_tracklist(rows, "tabla de Nuevo set")

    def open_tracklist(self) -> None:
        f = self.window.prompter.pick_file("Tracklist para el diagnóstico", str(downloads_folder()))
        if not f:
            return
        self.window.pool.start(lambda t: self.services.import_source(Path(f)),
                               on_ok=lambda res: self._on_imported(res, Path(f).name),
                               on_error=lambda m: self.banner.show_message(m, "error"))

    def _on_imported(self, result, name: str) -> None:
        rows = list(getattr(result, "rows", None) or [])
        if not rows:
            self.banner.show_message(getattr(result, "message_es", "") or "No he encontrado pistas.", "warn")
            return
        self.banner.hide()
        self.set_tracklist(rows, name)

    def start(self) -> None:
        if self.task is not None or not self.rows:
            return
        try:
            creds = self.services.get_credentials()
        except CredentialError as e:
            self.banner.show_message(e.msg_es, "error")
            return
        if creds is None:
            self.banner.show_message("Falta tu cuenta de Soulseek: añádela en Ajustes.", "error",
                                     actions=[("Ir a Ajustes", lambda: self.window.go("settings"))])
            return
        if self.window.worker_running():
            self.banner.show_message("Espera a que termine la descarga en curso.", "warn")
            return
        rows = [TrackRow.from_dict(r.to_dict()) for r in self.rows]
        download = self.download.isChecked()
        max_rows = int(self.max_rows.value())
        self.banner.hide()
        self.report = ""
        self.box.clear()
        self.saved.setText("")
        self.status.setText("Buscando en Soulseek…")

        def work(task):
            def on_event(ev):
                text = getattr(ev, "message_es", None) or getattr(ev, "text", None) or ""
                if text:
                    task.message.emit(text)
            return self.services.run_diagnostic(rows, creds, download=download, max_rows=max_rows,
                                                on_event=on_event, cancel=task.cancel)

        self.task = self.window.pool.start(work, on_ok=self._on_done, on_error=self._on_error,
                                           on_message=self.status.setText)
        self._refresh()

    def cancel(self) -> None:
        if self.task is not None:
            self.task.cancel.set()
            self.status.setText("Cancelando…")

    def _on_done(self, result) -> None:
        self.task = None
        report, path = result
        self.report = report
        self.box.setPlainText(report)
        self.status.setText("Terminado. Pulsa «Copiar informe» y pégalo en el chat.")
        self.saved.setText(f"Guardado también en {path}" if path else "")
        self._refresh()

    def _on_error(self, msg: str) -> None:
        self.task = None
        self.status.setText("")
        self.banner.show_message(msg, "error")
        self._refresh()

    def copy_report(self) -> None:
        if self.report:
            self.services.copy_text(self.report)
            self.window.status("Informe copiado: pégalo en el chat.")
