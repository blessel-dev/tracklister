"""The window's single door to the rest of Tracklister: settings, account, engine, sets, inputs.

Owner: GUI step.
SPDX-License-Identifier: GPL-3.0-or-later

- No widgets here. GUI unit tests replace this class with tests/gui/fakes.FakeServices; the
  integration tests (tests/integration) use THIS class with the fake engine and an HttpClient
  over recorded answers (`Services(http=...)`), so nothing leaves the machine.
- inputs/enrich/net are imported lazily inside the methods, through their frozen interface
  (plan.md section 6), so the window still opens if one of them fails to import.
- The Soulseek account only travels through engine.credentials (Windows Credential Manager, or the
  macOS Keychain). Nothing in this module writes or logs it.
- The engine and yt-dlp always run from the copies the app writes to its per-user tools folder, never
  from inside the bundle (engine.spec.resolve_engine, ensure_ytdlp).
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Sequence

from tracklister import config
from tracklister.core import osplatform, quarantine
from tracklister.core.bundled import YtdlpPin, bundled_dir, ytdlp_pin
from tracklister.core.model import SourceRef, TrackRow
from tracklister.core.paths import AppPaths, app_paths
from tracklister.core.settings import Settings, load_settings_checked, save_settings
from tracklister.engine.credentials import CredentialStore, Credentials
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.runner import EngineRunner
from tracklister.engine.spec import (DEFAULT_ENGINE_ID, PLATFORM_ENGINE_PINS, engine_pins, resolve_engine,
                                     sha256_file)
from tracklister.library.index import LibraryIndex
from tracklister.organize.journal import Journal
from tracklister.organize.naming import safe_component
from tracklister.pipeline.session import SetSession

log = logging.getLogger("tracklister.gui")

REORDER_LABEL = "Reordenar carpeta existente"   # organize.reorder.apply_reorder batch label


def _matches_pin(path: Path, pin: YtdlpPin) -> bool:
    """The file is the pinned yt-dlp: same size and SHA-256."""
    try:
        return path.stat().st_size == pin.size and sha256_file(path) == pin.sha256
    except OSError:
        return False


def unavailable_import(source, error: Exception | None = None) -> SimpleNamespace:
    """Same attribute names as inputs.importer.ImportResult, for when the importer cannot load."""
    log.error("importer unavailable: %r", error)
    return SimpleNamespace(kind="texto", rows=[], sources=[], warnings_es=[], candidates=[], chosen=None,
                           suggested_name=None,
                           message_es="No se pudo cargar el importador de tracklists. Reinstala Tracklister.")


class Services:
    def __init__(self, paths: AppPaths | None = None, *, bundle: Path | None = None, http=None):
        self.paths = (paths or app_paths()).ensure()
        self.bundle = bundle if bundle is not None else bundled_dir()
        self.settings_warning_es: str | None = None
        self.settings = self._load_settings()
        self.credentials = CredentialStore()
        self._http = http                    # net.http.HttpClient; tests pass one with a replay transport
        self._http_lock = threading.Lock()

    # ---- settings ---------------------------------------------------------------------------
    def _load_settings(self) -> Settings:
        try:
            settings, invalid = load_settings_checked(self.paths.settings_file)
            if invalid:
                # a value of the wrong type: only that setting goes back to its default (never a crash)
                log.warning("settings with invalid values reset to their defaults: %s", ", ".join(invalid))
                self.settings_warning_es = ("Algunos ajustes no eran válidos y han vuelto a su valor de serie. "
                                            "Revísalos en Ajustes.")
            return settings
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

    # ---- account (Windows Credential Manager / macOS Keychain) ------------------------------
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

    def create_session(self, name: str, rows: list[TrackRow], sources: list[SourceRef], *,
                       persist: bool = True) -> SetSession:
        """persist=False: nothing of the set is written until session.save() (see SetSession.create)."""
        root = self.library_root()
        if root is None:
            raise ValueError("Elige la carpeta de tu biblioteca en Ajustes.")
        root.mkdir(parents=True, exist_ok=True)
        return SetSession.create(name, rows, sources, self.settings, root, self.paths, persist=persist)

    def load_session(self, set_dir: Path) -> SetSession:
        return SetSession.load(Path(set_dir), self.settings, self.paths)

    # ---- engine -------------------------------------------------------------------------------
    def engine_id(self) -> str:
        """The engine this platform runs for the saved setting. On macOS an engine that only another platform
        ships (sldl 2.6.0 in a settings.json copied from a PC) becomes the default engine, with a warning in
        the log. Every other id, and every id on Windows, is used as saved (an unknown one still gets
        «Motor desconocido» from resolve_engine)."""
        eid = self.settings.engine_id
        if osplatform.is_macos() and eid not in engine_pins() and \
                any(eid in table for table in PLATFORM_ENGINE_PINS.values()):
            log.warning("engine %s is not shipped on macOS: using %s", eid, DEFAULT_ENGINE_ID)
            return DEFAULT_ENGINE_ID
        return eid

    def make_runner(self) -> EngineRunner:
        """Resolve (and on first use unpack + verify) the pinned engine. Raises EngineMissing."""
        spec = resolve_engine(self.engine_id(), self.paths, self.bundle)
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

    def merge_rows_detailed(self, base: list[TrackRow], extra: list[TrackRow], *, keep_positions: bool = False):
        """inputs.merge.MergeResult: rows + which uids were inserted, replaced an ID row or were appended."""
        from tracklister.inputs.merge import merge_sources_detailed
        return merge_sources_detailed(base, extra, keep_positions=keep_positions)

    def recompute_gaps(self, rows: list[TrackRow], dismissed=()):
        """inputs.gaps.GapRecompute with the durations the rows have now (R1): only for tables with trackid.net
        rows; the caller makes sure the set has never been downloaded."""
        from tracklister.inputs.gaps import recompute_gaps
        return recompute_gaps(rows, threshold_s=int(self.settings.gap_id_threshold_s), dismissed=dismissed)

    def gap_keys(self, rows: list[TrackRow], indices) -> list:
        """inputs.gaps.gap_key of the automatic gap rows among `indices` (the window remembers the gaps the
        user deletes, so 'Completar datos' does not bring them back)."""
        try:
            from tracklister.inputs.gaps import gap_key, is_auto_gap
        except ImportError:
            return []
        return [gap_key(rows, i) for i in indices if 0 <= i < len(rows) and is_auto_gap(rows[i])]

    def set_has_files(self, name: str) -> bool:
        """Does the set folder of this name already hold files of the set? (decision B: from then on its
        rows are never renumbered on their own)."""
        from tracklister.pipeline.session import set_has_files
        d = self.set_dir_for(name) if name else None
        return d is not None and set_has_files(d)

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
        """The copy of yt-dlp the app runs: <tools_dir>/yt-dlp.exe (yt-dlp on macOS), unless the settings say."""
        return (Path(self.settings.ytdlp_path) if self.settings.ytdlp_path
                else self.paths.tools_dir / ytdlp_pin().exe_name)

    def ensure_ytdlp(self) -> Path | None:
        """Copy the bundled yt-dlp to the per-user tools folder (updatable without admin); the app only runs
        that copy. A copy that is already there is used as it is, never hashed again ('yt-dlp -U' updates it).

        macOS only (DECISIONES Y): the copy is written data-only (core.quarantine.copy_data_only), never with
        shutil: on macOS shutil copies through fcopyfile(3), which carries the bundled file's
        com.apple.quarantine over, and macOS would then block yt-dlp. Before the copy is used, its size and
        SHA-256 must match the pin, or it is deleted and the next candidate is tried; then it is made
        executable (0755). An existing copy that carries the quarantine (left by a build that copied with
        shutil) is copied again; only if macOS itself marks the fresh, checked copy is that one attribute
        removed from it (core.quarantine.clear_ours)."""
        exe = self.ytdlp_exe()
        stale = False
        if exe.is_file():
            if not (osplatform.is_macos() and quarantine.carries(exe)):
                return exe
            log.warning("the yt-dlp copy carries %s: copying it again", quarantine.QUARANTINE)
            stale = True
        pin = ytdlp_pin()
        candidates = []
        if self.bundle is not None:
            candidates += [self.bundle / pin.asset_name, self.bundle / "tools" / pin.asset_name]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / pin.asset_name)
        for c in candidates:
            if c.is_file():
                # to a .part file first: an interrupted copy never leaves a half-written yt-dlp.exe that
                # every later start would take for a good one
                part = exe.with_name(exe.name + ".part")
                try:
                    exe.parent.mkdir(parents=True, exist_ok=True)
                    if osplatform.is_macos():
                        quarantine.copy_data_only(c, part)
                        if not _matches_pin(part, pin):
                            log.error("bundled %s does not match its pin (size or SHA-256): not used", c.name)
                            part.unlink(missing_ok=True)
                            continue
                        os.chmod(part, 0o755)
                        if quarantine.carries(part):        # only if macOS itself marked the checked copy
                            quarantine.clear_ours(part, self.paths.tools_dir)
                    else:
                        shutil.copy2(c, part)
                    os.replace(part, exe)
                    return exe
                except OSError as e:
                    log.error("cannot copy yt-dlp: %s", e)
                    try:
                        part.unlink(missing_ok=True)
                    except OSError:
                        pass
        return exe if stale and exe.is_file() else None

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

    def http(self):
        """ONE HTTP client for the whole window (live transport), so the per-host spacing
        (MusicBrainz at most 1 request per second, iTunes about 20 per minute) also holds across
        successive imports, 'Completar datos' and the update check."""
        with self._http_lock:
            if self._http is None:
                from tracklister.net.http import HttpClient, requests_transport
                self._http = HttpClient(requests_transport())
            return self._http

    def enrich(self, rows: list[TrackRow], on_progress: Callable[[int, int], None] | None = None,
               cancel: threading.Event | None = None) -> list:
        from tracklister.enrich.enricher import Enricher
        return Enricher(self.http(), self.paths.enrich_cache_file).enrich(rows, on_progress=on_progress,
                                                                         cancel=cancel)

    def check_for_update(self, force: bool = False):
        try:
            from tracklister.net.update_check import check_for_update
            http = self.http()
        except ImportError:
            return None
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
                              windows_version=osplatform.os_version(), listen_port=int(self.settings.listen_port),
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
