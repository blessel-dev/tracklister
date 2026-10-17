"""Bundled tools (1.1): the yt-dlp pin per platform and where the frozen app keeps its data.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import sys

from tracklister.core import osplatform
from tracklister.core.bundled import YTDLP_PINS, YtdlpPin, bundled_dir, ytdlp_pin


def test_both_yt_dlp_pins_have_the_exact_values():
    assert YTDLP_PINS["win32"] == YtdlpPin(
        "2026.08.19", "yt-dlp.exe", "66674953fe251b89f4d08c5f0e35e0728679bd67ab3d7d05c0562af101dd3e7a", 17840399,
        "yt-dlp.exe")
    assert YTDLP_PINS["darwin"] == YtdlpPin(
        "2026.08.19", "yt-dlp_macos", "0f192b7ec147ab6288885d6351d9ab67367640029b4377576ef46dd79cf7b202", 37146048,
        "yt-dlp")
    assert set(YTDLP_PINS) == {"win32", "darwin"}


def test_ytdlp_pin_follows_the_platform():
    assert ytdlp_pin("darwin") is YTDLP_PINS["darwin"]
    assert ytdlp_pin("win32") is YTDLP_PINS["win32"] and ytdlp_pin("linux") is YTDLP_PINS["win32"]
    with osplatform.simulate(osplatform.MACOS):
        assert ytdlp_pin() is YTDLP_PINS["darwin"]
    with osplatform.simulate(osplatform.WINDOWS):
        assert ytdlp_pin() is YTDLP_PINS["win32"]
    assert ytdlp_pin() is YTDLP_PINS["darwin" if sys.platform == "darwin" else "win32"]


def test_bundled_dir_from_source_is_none(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert bundled_dir() is None


def test_bundled_dir_on_windows_is_the_exe_folder(as_windows, monkeypatch, tmp_path):
    exe = tmp_path / "Tracklister" / "Tracklister.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert bundled_dir() == exe.resolve().parent


def test_bundled_dir_on_macos_is_contents_resources(as_macos, monkeypatch, tmp_path):
    exe = tmp_path / "Tracklister.app" / "Contents" / "MacOS" / "Tracklister"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    got = bundled_dir()
    assert got == (tmp_path / "Tracklister.app" / "Contents").resolve() / "Resources"
    assert got.parts[-3:] == ("Tracklister.app", "Contents", "Resources")
