"""Audit round 2: a damaged settings.json never stops the window (N6); the yt-dlp copy is atomic (N4).
1.1: the engine id per platform, and the checked yt-dlp copy of the Mac bundle.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import platform
import shutil
import stat
from pathlib import Path

import pytest

from tests.gui.fakes import FakeServices
from tracklister.config import DEFAULT_LISTEN_PORT
from tracklister.core import bundled as bundled_mod
from tracklister.core.paths import app_paths
from tracklister.engine.spec import fake_engine_spec
from tracklister.gui import services as services_mod
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


def test_r2_n4_an_interrupted_ytdlp_copy_leaves_no_broken_exe(as_windows, tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    (bundle / "tools").mkdir(parents=True)
    bundled = bundle / "tools" / "yt-dlp.exe"
    bundled.write_bytes(b"MZ" + bytes(range(256)) * 400)
    s = Services(bundle=bundle)
    target = s.ytdlp_exe()
    assert target == s.paths.tools_dir / "yt-dlp.exe"
    real_copy = shutil.copy2

    def dies_half_way(src, dst, *a, **kw):
        Path(dst).write_bytes(Path(src).read_bytes()[:1000])
        raise OSError(28, "No queda espacio en el disco")
    monkeypatch.setattr(shutil, "copy2", dies_half_way)
    assert s.ensure_ytdlp() is None
    assert not target.exists() and not target.with_name(target.name + ".part").exists()
    monkeypatch.setattr(shutil, "copy2", real_copy)
    # Windows as in 1.0: the bundled exe was verified at build time, so its copy is not hashed again here
    assert s.ensure_ytdlp() == target and target.read_bytes() == bundled.read_bytes()
    assert not target.with_name(target.name + ".part").exists()


def test_bundled_dir_is_still_reachable_through_services():
    assert services_mod.bundled_dir is bundled_mod.bundled_dir


# ---- 1.1, macOS: the copy of Contents/Resources/tools/yt-dlp_macos ----------------------------------------

def _mac_bundle(tmp_path, monkeypatch, data: bytes, where: str = "tools") -> tuple[Path, Path]:
    """Tracklister.app/Contents/Resources with yt-dlp_macos holding `data`, and the darwin pin pointed at it."""
    res = tmp_path / "Tracklister.app" / "Contents" / "Resources"
    f = res / where / "yt-dlp_macos" if where else res / "yt-dlp_macos"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    pin = dataclasses.replace(bundled_mod.YTDLP_PINS["darwin"], sha256=hashlib.sha256(data).hexdigest(),
                              size=len(data))
    monkeypatch.setitem(bundled_mod.YTDLP_PINS, "darwin", pin)
    return res, f


@pytest.fixture
def chmods(monkeypatch):
    """Every os.chmod call (shutil.copy2's own and the app's), passed on to the real one."""
    calls = []
    real = os.chmod

    def spy(path, mode, *a, **kw):
        calls.append((os.fspath(path), mode))
        return real(path, mode, *a, **kw)
    monkeypatch.setattr(os, "chmod", spy)
    return calls


def test_mac_ytdlp_copy_is_checked_and_made_executable(as_macos, tmp_path, monkeypatch, chmods):
    data = b"\xca\xfe\xba\xbe" + bytes(range(256)) * 64
    res, bundled = _mac_bundle(tmp_path, monkeypatch, data)
    s = Services(bundle=res)
    target = s.paths.tools_dir / "yt-dlp"
    assert s.ytdlp_exe() == target
    assert s.ensure_ytdlp() == target and target.read_bytes() == data
    assert (str(target.with_name("yt-dlp.part")), 0o755) in chmods
    assert not target.with_name("yt-dlp.part").exists()
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o755
    assert bundled.read_bytes() == data                          # the bundle itself is never changed


@pytest.mark.parametrize("bad", [b"evil bytes", b"good bytes, but longer"], ids=["same-size", "other-size"])
def test_mac_a_tampered_ytdlp_is_never_copied(as_macos, tmp_path, monkeypatch, caplog, bad):
    res, bundled = _mac_bundle(tmp_path, monkeypatch, b"good bytes")
    bundled.write_bytes(bad)
    s = Services(bundle=res)
    target = s.paths.tools_dir / "yt-dlp"
    with caplog.at_level(logging.ERROR, logger="tracklister.gui"):
        assert s.ensure_ytdlp() is None
    assert not target.exists() and not target.with_name("yt-dlp.part").exists()
    assert "yt-dlp_macos does not match its pin" in caplog.text
    assert str(tmp_path) not in caplog.text                       # no user path in the log


def test_mac_the_next_candidate_is_tried_after_a_bad_one(as_macos, tmp_path, monkeypatch):
    good = b"the pinned yt-dlp"
    res, _ = _mac_bundle(tmp_path, monkeypatch, good)               # Resources/tools/yt-dlp_macos: good
    (res / "yt-dlp_macos").write_bytes(b"a stale yt-dlp")          # Resources/yt-dlp_macos, tried first: bad
    s = Services(bundle=res)
    assert s.ensure_ytdlp() == s.paths.tools_dir / "yt-dlp"
    assert (s.paths.tools_dir / "yt-dlp").read_bytes() == good


def test_mac_an_existing_copy_is_kept_unread(as_macos, tmp_path, monkeypatch):
    """'Actualizar yt-dlp' (yt-dlp -U) changes the copy: it is used as it is, never hashed or replaced."""
    res, _ = _mac_bundle(tmp_path, monkeypatch, b"bundled")
    s = Services(bundle=res)
    target = s.paths.tools_dir / "yt-dlp"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"updated by yt-dlp -U")

    def must_not_run(*a, **k):
        raise AssertionError("an existing copy must not be read or replaced")
    monkeypatch.setattr(services_mod, "sha256_file", must_not_run)
    monkeypatch.setattr(shutil, "copy2", must_not_run)
    assert s.ensure_ytdlp() == target and target.read_bytes() == b"updated by yt-dlp -U"


# ---- 1.1: the engine each platform runs ----------------------------------------------------------------

@pytest.fixture
def resolved(monkeypatch):
    """The engine ids Services.make_runner asks engine.spec.resolve_engine for."""
    seen: list[str] = []

    def fake_resolve(engine_id, paths, bundled_dir=None):
        seen.append(engine_id)
        return fake_engine_spec()
    monkeypatch.setattr(services_mod, "resolve_engine", fake_resolve)
    return seen


def test_mac_sldl_from_a_windows_settings_file_runs_sockseek(as_macos, resolved, caplog):
    s = Services()
    s.settings.engine_id = "sldl-2.6.0"
    with caplog.at_level(logging.WARNING, logger="tracklister.gui"):
        s.make_runner()
    assert resolved == ["sockseek-3.0.5"] and s.engine_id() == "sockseek-3.0.5"
    assert "sldl-2.6.0 is not shipped on macOS" in caplog.text
    assert s.settings.engine_id == "sldl-2.6.0"                    # the saved setting is not rewritten
    s.settings.engine_id = "otro-1.0"
    s.make_runner()
    assert resolved[-1] == "otro-1.0"                              # unknown: «Motor desconocido», as before


def test_windows_runs_the_saved_engine_as_before(as_windows, resolved):
    s = Services()
    for eid in ("sldl-2.6.0", "sockseek-3.0.5", "otro-1.0"):
        s.settings.engine_id = eid
        s.make_runner()
        assert resolved[-1] == eid and s.engine_id() == eid


def test_mac_diagnostic_report_names_the_macos_version(as_macos, resolved, monkeypatch):
    import tracklister.diagnostics.run as run_mod
    from tracklister.engine.credentials import Credentials
    monkeypatch.setattr(platform, "mac_ver", lambda *a, **k: ("15.6", ("", "", ""), "arm64"))
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(run_mod, "run_diagnostic", lambda *a, **k: [])
    report, saved = Services().run_diagnostic([], Credentials("usuario-prueba", "clave-prueba"), download=False,
                                              max_rows=5)
    assert "  |  macOS 15.6 (arm64)\n" in report and saved is not None and saved.is_file()
