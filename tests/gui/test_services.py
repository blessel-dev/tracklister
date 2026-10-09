"""Audit round 2: a damaged settings.json never stops the window (N6); the yt-dlp copy is atomic (N4).

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.gui.fakes import FakeServices
from tracklister.config import DEFAULT_LISTEN_PORT
from tracklister.core.paths import app_paths
from tracklister.gui.services import Services

pytestmark = pytest.mark.gui


def test_r2_n6_settings_with_bad_types_still_open_the_window(qtbot, app, prompter, tmp_path):
    from tracklister.gui.app import build_window
    settings_file = app_paths().ensure().settings_file
    settings_file.write_text(json.dumps({
        "theme": ["noche"], "custom_preset": [1], "listen_port": "abc", "preset_id": 3,
        "first_run_done": True, "legal_notice_accepted": True, "library_root": str(tmp_path / "biblioteca"),
        "watch_downloads_folder": False, "enrichment_enabled": False}), encoding="utf-8")
    services = FakeServices()
    s = services.settings
    assert (s.theme, s.listen_port, s.preset_id, s.first_run_done) == (None, DEFAULT_LISTEN_PORT, "lossless", True)
    w = build_window(services, app=app, prompter=prompter)
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    assert w.themes.theme.id == "hormigon" and w.current_page() == "new_set"     # the good values are kept
    assert "no eran válidos" in w.new_set.banner.message()
    assert w.settings_page.port.value() == DEFAULT_LISTEN_PORT
    assert settings_file.is_file()                     # nothing was moved away: only the bad values were reset


def test_r2_n4_an_interrupted_ytdlp_copy_leaves_no_broken_exe(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    (bundle / "tools").mkdir(parents=True)
    bundled = bundle / "tools" / "yt-dlp.exe"
    bundled.write_bytes(b"MZ" + bytes(range(256)) * 400)
    s = Services(bundle=bundle)
    target = s.ytdlp_exe()
    real_copy = shutil.copy2

    def dies_half_way(src, dst, *a, **kw):
        Path(dst).write_bytes(Path(src).read_bytes()[:1000])
        raise OSError(28, "No queda espacio en el disco")
    monkeypatch.setattr(shutil, "copy2", dies_half_way)
    assert s.ensure_ytdlp() is None
    assert not target.exists() and not target.with_name(target.name + ".part").exists()
    monkeypatch.setattr(shutil, "copy2", real_copy)
    assert s.ensure_ytdlp() == target and target.read_bytes() == bundled.read_bytes()
    assert not target.with_name(target.name + ".part").exists()
