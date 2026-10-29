"""Per-user settings (%APPDATA%\\Tracklister\\settings.json). Owner: core (frozen during the parallel phase).

Never stores the Soulseek username or password: both live in Windows Credential Manager
through tracklister.engine.credentials (keyring). No API keys either.

A value of the wrong type (a hand-edited or damaged file: "theme": ["x"], "custom_preset": [1],
"listen_port": "abc"...) or a number out of its range ("searches_per_time": -5, AG-18) never stops
the app: that one setting goes back to its default and the others are kept (settings_from_dict
reports which ones). Only a file that is not a JSON object at all raises TypeError (the GUI then
backs it up and starts from the defaults).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tracklister.config import DEFAULT_LISTEN_PORT
from tracklister.core.jsonio import read_json, write_json
from tracklister.core.model import SETTINGS_SCHEMA

# engine.presets.PresetId values (core cannot import the engine package)
PRESET_IDS = ("lossless", "cdj_antiguos", "solo_mp3_320", "personalizado")


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
        return settings_from_dict(d)[0]


def _type_ok(value: Any, annotation: str) -> bool:
    """Does a JSON value fit a field annotation ("int", "str | None", "list[str]"...)?"""
    for kind in (k.strip() for k in annotation.split("|")):
        if kind == "None" and value is None:
            return True
        if kind == "bool" and isinstance(value, bool):
            return True
        if kind == "int" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if kind == "float" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if kind == "str" and isinstance(value, str):
            return True
        if kind == "list[str]" and isinstance(value, list) and all(isinstance(x, str) for x in value):
            return True
    return False


# Inclusive ranges of the numbers the app cannot work with outside them (AG-18, T.4 N5): a hand-edited
# "searches_per_time": -5 made every download end in «Error inesperado (IndexError)» (engine/ratelimit.py), and
# 0 downloads at a time went to the engine as it was. Out of range counts as not valid, like a wrong type.
_RANGES = {
    "listen_port": (1, 65535),
    "searches_per_time": (1, 1000),
    "searches_renew_s": (1, 3600),
    "concurrent_downloads": (1, 16),
    "duration_ok_s": (0, 600),
    "duration_review_s": (0, 600),
}


def _value_ok(name: str, value: Any) -> bool:
    """The few values the app cannot work with even when the type is right."""
    if name == "preset_id":
        return value in PRESET_IDS
    if name in _RANGES:
        low, high = _RANGES[name]
        return low <= value <= high
    return True


def _fields(cls, d: dict[str, Any], prefix: str = "") -> tuple[dict[str, Any], list[str]]:
    good: dict[str, Any] = {}
    bad: list[str] = []
    for f in dataclasses.fields(cls):
        if f.name not in d or f.name in ("schema", "custom_preset"):
            continue
        v = d[f.name]
        if _type_ok(v, str(f.type)) and _value_ok(f.name, v):
            good[f.name] = v
        else:
            bad.append(prefix + f.name)
    return good, bad


def settings_from_dict(d: dict[str, Any] | None) -> tuple[Settings, list[str]]:
    """(settings, names of the settings that were not valid and went back to their default)."""
    if d is None:
        d = {}
    if not isinstance(d, dict):
        raise TypeError("settings.json no contiene un objeto JSON")
    good, bad = _fields(Settings, d)
    s = Settings(**good)
    cp = d.get("custom_preset")
    if isinstance(cp, dict):
        cp_good, cp_bad = _fields(CustomPreset, cp, prefix="custom_preset.")
        s.custom_preset = CustomPreset(**cp_good)
        bad += cp_bad
    elif cp is not None:
        bad.append("custom_preset")
    return s, bad


def load_settings(path: Path) -> Settings:
    return Settings.from_dict(read_json(path, default={}))


def load_settings_checked(path: Path) -> tuple[Settings, list[str]]:
    """Like load_settings, plus the names of the settings that went back to their default."""
    return settings_from_dict(read_json(path, default={}))


def save_settings(path: Path, s: Settings) -> None:
    write_json(path, s.to_dict())
