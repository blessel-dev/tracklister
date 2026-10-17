"""Per-user locations per platform (1.1): Application Support on macOS, APPDATA/LOCALAPPDATA on Windows.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tracklister.core.paths import ENV_HOME, AppPaths, app_paths

FILES_AND_FOLDERS = ("settings_file", "library_file", "update_state_file", "cache_dir", "enrich_cache_file",
                     "ytdlp_cache_dir", "work_dir", "tools_dir", "logs_dir", "search_budget_file")


def _all(p: AppPaths) -> dict[str, Path]:
    return {name: getattr(p, name) for name in FILES_AND_FOLDERS}


@pytest.fixture
def home(monkeypatch, tmp_path):
    """A user home in tmp, and no TRACKLISTER_HOME (the conftest sets one for every test)."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.delenv(ENV_HOME, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: h))
    return h


def test_macos_uses_application_support_for_everything(as_macos, home, monkeypatch):
    # Windows variables do not matter on a Mac (they could come from the test machine)
    monkeypatch.setenv("APPDATA", str(home / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "Local"))
    p = app_paths()
    support = home / "Library" / "Application Support" / "Tracklister"
    assert p.config_dir == support and p.data_dir == support
    assert p.settings_file == support / "settings.json" and p.tools_dir == support / "tools"
    assert p.logs_dir == support / "logs" and p.work_dir == support / "work"
    every = _all(p)
    assert len(set(every.values())) == len(every), every            # config_dir = data_dir: nothing collides
    p.ensure()
    assert all(getattr(p, d).is_dir() for d in ("cache_dir", "work_dir", "tools_dir", "logs_dir"))
    assert not (home / "AppData").exists()


def test_windows_keeps_appdata_and_localappdata(as_windows, home, monkeypatch):
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    p = app_paths()
    assert p.config_dir == home / "AppData" / "Roaming" / "Tracklister"
    assert p.data_dir == home / "AppData" / "Local" / "Tracklister"
    assert p.tools_dir == home / "AppData" / "Local" / "Tracklister" / "tools"
    every = _all(p)
    assert len(set(every.values())) == len(every)


def test_windows_without_the_variables_falls_back_like_1_0(as_windows, home, monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    p = app_paths()
    assert p.config_dir == home / "AppData" / "Roaming" / "Tracklister"
    assert p.data_dir == home / "AppData" / "Local" / "Tracklister"


@pytest.mark.parametrize("plat", ["as_macos", "as_windows"])
def test_tracklister_home_wins_on_both(plat, request, monkeypatch, tmp_path):
    request.getfixturevalue(plat)
    monkeypatch.setenv(ENV_HOME, str(tmp_path / "tlhome2"))
    p = app_paths()
    assert p.config_dir == tmp_path / "tlhome2" / "config" and p.data_dir == tmp_path / "tlhome2" / "data"
    assert p.tools_dir == tmp_path / "tlhome2" / "data" / "tools"
