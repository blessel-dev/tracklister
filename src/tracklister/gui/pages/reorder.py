"""'Reordenar carpeta existente': name an old folder in tracklist order (preview + undo).

Owner: GUI step.
SPDX-License-Identifier: GPL-3.0-or-later

The preview is mandatory: nothing is renamed until 'Aplicar cambios'. Every rename goes through
the folder's journal (never overwrites), and 'Deshacer' reverts the last reorder of that folder.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLineEdit, QTableView, QWidget)

from tracklister.core.model import TrackRow
from tracklister.gui.models import ReorderPreviewModel
from tracklister.gui.pages.common import downloads_folder
from tracklister.gui.theme import Theme
from tracklister.gui.widgets import Banner, SourcePicker, button, label, page_layout

# «Reordenar» on the folder of the set being downloaded (CL-09)
RUNNING_SET_ES = "Es la carpeta del set que se está descargando: espera a que termine la descarga (o cancélala)."


class ReorderPage(QWidget):
    def __init__(self, window, parent: QWidget | None = None):
        super().__init__(parent)
        self.window = window
        self.services = window.services
        self.themes = window.themes
        self.rows: list[TrackRow] = []
        self.rows_from = ""
        self.preview_folder: Path | None = None    # the folder the shown proposals belong to
        lay = page_layout(self, "Reordenar carpeta existente",
                          "Para carpetas bajadas con la herramienta antigua: empareja cada archivo con su fila "
                          "de la tracklist y le pone su número. Primero ves la propuesta; nada se sobrescribe y "
                          "puedes deshacerlo.")
        frow = QHBoxLayout()
        frow.addWidget(label("Carpeta"))
        self.folder = QLineEdit()
        self.folder.setAccessibleName("Carpeta que quieres reordenar")
        self.folder.setPlaceholderText("La carpeta con los archivos sin ordenar")
        self.folder.textChanged.connect(self._on_folder_changed)
        frow.addWidget(self.folder, 1)
        pick = button("Elegir carpeta…")
        self.themes.bind_icon(pick, "carpeta")
        pick.clicked.connect(self._pick_folder)
        frow.addWidget(pick)
        lay.addLayout(frow)

        trow = QHBoxLayout()
        trow.addWidget(label("Tracklist"))
        self.source = SourcePicker()
        self.source.use_table.connect(self.use_table)
        self.source.open_file.connect(self.open_tracklist)
        trow.addWidget(self.source, 1)
        lay.addLayout(trow)

        arow = QHBoxLayout()
        self.propose_btn = button("Ver propuesta", "primary")
        self.propose_btn.clicked.connect(self.propose)
        arow.addWidget(self.propose_btn)
        arow.addStretch(1)
        self.summary = label("", "muted")
        arow.addWidget(self.summary)
        lay.addLayout(arow)

        self.banner = Banner(self.themes)
        lay.addWidget(self.banner)

        self.model = ReorderPreviewModel(self.themes.theme, self)
        self.model.edited.connect(self._refresh_buttons)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAccessibleName("Propuesta de nombres")
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(30)
        for col, w in enumerate((34, 48, 330, 360, 104, 170)):
            self.table.setColumnWidth(col, w)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)

        foot = QHBoxLayout()
        self.undo_btn = button("Deshacer el último reordenado")
        self.themes.bind_icon(self.undo_btn, "deshacer")
        self.undo_btn.clicked.connect(self.undo)
        foot.addWidget(self.undo_btn)
        foot.addStretch(1)
        self.apply_btn = button("Aplicar cambios", "primary")
        self.apply_btn.clicked.connect(self.apply)
        foot.addWidget(self.apply_btn)
        lay.addLayout(foot)
        self.themes.bind(self, ReorderPage._apply_theme)
        self._refresh_buttons()

    def _apply_theme(self, theme: Theme) -> None:
        self.model.set_theme(theme)

    def _folder(self) -> Path | None:
        t = self.folder.text().strip()
        return Path(t) if t else None

    def _clear_preview(self) -> None:
        self.preview_folder = None
        self.model.set_proposals([])
        self.summary.setText("")

    def _on_folder_changed(self) -> None:
        """Another folder in the field: the proposals shown are for the previous one, so they go (a new
        preview is mandatory before anything is renamed)."""
        if self.preview_folder is not None and self._folder() != self.preview_folder:
            self._clear_preview()
            self.banner.hide()
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        f = self._folder()
        ok_folder = f is not None and f.is_dir()
        self.propose_btn.setEnabled(ok_folder and bool(self.rows))
        n = self.model.checked_count()
        self.apply_btn.setEnabled(ok_folder and n > 0)
        self.apply_btn.setText(f"Aplicar cambios ({n})" if n else "Aplicar cambios")
        self.undo_btn.setEnabled(ok_folder and self.services.can_undo_reorder(f))
        self.source.set_summary(f"{len(self.rows)} pistas ({self.rows_from})" if self.rows else
                                "Sin tracklist: usa la tabla de Nuevo set o abre un archivo.")

    def _pick_folder(self) -> None:
        d = self.window.prompter.pick_folder("Carpeta que quieres reordenar", self.folder.text() or None)
        if d:
            self.folder.setText(str(Path(d)))
            self._clear_preview()
            self._refresh_buttons()

    def set_tracklist(self, rows: list[TrackRow], origin: str) -> None:
        self.rows = [TrackRow.from_dict(r.to_dict()) for r in rows]
        for i, r in enumerate(self.rows, start=1):
            r.pos = i
        self.rows_from = origin
        self._clear_preview()
        self._refresh_buttons()

    def use_table(self) -> None:
        rows = self.window.new_set.model.rows()
        if not rows:
            self.banner.show_message("La tabla de Nuevo set está vacía: carga allí la tracklist primero.", "warn")
            return
        self.set_tracklist(rows, "tabla de Nuevo set")

    def open_tracklist(self) -> None:
        f = self.window.prompter.pick_file("Tracklist de esa carpeta", str(downloads_folder()))
        if not f:
            return
        self.banner.show_message("Leyendo la tracklist…", "info", closable=False)
        self.window.pool.start(lambda t: self.services.import_source(Path(f)),
                               on_ok=lambda res: self._on_imported(res, Path(f).name),
                               on_error=lambda m: self.banner.show_message(m, "error"))

    def _on_imported(self, result, name: str) -> None:
        rows = list(getattr(result, "rows", None) or [])
        if not rows:
            self.banner.show_message(getattr(result, "message_es", "") or "No he encontrado pistas en ese archivo.",
                                     "warn")
            return
        self.banner.hide()
        self.set_tracklist(rows, name)

    def _is_running_set(self, folder: Path) -> bool:
        """The folder of the set being downloaded: renaming files under the download would leave its results
        naming old files, and the two undo journals would overwrite each other's batches (CL-09)."""
        session = self.window.session
        if not self.window.worker_running() or session is None:
            return False
        try:
            return os.path.samefile(folder, session.set_dir)
        except OSError:
            return False

    def _refuse_running_set(self, folder: Path | None) -> bool:
        if folder is not None and self._is_running_set(folder):
            self.banner.show_message(RUNNING_SET_ES, "warn")
            return True
        return False

    def propose(self) -> None:
        f = self._folder()
        if self._refuse_running_set(f):
            return
        if f is None or not f.is_dir() or not self.rows:
            return
        self.banner.show_message("Comparando los archivos con la tracklist…", "info", closable=False)
        self.propose_btn.setEnabled(False)
        rows = [TrackRow.from_dict(r.to_dict()) for r in self.rows]
        self.window.pool.start(lambda t: self.services.propose_reorder(f, rows),
                               on_ok=lambda proposals, f=f: self._on_proposed(proposals, f), on_error=self._on_error)

    def _on_proposed(self, proposals, folder: Path) -> None:
        if self._folder() != folder:
            # the field changed while comparing: this preview is for another folder, never show it
            self.banner.hide()
            self._refresh_buttons()
            return
        self.preview_folder = folder
        self.model.set_proposals(proposals)
        counts = {k: sum(1 for p in proposals if p.status == k) for k in ("match", "ambiguous", "missing", "extra")}
        self.summary.setText(f"{counts['match']} coinciden · {counts['ambiguous']} dudosas · "
                             f"{counts['missing']} sin archivo · {counts['extra']} archivos que no encajan")
        if counts["ambiguous"]:
            self.banner.show_message("Las dudosas no se renombran salvo que las marques tú.", "warn")
        else:
            self.banner.show_message("Revisa la propuesta y pulsa «Aplicar cambios».", "info")
        self._refresh_buttons()

    def _on_error(self, msg: str) -> None:
        self.banner.show_message(msg, "error")
        self._refresh_buttons()

    def apply(self) -> None:
        # always the PREVIEWED folder (its journal gets the undo record), never whatever the field says now
        f = self.preview_folder
        if self._refuse_running_set(f):
            return
        chosen = self.model.chosen()
        n = sum(1 for p in chosen if p.status == "match")
        if f is None or self._folder() != f or not n:
            return
        if not self.window.prompter.confirm("Reordenar carpeta",
                                            f"Se renombrarán {n} archivos de {f}. Nada se sobrescribe y puedes "
                                            "deshacerlo después.", ok="Renombrar"):
            return
        self.apply_btn.setEnabled(False)
        self.window.pool.start(lambda t: self.services.apply_reorder(f, chosen),
                               on_ok=lambda _bid, f=f: self._on_applied(n, f), on_error=self._on_error)

    def _on_applied(self, n: int, folder: Path) -> None:
        self._clear_preview()
        self.banner.show_message(f"Hecho: {n} archivos renombrados en el orden de la tracklist.", "ok",
                                 actions=[("Abrir carpeta", lambda: self.services.open_path(folder))])
        self._refresh_buttons()

    def undo(self) -> None:
        f = self._folder()
        if f is None or self._refuse_running_set(f):
            return
        errors = self.services.undo_reorder(f)
        if errors:
            self.banner.show_message("No se pudo deshacer todo: " + " ".join(errors), "warn")
        else:
            self.banner.show_message("Deshecho: los archivos tienen otra vez su nombre anterior.", "ok")
        self._clear_preview()
        self._refresh_buttons()
