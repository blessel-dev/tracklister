"""'Nuevo set': drop zone, 'Pega un enlace o un texto', the editable review table, 'Descargar'.

Owner: GUI step.
SPDX-License-Identifier: GPL-3.0-or-later

Importing goes through Services.import_source (inputs.importer, frozen interface), always in a
background task; it never raises for user input problems and returns rows + a Spanish message.
Enrichment (iTunes -> Deezer -> MusicBrainz) runs on COPIES of the rows, so the table is never
written from two threads; the result replaces the rows by uid.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPlainTextEdit, QStackedWidget, QTableView, QVBoxLayout, QWidget)

from tracklister import config
from tracklister.core.layout import set_doc_path
from tracklister.core.model import SourceRef, TrackRow
from tracklister.gui.models import ENRICH_ES, TrackTableModel
from tracklister.gui.pages.common import PRESET_LABEL_ES, downloads_folder
from tracklister.gui.theme import Theme, svg_pixmap
from tracklister.gui.widgets import (Banner, DownloadsWatcher, DropZone, button, card, label, page_layout)
from tracklister.assets import load_tokens

PASTE_PLACEHOLDER = ("Enlace de YouTube/SoundCloud, o la tracklist copiada (1001tracklists, MixesDB…)\n"
                     "01. Artista - Título (Remix)\n02. 05:12 Artista - Título")
TOP_HEIGHT = 176


def _copy_rows(rows) -> list[TrackRow]:
    return [TrackRow.from_dict(r.to_dict()) for r in rows]


class NewSetPage(QWidget):
    download_requested = Signal(str, list, list)   # set name, rows (copies), sources

    def __init__(self, window, parent: QWidget | None = None):
        super().__init__(parent)
        self.window = window
        self.services = window.services
        self.themes = window.themes
        self.sources: list[SourceRef] = []
        self.last_result = None
        self._busy = False
        self.watcher: DownloadsWatcher | None = None

        lay = page_layout(self, "Nuevo set",
                          "Trae la tracklist, revisa la tabla y descarga. Cada archivo se comprueba contra su fila.")
        top = QHBoxLayout()
        top.setSpacing(12)

        # Drop zone
        self.drop = DropZone()
        dz = QVBoxLayout(self.drop)
        dz.setContentsMargins(18, 16, 18, 16)
        dz.setSpacing(8)
        self.drop_icon = QLabel()
        self.drop_icon.setFixedSize(28, 28)
        dz.addWidget(self.drop_icon)
        dz.addWidget(label("Arrastra aquí el CSV de trackid.net, un Excel (.xlsx) o un CSV", "h2", wrap=True))
        dz.addWidget(label("También puedes soltar un enlace de YouTube o SoundCloud.", "small", wrap=True))
        dz.addStretch(1)
        drow = QHBoxLayout()
        self.open_btn = button("Abrir archivo…", tooltip="Ctrl+O")
        self.trackid_btn = button("Abrir en trackid.net",
                                  tooltip="trackid.net no deja leer sus tracklists automáticamente: ábrela, "
                                          "pulsa Export y arrastra aquí el CSV.")
        self.themes.bind_icon(self.open_btn, "abrir")
        self.themes.bind_icon(self.trackid_btn, "enlace")
        self.open_btn.clicked.connect(self.open_file)
        self.trackid_btn.clicked.connect(lambda: self.services.open_url(config.TRACKID_URL))
        drow.addWidget(self.open_btn)
        drow.addWidget(self.trackid_btn)
        drow.addStretch(1)
        dz.addLayout(drow)
        self.drop.dropped.connect(self._on_dropped)
        self.drop.setMaximumHeight(TOP_HEIGHT)
        top.addWidget(self.drop, 1)

        # Paste box
        pcard, pl = card("Pega un enlace o un texto")
        pcard.setMaximumHeight(TOP_HEIGHT)
        self.paste = QPlainTextEdit()
        self.paste.setPlaceholderText(PASTE_PLACEHOLDER)
        self.paste.setAccessibleName("Pega un enlace o un texto")
        self.paste.setTabChangesFocus(True)
        self.paste.setMinimumHeight(56)
        pl.addWidget(self.paste, 1)
        prow = QHBoxLayout()
        self.paste_btn = button("Pegar")
        self.themes.bind_icon(self.paste_btn, "pegar")
        self.paste_btn.clicked.connect(self.paste_clipboard)
        self.read_btn = button("Leer")
        self.read_btn.clicked.connect(self.read_paste)
        prow.addWidget(self.paste_btn)
        prow.addStretch(1)
        prow.addWidget(self.read_btn)
        pl.addLayout(prow)
        top.addWidget(pcard, 1)
        lay.addLayout(top)

        self.watch_banner = Banner(self.themes)
        self.banner = Banner(self.themes)
        lay.addWidget(self.watch_banner)
        lay.addWidget(self.banner)

        # YouTube / SoundCloud candidates
        self.cand_row = QWidget()
        ch = QHBoxLayout(self.cand_row)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.addWidget(label("Tracklist elegida"))
        self.cand_box = QComboBox()
        self.cand_box.setAccessibleName("Tracklist elegida")
        self.cand_box.setMinimumWidth(380)
        self.cand_box.activated.connect(self._on_candidate)
        ch.addWidget(self.cand_box)
        self.cand_hint = label("", "small", wrap=True)
        ch.addWidget(self.cand_hint, 1)
        self.cand_row.hide()
        lay.addWidget(self.cand_row)

        # Set name
        nrow = QHBoxLayout()
        name_lbl = label("Nombre del set")
        self.name = QLineEdit()
        self.name.setAccessibleName("Nombre del set")
        self.name.setPlaceholderText("p. ej. Fjaak - Techno DJ Set - Mayo 2026")
        self.name.setMinimumWidth(320)
        name_lbl.setBuddy(self.name)
        self.name.textChanged.connect(self._update_dest)
        self.dest = label("", "small", wrap=True)
        nrow.addWidget(name_lbl)
        nrow.addWidget(self.name, 2)
        nrow.addWidget(self.dest, 3)
        lay.addLayout(nrow)

        # Toolbar
        tb = QHBoxLayout()
        tb.setSpacing(6)
        self.enrich_btn = button("Completar datos",
                                 tooltip="Busca la duración y la versión exacta en iTunes, Deezer y MusicBrainz "
                                         "(solo envía artista y título).")
        self.enrich_btn.clicked.connect(self.enrich)
        self.add_source_btn = button("Añadir otra fuente del mismo set",
                                     tooltip="Combina otra tracklist del mismo set (por ejemplo, el CSV de "
                                             "trackid.net y los comentarios de YouTube).")
        self.add_source_btn.clicked.connect(self.add_source)
        self.up_btn = button("Subir")
        self.down_btn = button("Bajar")
        self.add_btn = button("Añadir fila")
        self.del_btn = button("Quitar fila")
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn.clicked.connect(lambda: self._move(1))
        self.add_btn.clicked.connect(self._insert)
        self.del_btn.clicked.connect(self._remove)
        for b in (self.enrich_btn, self.add_source_btn):
            tb.addWidget(b)
        tb.addSpacing(12)
        for b in (self.up_btn, self.down_btn, self.add_btn, self.del_btn):
            tb.addWidget(b)
        tb.addStretch(1)
        self.count_label = label("", "muted")
        tb.addWidget(self.count_label)
        lay.addLayout(tb)

        # Review table
        self.model = TrackTableModel(self.themes.theme, self)
        self.model.edited.connect(self._update_counts)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAccessibleName("Tabla de la tracklist")
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed
                                   | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(30)
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setStretchLastSection(False)
        widths = {"download": 34, "pos": 46, "start": 72, "artist": 190, "title": 230, "version": 170, "label": 130,
                  "duration": 80, "status": 116, "notes": 130}
        for key, w in widths.items():
            col = self.model.column_of(key)
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(col, w)
        hh.setSectionResizeMode(self.model.column_of("download"), QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(self.model.column_of("title"), QHeaderView.ResizeMode.Stretch)
        self.empty = label("Aún no hay pistas. Arrastra una tracklist o pega un enlace o un texto.", "muted",
                           wrap=True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.table)
        lay.addWidget(self.stack, 1)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), self.table, self._remove,
                  context=Qt.ShortcutContext.WidgetShortcut)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Open), self, self.open_file)

        # Footer
        foot = QHBoxLayout()
        self.preset_label = label("", "muted")
        foot.addWidget(self.preset_label, 1)
        self.download_btn = button("Descargar", "primary")
        self.download_btn.clicked.connect(self.request_download)
        foot.addWidget(self.download_btn)
        lay.addLayout(foot)

        self.themes.bind(self, NewSetPage._apply_theme)
        self.refresh()

    # ---- theme / state ------------------------------------------------------------------------
    def _apply_theme(self, theme: Theme) -> None:
        rel = load_tokens()["ui_icons"]["abrir"]
        self.drop_icon.setPixmap(svg_pixmap(rel, theme.color("ink"), 28, self.devicePixelRatioF()))
        self.model.set_theme(theme)

    def focus_default(self) -> None:
        (self.table if self.model.rowCount() else self.paste).setFocus()

    def refresh(self) -> None:
        pid = self.services.settings.preset_id
        self.preset_label.setText(f"Formato: {PRESET_LABEL_ES.get(pid, pid)} · se cambia en Ajustes")
        self._update_dest()
        self._update_counts()

    def showEvent(self, e) -> None:  # noqa: N802
        self.refresh()
        super().showEvent(e)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.model.set_editable(not busy)
        for b in (self.open_btn, self.read_btn, self.paste_btn, self.enrich_btn, self.add_source_btn, self.up_btn,
                  self.down_btn, self.add_btn, self.del_btn):
            b.setEnabled(not busy)
        self.drop.setAcceptDrops(not busy)
        self._update_counts()

    def _update_counts(self) -> None:
        total = self.model.rowCount()
        n = len(self.model.downloadable())
        self.stack.setCurrentIndex(1 if total else 0)
        self.count_label.setText(f"{total} pistas · {n} marcadas" if total else "")
        self.download_btn.setText("Descargar 1 pista" if n == 1 else f"Descargar {n} pistas" if n else "Descargar")
        self.download_btn.setEnabled(bool(n) and not self._busy)
        for b in (self.enrich_btn, self.up_btn, self.down_btn, self.del_btn):
            b.setEnabled(bool(total) and not self._busy)

    def _update_dest(self) -> None:
        name = self.name.text().strip()
        d = self.services.set_dir_for(name) if name else None
        if self.services.library_root() is None:
            self.dest.setText("Elige la carpeta de tu biblioteca en Ajustes.")
        elif d is None:
            self.dest.setText("")
        elif set_doc_path(d).is_file():
            self.dest.setText(f"Ya existe este set en {d}: se completa sin volver a bajar lo que ya está.")
        else:
            self.dest.setText(f"Se guardará en {d}")

    # ---- importing -----------------------------------------------------------------------------
    def _on_dropped(self, src: str) -> None:
        is_file = False
        if not src.startswith(("http://", "https://")) and "\n" not in src and len(src) < 1024:
            try:
                is_file = Path(src).is_file()
            except (OSError, ValueError):
                is_file = False
        self.import_source(Path(src) if is_file else src)

    def open_file(self) -> None:
        if self._busy:
            return
        f = self.window.prompter.pick_file("Abrir tracklist", str(downloads_folder()))
        if f:
            self.import_source(Path(f))

    def paste_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text()
        if text.strip():
            self.paste.setPlainText(text)
            self.read_paste()

    def read_paste(self) -> None:
        text = self.paste.toPlainText().strip()
        if not text:
            self.banner.show_message("Pega primero un enlace o el texto de la tracklist.", "warn")
            self.paste.setFocus()
            return
        self.import_source(text)

    def add_source(self) -> None:
        if self._busy:
            return
        idx = self.window.prompter.choose(
            "Añadir otra fuente del mismo set",
            "Puedes combinar un archivo o lo que hayas pegado en «Pega un enlace o un texto». "
            "Los nombres de trackid.net mandan; la otra fuente rellena huecos e IDs.",
            ["Abrir archivo…", "Usar lo pegado"])
        if idx == 0:
            f = self.window.prompter.pick_file("Otra fuente del mismo set", str(downloads_folder()))
            if f:
                self.import_source(Path(f), mode="merge")
        elif idx == 1:
            text = self.paste.toPlainText().strip()
            if text:
                self.import_source(text, mode="merge")
            else:
                self.banner.show_message("Pega primero el enlace o el texto de la otra fuente.", "warn")

    def import_source(self, source, mode: str | None = None) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self.banner.show_message("Leyendo la tracklist…", "info", closable=False)
        self.window.pool.start(lambda t: self.services.import_source(source),
                               on_ok=lambda res: self._on_imported(res, mode),
                               on_error=self._on_import_error)

    def _on_import_error(self, msg: str) -> None:
        self._set_busy(False)
        self.banner.show_message(f"No se pudo leer la tracklist. {msg}", "error")

    def _link_actions(self, kind: str, links: list[str]) -> list:
        """'Abrir en trackid.net' / 'Abrir la página' / 'Abrir la tracklist enlazada' buttons."""
        if kind == "trackid_url":
            url = links[0] if links else config.TRACKID_URL
            return [("Abrir en trackid.net", lambda: self.services.open_url(url))]
        if not links:
            return []
        text = "Abrir la página" if kind == "pegar_texto_url" else "Abrir la tracklist enlazada"
        return [(text, lambda url=links[0]: self.services.open_url(url))]

    def _on_imported(self, result, mode: str | None) -> None:
        self._set_busy(False)
        self.last_result = result
        rows = list(getattr(result, "rows", None) or [])
        msg = getattr(result, "message_es", "") or ""
        warnings = list(getattr(result, "warnings_es", None) or [])
        kind = str(getattr(result, "kind", "") or "")
        actions = self._link_actions(kind, list(getattr(result, "links", None) or []))
        if not rows:
            if mode != "merge" and getattr(result, "candidates", None):
                self._show_candidates(result)        # doubtful lists: let the user pick one
            self.banner.show_message(msg or "No he encontrado ninguna pista ahí.", "warn", actions=actions)
            return
        if mode is None and self.model.rowCount():
            idx = self.window.prompter.choose("Ya hay una tracklist en la tabla", "¿Qué hago con la nueva?",
                                              ["Reemplazar la tabla", "Combinar con la actual"])
            if idx is None:
                self.banner.show_message("No se ha cambiado nada.", "info")
                return
            mode = "merge" if idx == 1 else "replace"
        new_sources = list(getattr(result, "sources", None) or [])
        if mode == "merge":
            try:
                rows = self.services.merge_rows(self.model.rows(), rows)
            except Exception as e:  # noqa: BLE001
                self.banner.show_message(f"No se pudieron combinar las dos fuentes: {e}", "error")
                return
            self.sources += [s for s in new_sources if s not in self.sources]
        else:
            self.sources = new_sources
            name = getattr(result, "suggested_name", None) or f"Set {datetime.now():%Y-%m-%d %H%M}"
            self.name.setText(str(name))
        self.model.set_rows(rows)
        self._show_candidates(result if mode != "merge" else None)
        text = " ".join(x for x in [msg] + warnings if x)
        if mode == "merge":
            text = f"Fuentes combinadas: {len(rows)} pistas. " + text
        self.banner.show_message(text or f"{len(rows)} pistas.", "warn" if warnings else "ok", actions=actions)
        if self.services.settings.enrichment_enabled:
            self.enrich()

    def _show_candidates(self, result) -> None:
        """YouTube/SoundCloud: 'Comentario de @x · 22 pistas con tiempos · 11 likes', switchable."""
        cands = list(getattr(result, "candidates", None) or []) if result is not None else []
        chosen = getattr(result, "chosen", None) if result is not None else None
        self.cand_box.clear()
        if len(cands) < 2 and not (cands and chosen is None):
            self.cand_row.hide()
            return
        for c in cands:
            self.cand_box.addItem(str(getattr(c, "label_es", "?")))
        self.cand_box.setPlaceholderText("Elige una tracklist")
        self.cand_box.setCurrentIndex(chosen if isinstance(chosen, int) and 0 <= chosen < len(cands) else -1)
        switchable = all(getattr(c, "rows", None) for c in cands)
        self.cand_box.setEnabled(switchable)
        self.cand_hint.setText("" if switchable else
                               "Si prefieres otra, cópiala del vídeo y pégala en «Pega un enlace o un texto».")
        self.cand_row.show()

    def _on_candidate(self, i: int) -> None:
        cands = list(getattr(self.last_result, "candidates", None) or [])
        if not (0 <= i < len(cands)) or not getattr(cands[i], "rows", None):
            return
        c = cands[i]
        self.model.set_rows(_copy_rows(c.rows))
        ref = getattr(c, "source_ref", None)
        if ref is not None:
            self.sources = [ref]
        if not self.name.text().strip():
            self.name.setText(str(getattr(self.last_result, "suggested_name", None) or
                                  f"Set {datetime.now():%Y-%m-%d %H%M}"))
        self.banner.show_message(f"Usando: {c.label_es}.", "ok")

    # ---- enrichment ------------------------------------------------------------------------------
    def enrich(self) -> None:
        if self._busy or not self.model.rowCount():
            return
        copies = _copy_rows(self.model.rows())
        self._set_busy(True)
        self.banner.show_message("Completando datos (iTunes, Deezer, MusicBrainz)…", "info", closable=False)

        def work(task):
            return self.services.enrich(copies, on_progress=task.progress.emit, cancel=task.cancel)

        self.window.pool.start(work, on_ok=lambda outs: self._on_enriched(copies, outs),
                               on_error=self._on_enrich_error,
                               on_progress=lambda d, n: self.banner.text.setText(
                                   f"Completando datos (iTunes, Deezer, MusicBrainz)… {d} de {n}"))

    def _on_enriched(self, copies: list[TrackRow], outcomes) -> None:
        self._set_busy(False)
        self.model.replace_rows_by_uid(copies)
        outs = list(outcomes or [])
        ok = [o for o in outs if getattr(o, "accepted", False)]
        by = Counter(ENRICH_ES.get(getattr(o, "provider", None) or "", getattr(o, "provider", None) or "?")
                     for o in ok)
        with_dur = sum(1 for r in copies if r.expected_duration_s)
        detail = ", ".join(f"{k} {v}" for k, v in by.most_common())
        self.banner.show_message(
            f"Datos completados: {len(ok)} de {len(outs)} pistas" + (f" ({detail})" if detail else "") +
            f". {with_dur} con duración esperada.", "ok")

    def _on_enrich_error(self, msg: str) -> None:
        self._set_busy(False)
        self.banner.show_message(f"No se pudieron completar los datos ({msg}). Puedes descargar igual: solo "
                                 "faltará la duración esperada.", "warn")

    # ---- table editing ---------------------------------------------------------------------------
    def _selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectionModel().selectedRows()})

    def _move(self, delta: int) -> None:
        sel = self._selected_rows()
        if len(sel) != 1 or self._busy:
            return
        j = self.model.move_row(sel[0], delta)
        self.table.selectRow(j)

    def _insert(self) -> None:
        if self._busy:
            return
        sel = self._selected_rows()
        at = (sel[-1] + 1) if sel else self.model.rowCount()
        i = self.model.insert_row(at)
        self.table.selectRow(i)
        self.table.edit(self.model.index(i, self.model.column_of("artist")))

    def _remove(self) -> None:
        if self._busy:
            return
        sel = self._selected_rows()
        if sel:
            self.model.remove_rows(sel)

    def set_rows(self, rows: list[TrackRow], name: str | None = None, sources: list[SourceRef] | None = None) -> None:
        """Load rows directly (used by 'Abrir un set anterior' and by tools/screenshots.py)."""
        self.model.set_rows(rows)
        if name is not None:
            self.name.setText(name)
        if sources is not None:
            self.sources = list(sources)

    # ---- download ----------------------------------------------------------------------------------
    def request_download(self) -> None:
        name = self.name.text().strip()
        if not self.model.downloadable():
            self.banner.show_message("Marca al menos una pista con título para descargar.", "warn")
            return
        if not name:
            self.banner.show_message("Ponle un nombre al set: será el nombre de su carpeta.", "warn")
            self.name.setFocus()
            return
        self.download_requested.emit(name, _copy_rows(self.model.rows()), list(self.sources))

    # ---- Downloads folder watcher --------------------------------------------------------------
    def start_watching(self, folder: Path | None = None) -> bool:
        self.stop_watching()
        if not self.services.settings.watch_downloads_folder:
            return False
        self.watcher = DownloadsWatcher(folder or downloads_folder(), self.services.is_trackid_csv, self)
        self.watcher.found.connect(self._on_new_download)
        return self.watcher.start()

    def stop_watching(self) -> None:
        if self.watcher is not None:
            self.watcher.stop()
            self.watcher.deleteLater()
            self.watcher = None

    def _on_new_download(self, path: str) -> None:
        p = Path(path)
        self.watch_banner.show_message(f"Hay un CSV nuevo de trackid.net en Descargas: {p.name}", "info",
                                       actions=[("Importar", lambda: (self.watch_banner.hide(),
                                                                      self.import_source(p)))])
