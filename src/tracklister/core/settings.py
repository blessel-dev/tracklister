"""Per-user settings (%APPDATA%\\Tracklister\\settings.json). Owner: core (frozen during the parallel phase).

Never stores the Soulseek username or password: both live in Windows Credential Manager
through tracklister.engine.credentials (keyring). No API keys either.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tracklister.config import DEFAULT_LISTEN_PORT
from tracklister.core.jsonio import read_json, write_json
from tracklister.core.model import SETTINGS_SCHEMA


@dataclass
class CustomPreset:
    """'Personalizado' preset as chosen in Ajustes."""
    formats: list[str] = field(default_factory=lambda: ["flac", "wav", "aiff"])
    min_mp3_kbps: int = 320
    max_samplerate: int | None = None
    max_bitdepth: int | None = None
    allow_lossy_fallback: bool = False   # ask-per-set MP3 320 fallback like "Lossless"


@dataclass
class Settings:
    theme: str | None = None             # "hormigon" | "noche"; None -> assets tokens default_theme
    preset_id: str = "lossless"          # lossless | cdj_antiguos | solo_mp3_320 | personalizado
    custom_preset: CustomPreset = field(default_factory=CustomPreset)
    library_root: str | None = None      # chosen at first run
    listen_port: int = DEFAULT_LISTEN_PORT
    engine_id: str = "sockseek-3.0.5"    # or "sldl-2.6.0" (fallback through the same adapter)
    enrichment_enabled: bool = True      # 02 section 5.6
    spectral_check_enabled: bool = True
    watch_downloads_folder: bool = True  # pick up new trackid CSVs from Descargas (02 section 5.4)
    gap_id_threshold_s: int = 90         # trackid gaps -> "ID (hueco)" rows (02 section 5.7)
    duration_ok_s: int = 3
    duration_review_s: int = 10
    concurrent_downloads: int = 4
    searches_per_time: int = 34
    searches_renew_s: int = 220
    first_run_done: bool = False
    share_notice_shown: bool = False
    legal_notice_accepted: bool = False
    last_update_check: float | None = None   # epoch seconds
    ytdlp_path: str | None = None            # None -> <tools_dir>/yt-dlp.exe
    schema: str = SETTINGS_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Settings":
        d = dict(d or {})
        names = {f.name for f in dataclasses.fields(cls)}
        cp = d.pop("custom_preset", None) or {}
        cp_names = {f.name for f in dataclasses.fields(CustomPreset)}
        s = cls(**{k: v for k, v in d.items() if k in names and k != "schema"})
        s.custom_preset = CustomPreset(**{k: v for k, v in cp.items() if k in cp_names})
        return s


def load_settings(path: Path) -> Settings:
    return Settings.from_dict(read_json(path, default={}))


def save_settings(path: Path, s: Settings) -> None:
    write_json(path, s.to_dict())
