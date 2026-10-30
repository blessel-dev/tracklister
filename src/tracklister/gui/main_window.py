"""The main window: header + navigation, the screens, and the download flow.

Owner: GUI step.
SPDX-License-Identifier: GPL-3.0-or-later

Download flow (start_download):
1. the user's own account from Credential Manager (missing -> Ajustes);
2. SetSession.create (an existing set folder with the same name is merged, not re-downloaded),
   without writing anything yet;
3. every track already in the library is asked about, EVERY time, with both options and
   'Aplicar a todos los repetidos de este set' (only the copies the set's preset accepts are offered);
   closing a question writes nothing, answering them all saves the set;
4. a SessionWorker (QThread) applies those choices, runs the passes, asks the lossy checklist once
   and finalizes the folder (names, report, tracklist, library).
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QButtonGroup, QMainWindow, QStackedWidget, QStatusBar, QVBoxLayout, QWidget)

from tracklister import config
from tracklister.assets import asset_path, load_tokens
from tracklister.core import osplatform
from tracklister.core.layout import set_doc_path
from tracklister.core.model import DuplicateChoice
from tracklister.engine.credentials import CredentialError
from tracklister.gui.dialogs import Prompter
from tracklister.gui.pages.diagnostic import DiagnosticPage
from tracklister.gui.pages.first_run import FirstRunPage
from tracklister.gui.pages.new_set import NewSetPage
from tracklister.gui.pages.reorder import ReorderPage
from tracklister.gui.pages.results import ResultsPage
from tracklister.gui.pages.settings import SettingsPage
from tracklister.gui.theme import ThemeManager
from tracklister.gui.widgets import Banner, Header, button
from tracklister.gui.workers import SessionWorker, TaskPool, error_text

log = logging.getLogger("tracklister.gui")

NAV = (("new_set", "Nuevo set"), ("results", "Descarga"), ("reorder", "Reordenar"),
       ("diagnostic", "Diagnóstico"), ("settings", "Ajustes"))
# «Salir» during a download: the files that already arrived are still being checked and placed
CLOSING_AFTER_CHECKS_ES = "Guardando lo ya descargado… Tracklister se cerrará al terminar."
# a repeated-track question was closed: nothing starts
DUPLICATE_NOT_STARTED_ES = "Descarga no iniciada: no se ha elegido qué hacer con una pista repetida."


class MainWindow(QMainWindow):
    CLOSE_WAIT_MS = 30000       # closing during a download: how long the window waits for the worker to stop

    def __init__(self, services, themes: ThemeManager, prompter=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.services = services
        self.themes = themes
        self.prompter = prompter or Prompter(self, lambda: self.themes.theme)
        self.pool = TaskPool(self)
        self.session = None
        self.worker: SessionWorker | None = None
        self._close_when_done = False     # «Salir» was answered: close as soon as the worker has finished
        self.setWindowTitle(config.APP_NAME)
        self.setWindowIcon(QIcon(str(asset_path(load_tokens()["app_icon"]))))
        self.setMinimumSize(980, 640)
        self.resize(1280, 820)

        central = QWidget()
        central.setObjectName("Page")
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.header = Header(themes)
        v.addWidget(self.header)
        self.update_banner = Banner(themes)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(28, 10, 28, 0)
        hl.addWidget(self.update_banner)
        self.update_holder = holder
        holder.hide()
        self.update_banner.close_btn.clicked.connect(holder.hide)
        v.addWidget(holder)

        self.stack = QStackedWidget()
        self.stack.setObjectName("Pages")
        v.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = {}
        for key, text in NAV:
            b = button(text, "nav")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, key=key: self.go(key))
            self.nav_group.addButton(b)
            self.header.nav.addWidget(b)
            self.nav_buttons[key] = b

        self.first_run = FirstRunPage(self)
        self.new_set = NewSetPage(self)
        self.results = ResultsPage(self)
        self.reorder = ReorderPage(self)
        self.diagnostic = DiagnosticPage(self)
        self.settings_page = SettingsPage(self)
        self.pages = {"first_run": self.first_run, "new_set": self.new_set, "results": self.results,
                      "reorder": self.reorder, "diagnostic": self.diagnostic, "settings": self.settings_page}
        for p in self.pages.values():
            self.stack.addWidget(p)

        self.first_run.completed.connect(self._first_run_done)
        self.new_set.download_requested.connect(self.start_download)
        self.results.retry_requested.connect(lambda: self.run_again("retry"))
        self.results.continue_requested.connect(lambda: self.run_again("continue"))
        self.results.cancel_requested.connect(self.cancel_run)
        self.results.new_set_requested.connect(lambda: self.go("new_set"))
        self.results.open_set_requested.connect(self.open_previous_set)

        self.go("first_run" if self.needs_first_run() else "new_set")
        if services.settings_warning_es:
            self.new_set.banner.show_message(services.settings_warning_es, "warn")

    # ---- navigation -------------------------------------------------------------------------------
    def needs_first_run(self) -> bool:
        s = self.services.settings
        return not s.first_run_done or not s.library_root

    def current_page(self) -> str:
        w = self.stack.currentWidget()
        return next(k for k, p in self.pages.items() if p is w)

    def go(self, key: str) -> None:
        if key != "first_run" and self.needs_first_run():
            key = "first_run"
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        first = key == "first_run"
        for k, b in self.nav_buttons.items():
            b.setVisible(not first)
            b.setChecked(k == key)
        self.nav_buttons["results"].setEnabled(self.session is not None)
        focus = getattr(page, "focus_default", None)
        if focus is not None:
            focus()

    def status(self, text: str, ms: int = 6000) -> None:
        self.statusBar().showMessage(text, ms)

    def start_background(self) -> None:
        """After the window is shown: yt-dlp to the tools folder, Downloads watcher, update check."""
        self.pool.start(lambda t: self.services.ensure_ytdlp())
        if not self.needs_first_run():
            self.new_set.start_watching()
            self._warn_missing_account()
            QTimer.singleShot(1500, self.check_updates)

    def _first_run_done(self) -> None:
        self.status("Listo. Trae tu primera tracklist.")
        self.go("new_set")
        self.new_set.start_watching()
        self.settings_page.refresh()
        # never while the first-run screen is up, but this session checks too once it is done
        QTimer.singleShot(1500, self.check_updates)

    def _warn_missing_account(self) -> None:
        try:
            creds = self.services.get_credentials()
        except CredentialError as e:
            self.new_set.banner.show_message(e.msg_es, "error")
            return
        if creds is None:
            self.new_set.banner.show_message("Falta tu cuenta de Soulseek: añádela en Ajustes.", "warn",
                                             actions=[("Ir a Ajustes", lambda: self.go("settings"))])

    # ---- updates --------------------------------------------------------------------------------------
    def check_updates(self) -> None:
        self.pool.start(lambda t: self.services.check_for_update(), on_ok=self.show_update)

    def show_update(self, info) -> None:
        if not info:
            return
        name = getattr(info, "name_es", None) or f"Tracklister {getattr(info, 'latest', '')} ya está disponible"
        url = getattr(info, "url", None) or config.project_url()
        self.update_banner.show_message(f"{name}. Se descarga desde su página de GitHub; no se instala nada solo.",
                                        "info", actions=[("Ver la novedad", lambda: self.services.open_url(url))])
        self.update_holder.show()

    # ---- the download flow --------------------------------------------------------------------------
    def worker_running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def engine_busy_es(self) -> tuple[str, str] | None:
        """(title, Spanish message) when the engine is already in use, else None.

        ONE engine process at a time: a download (or 'Reintentar fallos'/'Continuar') and the
        Diagnostico would log in with the same account and listen port, and Soulseek drops one."""
        if self.worker_running():
            return "Descarga en curso", "Espera a que termine la descarga actual (o cancélala)."
        if self.diagnostic.running():
            return "Diagnóstico en curso", "Espera a que termine el Diagnóstico (o cancélalo)."
        return None

    def _credentials(self):
        try:
            creds = self.services.get_credentials()
        except CredentialError as e:
            self.prompter.error("Cuenta de Soulseek", e.msg_es)
            return None
        if creds is None:
            self.prompter.error("Cuenta de Soulseek", "Falta tu cuenta de Soulseek. Añádela en Ajustes.")
            self.go("settings")
        return creds

    def start_download(self, name: str, rows: list, sources: list) -> bool:
        busy = self.engine_busy_es()
        if busy:
            self.prompter.inform(*busy)
            return False
        creds = self._credentials()
        if creds is None:
            return False
        try:
            # nothing is written yet: closing a repeated-track question leaves no set folder behind
            session = self.services.create_session(name, rows, sources, persist=False)
        except Exception as e:  # noqa: BLE001
            log.exception("create_session")
            self.prompter.error("No se pudo preparar el set", error_text(e))
            return False
        try:
            hits = session.find_duplicates(self.services.library())
        except Exception as e:  # noqa: BLE001 - a broken library index must not block downloads
            log.exception("find_duplicates")
            self.status(f"No se pudo leer la biblioteca: {error_text(e)}")
            hits = []
        choices = self._ask_duplicates(hits, self.new_set.banner)
        if choices is None:
            return False
        try:
            session.save()
        except Exception as e:  # noqa: BLE001
            log.exception("save session")
            self.prompter.error("No se pudo preparar el set", error_text(e))
            return False
        self.session = session
        self.results.show_session(session, running=True)
        self.go("results")
        self._start_worker("run", creds, choices)
        return True

    def _ask_duplicates(self, hits: list, banner: Banner) -> list | None:
        """Ask about each track already in the library, with both options and «Aplicar a todos los repetidos de
        este set» (G.3): the choices for the worker, or None when a question was closed (nothing starts, and
        `banner` says so)."""
        choices = []
        all_choice = None
        for i, hit in enumerate(hits, start=1):
            if all_choice is not None:
                entry = hit.entries[0] if all_choice == DuplicateChoice.REUSE and hit.entries else None
                choices.append((hit.row.uid, all_choice, entry))
                continue
            ans = self.prompter.ask_duplicate(hit, i, len(hits))
            if ans is None:
                banner.show_message(DUPLICATE_NOT_STARTED_ES, "info")
                return None
            choice, entry, apply_all = ans
            choices.append((hit.row.uid, choice, entry))
            if apply_all:
                all_choice = choice
        return choices

    def run_again(self, mode: str) -> None:
        if self.session is None:
            return
        busy = self.engine_busy_es()
        if busy:
            self.prompter.inform(*busy)
            return
        creds = self._credentials()
        if creds is None:
            return
        # barrido audit AU-2-04: the tracks the library has and this set has no answer for (a «Usar el que ya
        # tengo» whose file was deleted forgets its choice, Z.14) are asked about, as «Descargar» does; first the
        # files deleted with the set open in Descarga, so that question covers them too (AU-3-02)
        self.session.refresh_missing_files()
        try:
            hits = [h for h in self.session.find_duplicates(self.services.library())
                    if h.row.uid not in self.session.doc.duplicate_choices]
        except Exception as e:  # noqa: BLE001 - a broken library index must not block downloads
            log.exception("find_duplicates")
            self.status(f"No se pudo leer la biblioteca: {error_text(e)}")
            hits = []
        choices = self._ask_duplicates(hits, self.results.banner)
        if choices is None:
            return
        self.results.show_session(self.session, running=True)
        self.go("results")
        self._start_worker(mode, creds, choices)

    def _start_worker(self, mode: str, creds, choices) -> None:
        w = SessionWorker(self.session, runner_factory=self.services.make_runner, creds=creds,
                          library_factory=self.services.library, mode=mode, choices=choices)
        w.session_event.connect(self.results.on_session_event)
        w.lossy_requested.connect(self._on_lossy_requested)
        w.completed.connect(self._on_worker_completed)
        w.finished.connect(w.deleteLater)
        self.worker = w
        self.status("Descargando…", 0)
        w.start()

    def _on_lossy_requested(self, rows: list) -> None:
        w = self.worker
        if w is None:
            return
        uids = self.prompter.ask_lossy(rows, self.session.preset if self.session else None)
        w.answer_lossy(uids or set())

    def _on_worker_completed(self, error: str) -> None:
        w = self.worker
        if w is not None:
            w.wait(5000)
        self.worker = None
        self.results.on_finished(error)
        self.nav_buttons["results"].setEnabled(True)
        self.status("La descarga terminó con errores." if error else
                    "Descarga cancelada." if self.results.cancelling else "Descarga terminada.")
        if self._close_when_done:
            QTimer.singleShot(0, self.close)

    def cancel_run(self) -> None:
        if self.worker_running():
            self.worker.stop()
            self.results.mark_cancelling()

    def open_previous_set(self) -> None:
        if self.worker_running():
            return
        start = self.services.settings.library_root or str(Path.home())
        d = self.prompter.pick_folder("Abrir un set anterior", start)
        if not d:
            return
        if not set_doc_path(Path(d)).is_file():
            # the path with the separator of this system (CL-25, Y.12; Windows unchanged)
            where = ".tracklister/set.json" if osplatform.is_macos() else ".tracklister\\set.json"
            self.prompter.error("Abrir un set anterior", "Esa carpeta no es un set de Tracklister "
                                f"(no tiene {where}).")
            return
        try:
            self.session = self.services.load_session(Path(d))
        except Exception as e:  # noqa: BLE001
            self.prompter.error("Abrir un set anterior", error_text(e))
            return
        self.results.show_session(self.session, running=False)
        self.results.on_finished("")
        self.go("results")

    # ---- closing -------------------------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker_running():
            if self._close_when_done:          # already answered «Salir»: it closes by itself when done
                # say it again (another notice may have covered it), never ask again (barrido audit AU-1-06)
                self.status(CLOSING_AFTER_CHECKS_ES, 0)
                self.results.mark_cancelling()
                event.ignore()
                return
            if not self.prompter.confirm("Salir", "Hay una descarga en curso. Si sales, se cancela y se guarda "
                                         "lo que ya esté descargado.", ok="Salir", cancel="Seguir"):
                event.ignore()
                return
            # the download may have ended while the question was open (self.worker is then None): look again,
            # and if it has, just close (barrido audit AU-2-02)
            if self.worker_running():
                self.worker.stop()
                self.results.mark_cancelling()     # as «Cancelar» does (AU-1-06, CL-28)
                if not self.worker.wait(self.CLOSE_WAIT_MS):
                    # the files that already arrived are still being checked and placed: closing now would kill
                    # the process in the middle of a file (QThread destroyed while running)
                    self._close_when_done = True
                    self.status(CLOSING_AFTER_CHECKS_ES, 0)
                    event.ignore()
                    return
        self.pool.cancel_all()
        self.pool.wait_all(5000)
        self.new_set.stop_watching()
        event.accept()
