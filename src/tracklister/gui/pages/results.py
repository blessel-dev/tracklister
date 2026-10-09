"""'Descargando' / 'Resultados': per-track states, progress, 'Reintentar fallos', 'Copiar tracklist'.

Owner: GUI step.
SPDX-License-Identifier: GPL-3.0-or-later

While a run is going the page only reads the snapshots carried by the worker's signals; the
session document itself is read again when the worker has finished.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QPlainTextEdit, QProgressBar,
                               QTableView, QWidget)

from tracklister.core.layout import DUDOSOS, REPORT_TEMPLATE
from tracklister.core.model import DoubtKind, ResultState
from tracklister.gui.models import ResultsTableModel
from tracklister.gui.pages.common import PRESET_LABEL_ES
from tracklister.gui.theme import Theme
from tracklister.gui.widgets import Banner, StateChips, button, label, page_layout
from tracklister.organize.naming import safe_component

DONE_STATES = {s for s in ResultState} - {ResultState.PENDIENTE, ResultState.EN_CURSO}
PLURAL = {ResultState.VERIFICADO: ("verificada", "verificadas"),
          ResultState.YA_EN_BIBLIOTECA: ("ya en biblioteca", "ya en biblioteca"),
          ResultState.DUDOSO: ("dudosa", "dudosas"),
          ResultState.NO_ENCONTRADO: ("no encontrada", "no encontradas"),
          ResultState.NO_CUMPLE_FORMATO: ("no cumple formato", "no cumplen formato"),
          ResultState.FALLIDA: ("fallida", "fallidas"),
          ResultState.OMITIDA: ("omitida", "omitidas"),
          ResultState.PENDIENTE: ("pendiente", "pendientes")}


def summary_text(counts) -> str:
    parts = []
    for st, (one, many) in PLURAL.items():
        n = counts.get(st, 0)
        if n:
            parts.append(f"{n} {one if n == 1 else many}")
    return ", ".join(parts)


class ResultsPage(QWidget):
    retry_requested = Signal()
    continue_requested = Signal()
    cancel_requested = Signal()
    new_set_requested = Signal()
    open_set_requested = Signal()

    def __init__(self, window, parent: QWidget | None = None):
        super().__init__(parent)
        self.window = window
        self.services = window.services
        self.themes = window.themes
        self.session = None
        self.running = False
        lay = page_layout(self, "Descarga")
        self.title = self.page_title

        info = QHBoxLayout()
        self.info = label("", "muted", wrap=True, selectable=True)
        info.addWidget(self.info, 1)
        self.folder_btn = button("Abrir carpeta")
        self.themes.bind_icon(self.folder_btn, "carpeta")
        self.folder_btn.clicked.connect(self.open_folder)
        info.addWidget(self.folder_btn)
        lay.addLayout(info)

        prow = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Progreso de la descarga")
        prow.addWidget(self.progress, 1)
        self.count = label("", mono=True)
        prow.addWidget(self.count)
        self.cancel_btn = button("Cancelar")
        self.cancel_btn.clicked.connect(self.cancel_requested)
        prow.addWidget(self.cancel_btn)
        lay.addLayout(prow)
        self.phase = label("", "small", wrap=True)
        lay.addWidget(self.phase)

        self.chips = StateChips(self.themes)
        lay.addWidget(self.chips)
        self.banner = Banner(self.themes)
        lay.addWidget(self.banner)

        self.model = ResultsTableModel(self.themes.theme, self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAccessibleName("Resultados por pista")
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(30)
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        for col, w in enumerate((48, 300, 210, 360, 200, 92)):
            self.table.setColumnWidth(col, w)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)
        self.detail = label("Selecciona una pista para ver el detalle completo (motivos, archivo y origen).",
                            "small", wrap=True, selectable=True)
        self.detail.setAccessibleName("Detalle de la pista seleccionada")
        lay.addWidget(self.detail)
        self.table.selectionModel().currentRowChanged.connect(self._show_detail)
        self.model.dataChanged.connect(lambda *_: self._show_detail(self.table.currentIndex()))

        self.log_btn = button("Ver registro", "link")
        self.log_btn.setCheckable(True)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setProperty("mono", True)
        self.log.setMaximumBlockCount(3000)
        self.log.setAccessibleName("Registro del motor")
        self.log.setFixedHeight(130)
        self.log.hide()
        self.log_btn.toggled.connect(self.log.setVisible)
        self.log_btn.toggled.connect(lambda on: self.log_btn.setText("Ocultar registro" if on else "Ver registro"))

        foot = QHBoxLayout()
        foot.addWidget(self.log_btn)
        foot.addStretch(1)
        self.retry_btn = button("Reintentar fallos",
                                tooltip="Vuelve a buscar las que fallaron, con el filtro de artista relajado.")
        self.themes.bind_icon(self.retry_btn, "reintentar")
        self.continue_btn = button("Continuar descarga")
        self.copy_btn = button("Copiar tracklist", tooltip="Texto con tiempos para Mixcloud o Instagram.")
        self.themes.bind_icon(self.copy_btn, "copiar")
        self.report_btn = button("Abrir informe")
        self.open_set_btn = button("Abrir un set anterior…")
        self.new_btn = button("Nuevo set", "primary")
        self.retry_btn.clicked.connect(self.retry_requested)
        self.continue_btn.clicked.connect(self.continue_requested)
        self.copy_btn.clicked.connect(self.copy_tracklist)
        self.report_btn.clicked.connect(self.open_report)
        self.open_set_btn.clicked.connect(self.open_set_requested)
        self.new_btn.clicked.connect(self.new_set_requested)
        for b in (self.retry_btn, self.continue_btn, self.copy_btn, self.report_btn, self.open_set_btn, self.new_btn):
            foot.addWidget(b)
        lay.addWidget(self.log)
        lay.addLayout(foot)
        self.themes.bind(self, ResultsPage._apply_theme)
        self._refresh_buttons()

    def _apply_theme(self, theme: Theme) -> None:
        self.model.set_theme(theme)

    def focus_default(self) -> None:
        self.table.setFocus()

    def _show_detail(self, index, _prev=None) -> None:
        if index is None or not index.isValid():
            return
        self.detail.setText(self.model.detail_text(index.row()).replace("\n", "  ·  "))

    # ---- session -----------------------------------------------------------------------------------
    def show_session(self, session, running: bool) -> None:
        self.session = session
        doc = session.doc
        self.title.setText(doc.name)
        preset = PRESET_LABEL_ES.get(doc.preset_id, doc.preset_id)
        self.info.setText(f"{preset} · {session.set_dir}")
        self.model.load(doc.rows, doc.results)
        self.detail.setText("Selecciona una pista para ver el detalle completo (motivos, archivo y origen).")
        self.log.clear()
        self.banner.hide()
        self.phase.setText("Preparando…" if running else "")
        self.set_running(running)

    def set_running(self, running: bool) -> None:
        self.running = running
        self._refresh_progress()
        self._refresh_buttons()

    def _targets(self) -> list:
        return [r for r in self.model.rows() if r.download and (r.title or "").strip()]

    def _refresh_progress(self) -> None:
        targets = self._targets()
        done = sum(1 for r in targets if self.model.state_of(r.uid) in DONE_STATES)
        self.progress.setMaximum(max(1, len(targets)))
        self.progress.setValue(done)
        self.count.setText(f"{done} de {len(targets)}")
        self.chips.set_counts(self.model.counts())

    def _refresh_buttons(self) -> None:
        has = self.session is not None
        self.cancel_btn.setVisible(self.running)
        self.cancel_btn.setEnabled(self.running)
        idle = has and not self.running
        self.retry_btn.setEnabled(idle and self.model.retryable() > 0)
        self.continue_btn.setVisible(idle and self.model.pending() > 0)
        self.copy_btn.setEnabled(has)
        self.report_btn.setEnabled(idle and self._report_path() is not None and self._report_path().is_file())
        self.folder_btn.setEnabled(has)
        self.open_set_btn.setEnabled(not self.running)
        self.new_btn.setEnabled(not self.running)

    def on_session_event(self, ev, snap) -> None:
        kind = getattr(ev, "kind", "")
        if kind == "row_state":
            self.model.apply_event(ev.uid, ev.state, ev.message_es, snap)
            self._refresh_progress()
        elif kind in ("pass_started", "pass_finished"):
            self.phase.setText(ev.message_es)
            self._append_log(ev.message_es)
        elif kind == "log":
            self._append_log(ev.message_es)
            if ev.message_es.startswith("Esperando"):
                self.phase.setText(ev.message_es)
        elif kind == "error":
            self.banner.show_message(ev.message_es, "error")
            self._append_log("! " + ev.message_es)

    def _append_log(self, text: str) -> None:
        if text:
            self.log.appendPlainText(text)

    def on_finished(self, error: str = "") -> None:
        if self.session is not None:
            self.model.load(self.session.doc.rows, self.session.doc.results)
        self.set_running(False)
        counts = self.model.counts()
        self.phase.setText("Terminado.")
        if error:
            self.banner.show_message(error, "error")
            return
        if self.banner.isVisible() and self.banner.kind == "error":
            return
        text = "Listo: " + (summary_text(counts) or "nada que descargar") + "."
        quarantined = sum(1 for r in self.model.rows()
                          if (res := self.model.result_of(r.uid)) is not None and res.state == ResultState.DUDOSO
                          and res.doubt in (DoubtKind.IDENTIDAD, DoubtKind.VERSION, DoubtKind.DURACION))
        if quarantined:
            text += f" Revisa la carpeta {DUDOSOS}: ahí están las dudas de identidad, versión o duración."
        if self.model.retryable():
            text += " Puedes pulsar «Reintentar fallos»."
        good = counts.get(ResultState.VERIFICADO, 0) + counts.get(ResultState.YA_EN_BIBLIOTECA, 0)
        self.banner.show_message(text, "ok" if good and not self.model.retryable() else "warn")

    # ---- actions ------------------------------------------------------------------------------------
    def _report_path(self):
        if self.session is None:
            return None
        return self.session.set_dir / REPORT_TEMPLATE.format(name=safe_component(self.session.doc.name))

    def copy_tracklist(self) -> None:
        if self.session is None:
            return
        self.services.copy_text(self.session.tracklist_text())
        self.window.status(f"Tracklist de «{self.session.doc.name}» copiada: pégala en Mixcloud o Instagram.")

    def open_folder(self) -> None:
        if self.session is not None:
            self.services.open_path(self.session.set_dir)

    def open_report(self) -> None:
        p = self._report_path()
        if p is not None and p.is_file():
            self.services.open_path(p)
