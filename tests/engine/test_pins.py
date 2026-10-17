"""Pin tables per platform (no network) and engine resolution from a verified zip (Windows) or tar.gz (macOS).

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import dataclasses
import io
import os
import re
import stat
import sys
import tarfile
import zipfile

import pytest

from tracklister.core import osplatform
from tracklister.core.paths import app_paths
from tracklister.engine import spec as spec_mod
from tracklister.engine.spec import (
    DEFAULT_ENGINE_ID, ENGINE_PINS, PLATFORM_ENGINE_PINS, SOURCE_ARCHIVES, EngineDialect, EngineMissing, EnginePin,
    archive_kind, asset_name, engine_pins, fake_engine_spec, resolve_engine, sha256_file, source_archives,
)

WIN32 = engine_pins("win32")
DARWIN = engine_pins("darwin")
SLDL_ON_MAC_ES = "El motor sldl 2.6.0 no está disponible en macOS. Elige Sockseek en Ajustes > Motor."


def test_pins_well_formed():
    """The Windows table is exactly the one of 1.0.1."""
    assert DEFAULT_ENGINE_ID == "sockseek-3.0.5"
    assert set(WIN32) == {"sockseek-3.0.5", "sldl-2.6.0"} == set(SOURCE_ARCHIVES)
    for eid, pin in WIN32.items():
        assert pin.engine_id == eid
        assert re.fullmatch(r"[0-9a-f]{64}", pin.asset_sha256)
        assert pin.asset_url.startswith(f"https://github.com/fiso64/sockseek/releases/download/v{pin.version}/")
        assert pin.asset_url.endswith(".zip") and "win" in asset_name(pin) and archive_kind(pin) == "zip"
        assert pin.source_url == f"https://github.com/fiso64/sockseek/tree/v{pin.version}"
        assert pin.asset_size is None
        url, sha = SOURCE_ARCHIVES[eid]
        assert url.endswith(f"/v{pin.version}.zip") and re.fullmatch(r"[0-9a-f]{64}", sha)
    assert WIN32["sockseek-3.0.5"] == EnginePin(
        "sockseek-3.0.5", EngineDialect.SOCKSEEK3, "3.0.5",
        "https://github.com/fiso64/sockseek/releases/download/v3.0.5/sockseek_3.0.5_win-x64.zip",
        "1b5c1189dcfc24cc9fea22dc67a58b7a5f0a127d0367355cf2a8718100044802", "sockseek.exe", "AGPL-3.0-only",
        "https://github.com/fiso64/sockseek/tree/v3.0.5")
    assert WIN32["sldl-2.6.0"] == EnginePin(
        "sldl-2.6.0", EngineDialect.SLDL2, "2.6.0",
        "https://github.com/fiso64/sockseek/releases/download/v2.6.0/sldl_win-x86_self-contained.zip",
        "6e39232c8c22f9b4e5f6a635dae85fdc405e50bcc56392351001d8964cf29a63", "sldl.exe", "GPL-3.0-only",
        "https://github.com/fiso64/sockseek/tree/v2.6.0")
    assert list(WIN32) == ["sockseek-3.0.5", "sldl-2.6.0"]          # the order of the Ajustes selector


def test_pins_darwin_table_holds_only_sockseek():
    assert list(DARWIN) == ["sockseek-3.0.5"]
    assert DARWIN["sockseek-3.0.5"] == EnginePin(
        "sockseek-3.0.5", EngineDialect.SOCKSEEK3, "3.0.5",
        "https://github.com/fiso64/sockseek/releases/download/v3.0.5/sockseek_3.0.5_osx-arm64.tar.gz",
        "6a18078b78f98a9797d723925574996a7bf87f6cc3012aee9efa1e9977a0edd0", "sockseek", "AGPL-3.0-only",
        "https://github.com/fiso64/sockseek/tree/v3.0.5", 46570010)
    assert archive_kind(DARWIN["sockseek-3.0.5"]) == "tar.gz"
    assert asset_name(DARWIN["sockseek-3.0.5"]) == "sockseek_3.0.5_osx-arm64.tar.gz"
    assert source_archives("darwin") == {"sockseek-3.0.5": SOURCE_ARCHIVES["sockseek-3.0.5"]}
    assert source_archives("win32") == SOURCE_ARCHIVES and source_archives("linux") == SOURCE_ARCHIVES


def test_engine_pins_is_the_live_table_of_the_platform():
    assert ENGINE_PINS is engine_pins()                       # the import-time alias of the real platform
    assert ENGINE_PINS is PLATFORM_ENGINE_PINS["darwin" if sys.platform == "darwin" else "win32"]
    assert engine_pins("win32") is PLATFORM_ENGINE_PINS["win32"] and engine_pins("linux") is engine_pins("win32")
    with osplatform.simulate(osplatform.MACOS):
        assert engine_pins() is DARWIN
    with osplatform.simulate(osplatform.WINDOWS):
        assert engine_pins() is WIN32
    with pytest.raises(ValueError):
        archive_kind(dataclasses.replace(WIN32["sldl-2.6.0"], asset_url="https://x/engine.rar"))


def test_pins_fake_spec_points_to_the_fake_script():
    s = fake_engine_spec()
    assert s.is_fake() and s.engine_id == "fake:sockseek-3.0.5"
    assert s.argv_prefix[1].endswith("fake_engine.py")
    assert fake_engine_spec(EngineDialect.SLDL2).engine_id == "fake:sldl-2.6.0"


# ---- Windows: the verified zip (pinned to the Windows table, so it also runs on the macOS runner) -----------

def _fake_pin(monkeypatch, tmp_path, payload: bytes):
    """Point the sockseek pin at a tiny local zip so resolution is tested without the real 50 MB."""
    z = tmp_path / "bundle" / "sockseek_3.0.5_win-x64.zip"
    z.parent.mkdir(parents=True)
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("sockseek.exe", payload)
        zf.writestr("LICENSE", "AGPL")
    pin = WIN32["sockseek-3.0.5"]
    fake = spec_mod.EnginePin(**{**pin.__dict__, "asset_sha256": sha256_file(z)})
    monkeypatch.setitem(WIN32, "sockseek-3.0.5", fake)
    monkeypatch.setattr(spec_mod, "dev_bin_dir", lambda: tmp_path / "nowhere")
    return z


def test_pins_resolve_unpacks_verified_zip(as_windows, monkeypatch, tmp_path):
    z = _fake_pin(monkeypatch, tmp_path, b"MZ fake exe")
    paths = app_paths()
    s = resolve_engine("sockseek-3.0.5", paths, bundled_dir=z.parent)
    assert s.argv_prefix[0].endswith("sockseek.exe") and not s.is_fake()
    assert (paths.tools_dir / "engines" / "sockseek-3.0.5" / "LICENSE").exists()
    # second call reuses the unpacked copy (marker matches) even without the zip
    z.unlink()
    assert resolve_engine("sockseek-3.0.5", paths).argv_prefix == s.argv_prefix


def test_pins_resolve_rejects_tampered_zip(as_windows, monkeypatch, tmp_path):
    z = _fake_pin(monkeypatch, tmp_path, b"MZ fake exe")
    with zipfile.ZipFile(z, "a") as zf:
        zf.writestr("extra.txt", "tampered")
    with pytest.raises(EngineMissing) as e:
        resolve_engine("sockseek-3.0.5", app_paths(), bundled_dir=z.parent)
    assert "SHA-256" in e.value.msg_es


def test_pins_resolve_missing_and_unknown(as_windows, monkeypatch, tmp_path):
    monkeypatch.setattr(spec_mod, "dev_bin_dir", lambda: tmp_path / "nowhere")
    with pytest.raises(EngineMissing) as e:
        resolve_engine("sldl-2.6.0", app_paths())
    assert e.value.msg_es.startswith("No se encuentra el motor sldl-2.6.0 (sldl_win-x86_self-contained.zip).")
    with pytest.raises(EngineMissing) as e:
        resolve_engine("otro-1.0", app_paths())
    assert e.value.msg_es == "Motor desconocido: otro-1.0. Elige otro en Ajustes > Motor."


def test_pins_zip_slip_refused(as_windows, monkeypatch, tmp_path):
    z = tmp_path / "bundle" / "sockseek_3.0.5_win-x64.zip"
    z.parent.mkdir(parents=True)
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../evil.exe", b"x")
        zf.writestr("sockseek.exe", b"x")
    pin = WIN32["sockseek-3.0.5"]
    monkeypatch.setitem(WIN32, "sockseek-3.0.5", spec_mod.EnginePin(**{**pin.__dict__, "asset_sha256": sha256_file(z)}))
    monkeypatch.setattr(spec_mod, "dev_bin_dir", lambda: tmp_path / "nowhere")
    with pytest.raises(EngineMissing):
        resolve_engine("sockseek-3.0.5", app_paths(), bundled_dir=z.parent)
    assert not (tmp_path / "evil.exe").exists()


# ---- macOS: the verified tar.gz, extracted with the 'data' filter and made executable ---------------------

def _add(tf: tarfile.TarFile, name: str, data: bytes = b"", mode: int = 0o644, kind=tarfile.REGTYPE,
         link: str = "") -> None:
    info = tarfile.TarInfo(name)
    info.type, info.mode, info.linkname = kind, mode, link
    info.size = len(data) if kind == tarfile.REGTYPE else 0
    tf.addfile(info, io.BytesIO(data) if kind == tarfile.REGTYPE else None)


def _fake_tar(tmp_path, *, exe_mode=0o755, extra=()):
    """Resources/engines/sockseek_3.0.5_osx-arm64.tar.gz as upstream packs it: LICENSE and sockseek at the top."""
    t = tmp_path / "Resources" / "engines" / "sockseek_3.0.5_osx-arm64.tar.gz"
    t.parent.mkdir(parents=True)
    with tarfile.open(t, "w:gz") as tf:
        _add(tf, "LICENSE", b"AGPL", 0o644)
        for args in extra:
            _add(tf, *args)
        _add(tf, "sockseek", b"\xcf\xfa\xed\xfe fake engine", exe_mode)
    return t


def _darwin_pin(monkeypatch, tmp_path, tar, *, size_delta=0):
    pin = DARWIN["sockseek-3.0.5"]
    fake = dataclasses.replace(pin, asset_sha256=sha256_file(tar), asset_size=tar.stat().st_size + size_delta)
    monkeypatch.setitem(DARWIN, "sockseek-3.0.5", fake)
    monkeypatch.setattr(spec_mod, "dev_bin_dir", lambda: tmp_path / "nowhere")
    return fake


@pytest.fixture
def chmods(monkeypatch):
    """Every os.chmod call (tarfile's own and the app's), passed on to the real one."""
    calls = []
    real = os.chmod

    def spy(path, mode, *a, **kw):
        calls.append((os.fspath(path), mode))
        return real(path, mode, *a, **kw)
    monkeypatch.setattr(os, "chmod", spy)
    return calls


@pytest.mark.parametrize("exe_mode", [0o755, 0o644], ids=["as-upstream", "mode-lost"])
def test_mac_resolve_extracts_the_tar_and_makes_the_engine_executable(as_macos, monkeypatch, tmp_path, chmods,
                                                                     exe_mode):
    tar = _fake_tar(tmp_path, exe_mode=exe_mode)
    pin = _darwin_pin(monkeypatch, tmp_path, tar)
    paths = app_paths()
    s = resolve_engine("sockseek-3.0.5", paths, bundled_dir=tar.parent.parent)
    exe = paths.tools_dir / "engines" / "sockseek-3.0.5" / "sockseek"
    assert s.argv_prefix == (str(exe),) and s.dialect == EngineDialect.SOCKSEEK3 and not s.is_fake()
    assert exe.read_bytes() == b"\xcf\xfa\xed\xfe fake engine"
    assert (exe.parent / "LICENSE").read_bytes() == b"AGPL"
    assert (exe.parent / ".tracklister-sha256").read_text(encoding="ascii") == pin.asset_sha256
    # the app's own chmod comes last, on the copy it is about to move into place
    on_exe = [mode for p, mode in chmods if p.endswith(os.path.join("sockseek-3.0.5.tmp", "sockseek"))]
    assert on_exe and on_exe[-1] == 0o755
    if os.name == "posix":
        assert stat.S_IMODE(exe.stat().st_mode) == 0o755
    # a second call reuses the copy (the marker matches), even without the archive
    tar.unlink()
    chmods.clear()
    assert resolve_engine("sockseek-3.0.5", paths).argv_prefix == s.argv_prefix
    assert chmods == []


def test_mac_resolve_rejects_a_tampered_tar(as_macos, monkeypatch, tmp_path):
    tar = _fake_tar(tmp_path)
    _darwin_pin(monkeypatch, tmp_path, tar)
    with open(tar, "ab") as f:
        f.write(b"tampered")
    with pytest.raises(EngineMissing) as e:
        resolve_engine("sockseek-3.0.5", app_paths(), bundled_dir=tar.parent.parent)
    assert "no coincide con su huella SHA-256" in e.value.msg_es
    assert not (app_paths().tools_dir / "engines" / "sockseek-3.0.5").exists()


def test_mac_resolve_rejects_a_wrong_size_with_the_sha_message(as_macos, monkeypatch, tmp_path):
    tar = _fake_tar(tmp_path)
    _darwin_pin(monkeypatch, tmp_path, tar, size_delta=1)
    with pytest.raises(EngineMissing) as e:
        resolve_engine("sockseek-3.0.5", app_paths(), bundled_dir=tar.parent.parent)
    assert e.value.msg_es.startswith("El archivo del motor sockseek_3.0.5_osx-arm64.tar.gz no coincide con su "
                                     "huella SHA-256")
    assert not (app_paths().tools_dir / "engines" / "sockseek-3.0.5").exists()


@pytest.mark.parametrize("bad", [
    ("../evil", b"x", 0o644),
    ("enlace", b"", 0o777, tarfile.SYMTYPE, "../../../../evil-link-target"),
    ("enlace-abs", b"", 0o777, tarfile.SYMTYPE, "/etc/hosts"),
], ids=["dot-dot", "symlink-outside", "symlink-absolute"])
def test_mac_resolve_refuses_members_outside_the_folder(as_macos, monkeypatch, tmp_path, bad):
    tar = _fake_tar(tmp_path, extra=[bad])
    _darwin_pin(monkeypatch, tmp_path, tar)
    paths = app_paths()
    before = set(tmp_path.rglob("*"))
    with pytest.raises(EngineMissing) as e:
        resolve_engine("sockseek-3.0.5", paths, bundled_dir=tar.parent.parent)
    assert e.value.msg_es.startswith("El archivo del motor contiene una ruta no válida")
    # nothing was written outside the extraction folder, and no engine copy is in place
    engines = paths.tools_dir / "engines"
    work = engines / "sockseek-3.0.5.tmp"
    new = set(tmp_path.rglob("*")) - before
    assert all(p == work or work in p.parents or p in (paths.data_dir, paths.tools_dir, engines) for p in new), \
        sorted(map(str, new))
    assert not (engines / "sockseek-3.0.5").exists() and not list(tmp_path.rglob("evil*"))
    assert not os.path.lexists(work / bad[0])                # the bad member itself was never written


def test_mac_resolve_says_sldl_is_not_on_macos_and_keeps_the_unknown_message(as_macos):
    with pytest.raises(EngineMissing) as e:
        resolve_engine("sldl-2.6.0", app_paths())
    assert e.value.msg_es == SLDL_ON_MAC_ES
    with pytest.raises(EngineMissing) as e:
        resolve_engine("otro-1.0", app_paths())
    assert e.value.msg_es == "Motor desconocido: otro-1.0. Elige otro en Ajustes > Motor."


def test_mac_resolve_without_the_archive(as_macos, monkeypatch, tmp_path):
    monkeypatch.setattr(spec_mod, "dev_bin_dir", lambda: tmp_path / "nowhere")
    with pytest.raises(EngineMissing) as e:
        resolve_engine("sockseek-3.0.5", app_paths(), bundled_dir=tmp_path / "Resources")
    assert e.value.msg_es.startswith("No se encuentra el motor sockseek-3.0.5 (sockseek_3.0.5_osx-arm64.tar.gz).")
