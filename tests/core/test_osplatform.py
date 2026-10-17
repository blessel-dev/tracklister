"""The platform module (1.1): sys.platform by default, simulate() for tests, the OS line of the Diagnóstico.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import platform
import sys
from pathlib import Path

import pytest

import tracklister
from tracklister.core import osplatform


def test_the_default_is_the_real_platform():
    assert osplatform.current() == sys.platform
    assert osplatform.is_windows() is (sys.platform == "win32")
    assert osplatform.is_macos() is (sys.platform == "darwin")
    assert (osplatform.WINDOWS, osplatform.MACOS) == ("win32", "darwin")


def test_simulate_nests_and_restores():
    before = osplatform.current()
    with osplatform.simulate(osplatform.MACOS):
        assert osplatform.current() == "darwin" and osplatform.is_macos() and not osplatform.is_windows()
        with osplatform.simulate(osplatform.WINDOWS):
            assert osplatform.current() == "win32" and osplatform.is_windows() and not osplatform.is_macos()
        assert osplatform.is_macos()
    assert osplatform.current() == before


def test_simulate_restores_after_an_error_and_refuses_a_non_name():
    before = osplatform.current()
    with pytest.raises(RuntimeError):
        with osplatform.simulate(osplatform.MACOS):
            raise RuntimeError("boom")
    assert osplatform.current() == before
    with pytest.raises(ValueError):
        with osplatform.simulate(""):
            pass
    assert osplatform.current() == before


def test_another_platform_is_neither_windows_nor_macos():
    """Linux and the rest get the Windows policy: the code branches on is_macos()."""
    with osplatform.simulate("linux"):
        assert not osplatform.is_macos() and not osplatform.is_windows()
        assert osplatform.os_version().startswith("Windows ")


def test_fixtures_simulate_for_one_test(as_macos):
    assert osplatform.is_macos()


def test_as_windows_fixture(as_windows):
    assert osplatform.is_windows() and not osplatform.is_macos()


def test_os_version_on_windows_is_the_text_of_1_0(as_windows, monkeypatch):
    assert osplatform.os_version() == f"Windows {platform.release()} (build {platform.version()})"
    monkeypatch.setattr(platform, "release", lambda: "11")
    monkeypatch.setattr(platform, "version", lambda: "10.0.26100")
    assert osplatform.os_version() == "Windows 11 (build 10.0.26100)"


def test_os_version_on_macos(as_macos, monkeypatch):
    monkeypatch.setattr(platform, "mac_ver", lambda *a, **k: ("15.6", ("", "", ""), "arm64"))
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    assert osplatform.os_version() == "macOS 15.6 (arm64)"
    monkeypatch.setattr(platform, "mac_ver", lambda *a, **k: ("", ("", "", ""), ""))
    assert osplatform.os_version() == "macOS ? (arm64)"


def test_the_tests_import_the_package_of_this_worktree():
    """pytest's pythonpath = ["src", "."]: never an editable install of another checkout."""
    repo = Path(__file__).resolve().parents[2]
    assert Path(tracklister.__file__).resolve().is_relative_to(repo / "src" / "tracklister")
