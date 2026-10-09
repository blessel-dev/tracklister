"""Entry points: `python -m tracklister` -> tracklister.gui.app.run(argv).

SPDX-License-Identifier: GPL-3.0-or-later

run() owns the event loop (app.exec()), so it is exercised in a child process, exactly like the
exe smoke test: offscreen Qt, a temp TRACKLISTER_HOME and keyring's null backend (the child never
reads the real Windows Credential Manager). The first-run screen makes no network request.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtGui import QImage

import tracklister

pytestmark = [pytest.mark.gui, pytest.mark.slow]


def _env(tmp_path: Path) -> dict:
    src = Path(tracklister.__file__).resolve().parents[1]
    return dict(os.environ, TRACKLISTER_HOME=str(tmp_path / "home"), QT_QPA_PLATFORM="offscreen",
                PYTHONPATH=str(src), PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring")


def test_python_m_tracklister_opens_the_first_run_screen(tmp_path):
    out = tmp_path / "primer-inicio.png"
    r = subprocess.run([sys.executable, "-m", "tracklister", "--screenshot", str(out)], capture_output=True,
                       text=True, env=_env(tmp_path), timeout=180)
    assert r.returncode == 0, r.stderr[-2000:]
    img = QImage(str(out))
    assert img.width() >= 980 and img.height() >= 640
    log = tmp_path / "home" / "data" / "logs" / "tracklister.log"
    assert not log.exists() or "uncaught" not in log.read_text(encoding="utf-8")


def test_flags_and_quit_after(tmp_path):
    import tracklister.__main__ as entry
    assert callable(entry.main)
    r = subprocess.run([sys.executable, "-m", "tracklister", "--help"], capture_output=True, text=True,
                       env=_env(tmp_path), timeout=120)
    assert r.returncode == 0 and "--screenshot" in r.stdout and "--quit-after" in r.stdout
    r = subprocess.run([sys.executable, "-m", "tracklister", "--quit-after", "800"], capture_output=True,
                       text=True, env=_env(tmp_path), timeout=180)
    assert r.returncode == 0, r.stderr[-2000:]
