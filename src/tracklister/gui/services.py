"""The window's single door to the rest of Tracklister: settings, account, engine, sets, inputs.

Owner: GUI step.
SPDX-License-Identifier: GPL-3.0-or-later

- No widgets here. Tests replace this class with tests/gui/fakes.FakeServices.
- inputs/enrich/net are imported lazily inside the methods, through their frozen interface
  (plan.md section 6), so the window still opens if one of them fails to import.
- The Soulseek account only travels through engine.credentials (Windows Credential Manager).
  Nothing in this module writes or logs it.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Sequence

from tracklister import config
from tracklister.core.model import SourceRef, TrackRow
from tracklister.core.paths import AppPaths, app_paths
from tracklister.core.settings import Settings, load_settings, save_settings
from tracklister.engine.credentials import CredentialStore, Credentials
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.runner import EngineRunner
from tracklister.engine.spec import resolve_engine
from tracklister.library.index import LibraryIndex
from tracklister.organize.journal import Journal
from tracklister.organize.naming import safe_component
from tracklister.pipeline.session import SetSession

log = logging.getLogger("tracklister.gui")

REORDER_LABEL = "Reordenar carpeta existente"   # organize.reorder.apply_reorder batch label
YTDLP_EXE = "yt-dlp.exe"


def windows_version() -> str:
    return f"Windows {platform.release()} (build {platform.version()})"


def bundled_dir() -> Path | None:
    """Folder of the frozen exe (PyInstaller); None when running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def unavailable_import(source, error: Exception | None = None) -> SimpleNamespace:
    """Same attribute names as inputs.importer.ImportResult, for when the importer cannot load."""
    log.error("importer unavailable: %r", error)
    return SimpleNamespace(kind="texto", rows=[], sources=[], warnings_es=[], candidates=[], chosen=None,
                           suggested_name=None,
                           message_es="No se pudo cargar el importador de tracklists. Reinstala Tracklister.")


class Services:
    def __init__(self, paths: AppPaths | None = None, *, bundle: Path | None = None):
        self.paths = (paths or app_paths()).ensure()
        self.bundle = bundle if bundle is not None else bundled_dir()
        self.settings_warning_es: str | None = None
        self.settings = self._load_settings()
        self.credentials = CredentialStore()

    # ---- settings ---------------------------------------------------------------------------
    def _load_settings(self) -> Settings:
        try:
            return load_settings(self.paths.settings_file)
        except (ValueError, TypeError) as e:
            log.error("settings unreadable: %s", e)
            backup = self.paths.settings_file.with_name("settings-danado.json")
            try:
                os.replace(self.paths.settings_file, backup)
            except OSError:
                pass
            self.settings_warning_es = ("Tus ajustes estaban dañados y se han restablecido. "
                                        f"Copia del archivo anterior: {backup.name}.")
            return Settings()

    def save_settings(self) -> None:
        save_settings(self.paths.settings_file, self.settings)

    # ---- account (Windows Credential Manager) ----------------------------------------------
    def get_credentials(self) -> Credentials | None:
        """Raises engine.credentials.CredentialError (msg_es) when the manager is unavailable."""
        return self.credentials.get()

    def save_credentials(self, username: str, password: str) -> None:
        self.credentials.set(Credentials(username.strip(), password))

    def clear_credentials(self) -> None:
        self.credentials.clear()

    # ---- folders, library, sets ---------------------------------------------------------------
    def library_root(self) -> Path | None:
        return Path(self.settings.library_root) if self.settings.library_root else None

    def set_dir_for(self, name: str) -> Path | None:
        root = self.library_root()
        return root / safe_component(name) if root and name.strip() else None

    def library(self) -> LibraryIndex:
        lib = LibraryIndex(self.paths.library_file)
        lib.load()
        return lib

    def rebuild_library(self) -> int:
        lib = LibraryIndex(self.paths.library_file)
        root = self.library_root()
        n = lib.rebuild(root) if root else 0
        lib.save()
        return n

    def create_session(self, name: str, rows: list[TrackRow], sources: list[SourceRef]) -> SetSession:
        root = self.library_root()
        if root is None:
            raise ValueError("Elige la carpeta de tu biblioteca en Ajustes.")
        root.mkdir(parents=True, exist_ok=True)
        return SetSession.create(name, rows, sources, self.settings, root, self.paths)

    def load_session(self, set_dir: Path) -> SetSession:
        return SetSession.load(Path(set_dir), self.settings, self.paths)

    # ---- engine -------------------------------------------------------------------------------
    def make_runner(self) -> EngineRunner:
        """Resolve (and on first use unpack + verify) the pinned engine. Raises EngineMissing."""
        spec = resolve_engine(self.settings.engine_id, self.paths, self.bundle)
        budget = SearchBudget(self.paths.search_budget_file, int(self.settings.searches_per_time),
                              int(self.settings.searches_renew_s))
        return EngineRunner(spec, budget)

    # ---- inputs (lazy, frozen interface: plan.md section 6) -----------------------------------
    def import_source(self, source: str | Path):
        try:
            from tracklister.inputs.importer import import_source
        except ImportError as e:
            return unavailable_import(source, e)
        return import_source(source, ytdlp=self.ytdlp(), gap_threshold_s=int(self.settings.gap_id_threshold_s))

    def merge_rows(self, base: list[TrackRow], extra: list[TrackRow]) -> list[TrackRow]:
        from tracklister.inputs.merge import merge_sources
        return merge_sources(base, extra)

    def is_trackid_csv(self, path: Path) -> bool:
        try:
            from tracklister.inputs.detect import InputKind, detect
        except ImportError:
            return False
        try:
            return detect(Path(path)) == InputKind.TRACKID_CSV
        except Exception:  # noqa: BLE001 - a half-written download must not break the window
            return False

    def ytdlp_exe(self) -> Path:
        return Path(self.settings.ytdlp_path) if self.settings.ytdlp_path else self.paths.tools_dir / YTDLP_EXE

    def ensure_ytdlp(self) -> Path | None:
        """Copy the bundled yt-dlp.exe to the per-user tools folder (updatable without admin)."""
        exe = self.ytdlp_exe()
        if exe.is_file():
            return exe
        candidates = []
        if self.bundle is not None:
            candidates += [self.bundle / YTDLP_EXE, self.bundle / "tools" / YTDLP_EXE]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / YTDLP_EXE)
        for c in candidates:
            if c.is_file():
                try:
                    exe.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(c, exe)
                    return exe
                except OSError as e:
                    log.error("cannot copy yt-dlp: %s", e)
        return None

    def ytdlp(self):
        try:
            from tracklister.inputs.ytdlp import YtDlp
        except ImportError:
            return None
        return YtDlp(self.ytdlp_exe(), self.paths.ytdlp_cache_dir)

    def ytdlp_version(self) -> str | None:
        y = self.ytdlp()
        if y is None or not y.available():
            return None
        return y.version()

    def update_ytdlp(self) -> tuple[bool, str]:
        self.ensure_ytdlp()
        y = self.ytdlp()
        if y is None or not y.available():
            return False, "No se encuentra yt-dlp. Vuelve a descomprimir Tracklister completo."
        return y.update()

    def enrich(self, rows: list[TrackRow], on_progress: Callable[[int, int], None] | None = None,
               cancel: threading.Event | None = None) -> list:
        from tracklister.enrich.enricher import Enricher
        from tracklister.net.http import HttpClient, requests_transport
        http = HttpClient(requests_transport())
        return Enricher(http, self.paths.enrich_cache_file).enrich(rows, on_progress=on_progress, cancel=cancel)

    def check_for_update(self, force: bool = False):
        try:
            from tracklister.net.http import HttpClient, requests_transport
            from tracklister.net.update_check import check_for_update
        except ImportError:
            return None
        http = HttpClient(requests_transport())
        return check_for_update(http, current=config.APP_VERSION, state_path=self.paths.update_state_file,
                                now=time.time(), force=force)

    # ---- reorder an old folder -----------------------------------------------------------------
    def propose_reorder(self, folder: Path, rows: list[TrackRow]) -> list:
        from tracklister.organize.reorder import propose_reorder
        return propose_reorder(Path(folder), rows)

    def apply_reorder(self, folder: Path, proposals: Sequence) -> str:
        from tracklister.organize.reorder import apply_reorder
        return apply_reorder(Path(folder), list(proposals), Journal(Path(folder)))

    def can_undo_reorder(self, folder: Path) -> bool:
        if not folder or not Path(folder).is_dir():
            return False
        batches = Journal(Path(folder)).batches()
        return bool(batches) and batches[-1].get("label_es") == REORDER_LABEL

    def undo_reorder(self, folder: Path) -> list[str]:
        if not self.can_undo_reorder(folder):
            return ["No hay ningún reordenado que deshacer en esta carpeta."]
        return Journal(Path(folder)).undo_last()

    # ---- Diagnostico ------------------------------------------------------------------------------
    def run_diagnostic(self, rows: list[TrackRow], creds: Credentials, *, download: bool, max_rows: int,
                       on_event: Callable | None = None,
                       cancel: threading.Event | None = None) -> tuple[str, Path | None]:
        """Search-only by default. Returns (redacted report, saved file or None)."""
        from tracklister.diagnostics.redact import Redactor
        from tracklister.diagnostics.report import build_report
        from tracklister.diagnostics.run import run_diagnostic
        runner = self.make_runner()
        diag = run_diagnostic(rows, runner, creds, download=download, max_rows=max_rows, on_event=on_event,
                              cancel=cancel, settings=self.settings, paths=self.paths)
        redactor = Redactor(secrets=[creds.username, creds.password])
        report = build_report(diag, app_version=config.APP_VERSION, engine_id=runner.spec.engine_id,
                              windows_version=windows_version(), listen_port=int(self.settings.listen_port),
                              redactor=redactor)
        path = self.paths.logs_dir / f"Diagnostico_{datetime.now():%Y-%m-%d_%H%M%S}.txt"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(report, encoding="utf-8")
        except OSError as e:
            log.error("cannot save diagnostic report: %s", e)
            path = None
        return report, path

    # ---- desktop -----------------------------------------------------------------------------------
    def open_url(self, url: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(url))

    def open_path(self, path: Path) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def copy_text(self, text: str) -> None:
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(text)
