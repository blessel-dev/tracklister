"""Entry point of the window: tracklister.gui.app.run(argv) -> int.

Owner: GUI step.
SPDX-License-Identifier: GPL-3.0-or-later

    python -m tracklister                      the app
    python -m tracklister --screenshot X.png   open, save a capture of the window after ~1.5 s, exit
    python -m tracklister --quit-after 3000    open and close itself (exe smoke test)

Fonts are registered before any widget exists. Unexpected errors go to
%LOCALAPPDATA%\\Tracklister\\logs\\tracklister.log (never with the account) and to a message box.
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from tracklister import config
from tracklister.assets import asset_path, load_tokens
from tracklister.core.paths import app_paths
from tracklister.gui import gcguard
from tracklister.gui.theme import ThemeManager, register_fonts

log = logging.getLogger("tracklister.gui")
APP_USER_MODEL_ID = "Tracklister.Tracklister"


def prepare_app(app: QApplication) -> QApplication:
    """Application-wide setup shared by run(), the tests and tools/screenshots.py."""
    app.setApplicationName(config.APP_NAME)
    app.setOrganizationName(config.APP_NAME)
    app.setApplicationVersion(config.APP_VERSION)
    app.setStyle("Fusion")
    register_fonts()
    app.setWindowIcon(QIcon(str(asset_path(load_tokens()["app_icon"]))))
    gcguard.install(app)            # cyclic GC only in the GUI thread (see gcguard.py)
    return app


def create_app(argv) -> QApplication:
    app = QApplication.instance() or QApplication(list(argv))
    return prepare_app(app)


def build_window(services=None, *, app: QApplication | None = None, prompter=None):
    """Services + theme + MainWindow, without showing it (tests and tools call this too)."""
    from tracklister.gui.main_window import MainWindow
    from tracklister.gui.services import Services
    app = app or QApplication.instance()
    services = services or Services()
    themes = ThemeManager(app, services.settings.theme, services.paths.cache_dir / "ui")
    return MainWindow(services, themes, prompter=prompter)


def _setup_logging() -> logging.Handler | None:
    try:
        logs = app_paths().ensure().logs_dir
        handler = logging.handlers.RotatingFileHandler(logs / "tracklister.log", maxBytes=1_000_000,
                                                       backupCount=3, encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("tracklister")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return handler


def _install_excepthook(log_file: Path | None) -> None:
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.error("uncaught: %s", text)
        if QApplication.instance() is not None:
            where = f"\n\nDetalles en {log_file}" if log_file else ""
            QMessageBox.warning(None, config.APP_NAME,
                                f"Algo ha fallado: {exc_type.__name__}: {exc}{where}")
    sys.excepthook = hook


def _set_app_user_model_id() -> None:
    """So Windows groups the taskbar button under Tracklister's own icon."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


def _parse(argv) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="tracklister", add_help=True)
    p.add_argument("--screenshot", metavar="PNG", help="guarda una captura de la ventana y sale")
    p.add_argument("--quit-after", metavar="MS", type=int, default=0, help="se cierra sola tras MS milisegundos")
    args, _unknown = p.parse_known_args(list(argv)[1:])
    return args


def run(argv) -> int:
    args = _parse(argv)
    handler = _setup_logging()
    previous_hook = sys.excepthook
    _install_excepthook(Path(handler.baseFilename) if handler is not None else None)
    _set_app_user_model_id()
    try:
        app = create_app(argv)
        win = build_window(app=app)
        win.show()
        win.start_background()
        if args.screenshot:
            target = Path(args.screenshot)

            def shoot():
                target.parent.mkdir(parents=True, exist_ok=True)
                win.grab().save(str(target))
                win.close()
                app.quit()
            QTimer.singleShot(1500, shoot)
        elif args.quit_after:
            QTimer.singleShot(int(args.quit_after), lambda: (win.close(), app.quit()))
        code = app.exec()
        win.deleteLater()
        return int(code)
    finally:
        sys.excepthook = previous_hook
        if handler is not None:
            logging.getLogger("tracklister").removeHandler(handler)
            handler.close()
