"""settings.json with values of the wrong type (audit round 2, N6): defaults, never a crash.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import json

import pytest

from tracklister.config import DEFAULT_LISTEN_PORT
from tracklister.core.settings import CustomPreset, Settings, load_settings_checked, settings_from_dict


def test_bad_types_fall_back_to_their_default_one_by_one():
    s, bad = settings_from_dict({
        "theme": ["noche"], "preset_id": 7, "custom_preset": [1, 2], "library_root": {"a": 1},
        "listen_port": "abc", "enrichment_enabled": "sí", "concurrent_downloads": True,
        "last_update_check": "ayer", "ytdlp_path": 3, "first_run_done": True, "engine_id": "sldl-2.6.0"})
    d = Settings()
    assert (s.theme, s.preset_id, s.custom_preset, s.library_root) == (d.theme, d.preset_id, CustomPreset(), None)
    assert s.listen_port == DEFAULT_LISTEN_PORT and s.enrichment_enabled is True and s.concurrent_downloads == 4
    assert s.last_update_check is None and s.ytdlp_path is None
    assert s.first_run_done is True and s.engine_id == "sldl-2.6.0"          # the good ones are kept
    assert sorted(bad) == sorted(["theme", "preset_id", "custom_preset", "library_root", "listen_port",
                                  "enrichment_enabled", "concurrent_downloads", "last_update_check",
                                  "ytdlp_path"])


def test_values_the_app_cannot_use_and_the_custom_preset_fields():
    s, bad = settings_from_dict({"preset_id": "flac_a_tope", "listen_port": 70000,
                                 "custom_preset": {"formats": "flac", "min_mp3_kbps": 256,
                                                   "max_samplerate": "48k", "allow_lossy_fallback": True}})
    assert s.preset_id == "lossless" and s.listen_port == DEFAULT_LISTEN_PORT
    assert s.custom_preset == CustomPreset(min_mp3_kbps=256, allow_lossy_fallback=True)
    assert sorted(bad) == ["custom_preset.formats", "custom_preset.max_samplerate", "listen_port", "preset_id"]


def test_valid_settings_load_unchanged_and_unknown_keys_are_ignored():
    good = Settings(theme="noche", preset_id="personalizado", library_root="D:/Sets", listen_port=50123,
                    custom_preset=CustomPreset(formats=["flac", "mp3"], max_samplerate=48000, max_bitdepth=24),
                    last_update_check=1700000000.5)
    d = good.to_dict()
    d["campo_de_otra_version"] = 1
    s, bad = settings_from_dict(d)
    assert s == good and bad == []
    assert settings_from_dict(None) == (Settings(), [])


@pytest.mark.parametrize("content", ["[1, 2]", '"texto"', "3"])
def test_a_file_that_is_not_a_json_object_is_reported(tmp_path, content):
    p = tmp_path / "settings.json"
    p.write_text(content, encoding="utf-8")
    with pytest.raises(TypeError):
        load_settings_checked(p)


def test_checked_load_reports_the_reset_settings(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"theme": ["x"], "first_run_done": True}), encoding="utf-8")
    s, bad = load_settings_checked(p)
    assert s.first_run_done and s.theme is None and bad == ["theme"]


def test_out_of_range_numbers_go_back_to_their_defaults():
    # AG-18 (T.4 N5): a hand-edited settings.json with -5 searches per window made every download end in
    # «Error inesperado (IndexError)». Out of range counts as not valid, like a wrong type.
    names = ["searches_per_time", "searches_renew_s", "concurrent_downloads", "duration_ok_s", "duration_review_s"]
    s, bad = settings_from_dict({"searches_per_time": -5, "searches_renew_s": 0, "concurrent_downloads": 0,
                                 "duration_ok_s": -1, "duration_review_s": 601})
    assert [getattr(s, n) for n in names] == [34, 220, 4, 3, 10]
    assert sorted(bad) == sorted(names)
    lows = {"searches_per_time": 1, "searches_renew_s": 1, "concurrent_downloads": 1, "duration_ok_s": 0,
            "duration_review_s": 0}
    highs = {"searches_per_time": 1000, "searches_renew_s": 3600, "concurrent_downloads": 16, "duration_ok_s": 600,
             "duration_review_s": 600}
    for edges in (lows, highs):                     # the edges of each range are kept
        s, bad = settings_from_dict(edges)
        assert bad == [] and [getattr(s, n) for n in names] == [edges[n] for n in names]
    s, bad = settings_from_dict({n: v + 1 for n, v in highs.items()})
    assert sorted(bad) == sorted(names) and s == Settings()
