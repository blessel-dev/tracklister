"""Per-user locations. Owner: core (frozen during the parallel phase).

Real app: config in %APPDATA%\\Tracklister, data/cache/work in %LOCALAPPDATA%\\Tracklister.
Tests and screenshot tools set TRACKLISTER_HOME to a temp dir; then everything lives under it.
The engine work dir is deliberately SHORT (LOCALAPPDATA) to stay far from MAX_PATH.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_HOME = "TRACKLISTER_HOME"


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    data_dir: Path

    @property
    def settings_file(self) -> Path:
        return self.config_dir / "settings.json"

    @property
    def library_file(self) -> Path:
        return self.config_dir / "library.json"

    @property
    def update_state_file(self) -> Path:
        return self.config_dir / "update.json"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def enrich_cache_file(self) -> Path:
        return self.cache_dir / "enrich.json"

    @property
    def ytdlp_cache_dir(self) -> Path:
        return self.cache_dir / "yt-dlp"

    @property
    def work_dir(self) -> Path:
        """Engine passes: <work_dir>/<set_id[:8]>/p<NN>/ (input.csv, index.csv, engine.log, in/)."""
        return self.data_dir / "work"

    @property
    def tools_dir(self) -> Path:
        """Unpacked engine (engines/<engine_id>/) and the updatable yt-dlp.exe."""
        return self.data_dir / "tools"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def search_budget_file(self) -> Path:
        return self.data_dir / "search-budget.json"

    def ensure(self) -> "AppPaths":
        for p in (self.config_dir, self.data_dir, self.cache_dir, self.work_dir,
                  self.tools_dir, self.logs_dir):
            p.mkdir(parents=True, exist_ok=True)
        return self


def app_paths() -> AppPaths:
    home = os.environ.get(ENV_HOME)
    if home:
        h = Path(home)
        return AppPaths(config_dir=h / "config", data_dir=h / "data")
    appdata = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return AppPaths(config_dir=appdata / "Tracklister", data_dir=local / "Tracklister")
