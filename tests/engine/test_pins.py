"""Pin table sanity (no network) and engine resolution from a verified zip.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import re
import zipfile

import pytest

from tracklister.core.paths import app_paths
from tracklister.engine import spec as spec_mod
from tracklister.engine.spec import (
    DEFAULT_ENGINE_ID, ENGINE_PINS, SOURCE_ARCHIVES, EngineDialect, EngineMissing, asset_name,
    fake_engine_spec, resolve_engine, sha256_file,
)


def test_pins_well_formed():
    assert DEFAULT_ENGINE_ID == "sockseek-3.0.5"
    assert set(ENGINE_PINS) == {"sockseek-3.0.5", "sldl-2.6.0"} == set(SOURCE_ARCHIVES)
    for eid, pin in ENGINE_PINS.items():
        assert pin.engine_id == eid
        assert re.fullmatch(r"[0-9a-f]{64}", pin.asset_sha256)
        assert pin.asset_url.startswith(f"https://github.com/fiso64/sockseek/releases/download/v{pin.version}/")
        assert pin.asset_url.endswith(".zip") and "win" in asset_name(pin)
        assert pin.source_url == f"https://github.com/fiso64/sockseek/tree/v{pin.version}"
        url, sha = SOURCE_ARCHIVES[eid]
        assert url.endswith(f"/v{pin.version}.zip") and re.fullmatch(r"[0-9a-f]{64}", sha)
    assert ENGINE_PINS["sockseek-3.0.5"].dialect == EngineDialect.SOCKSEEK3
    assert ENGINE_PINS["sockseek-3.0.5"].exe_name == "sockseek.exe"
    assert ENGINE_PINS["sldl-2.6.0"].dialect == EngineDialect.SLDL2
    assert ENGINE_PINS["sldl-2.6.0"].exe_name == "sldl.exe"


def test_pins_fake_spec_points_to_the_fake_script():
    s = fake_engine_spec()
    assert s.is_fake() and s.engine_id == "fake:sockseek-3.0.5"
    assert s.argv_prefix[1].endswith("fake_engine.py")
    assert fake_engine_spec(EngineDialect.SLDL2).engine_id == "fake:sldl-2.6.0"


def _fake_pin(monkeypatch, tmp_path, payload: bytes):
    """Point the sockseek pin at a tiny local zip so resolution is tested without the real 50 MB."""
    z = tmp_path / "bundle" / "sockseek_3.0.5_win-x64.zip"
    z.parent.mkdir(parents=True)
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("sockseek.exe", payload)
        zf.writestr("LICENSE", "AGPL")
    pin = ENGINE_PINS["sockseek-3.0.5"]
    fake = spec_mod.EnginePin(**{**pin.__dict__, "asset_sha256": sha256_file(z)})
    monkeypatch.setitem(spec_mod.ENGINE_PINS, "sockseek-3.0.5", fake)
    monkeypatch.setattr(spec_mod, "dev_bin_dir", lambda: tmp_path / "nowhere")
    return z


def test_pins_resolve_unpacks_verified_zip(monkeypatch, tmp_path):
    z = _fake_pin(monkeypatch, tmp_path, b"MZ fake exe")
    paths = app_paths()
    s = resolve_engine("sockseek-3.0.5", paths, bundled_dir=z.parent)
    assert s.argv_prefix[0].endswith("sockseek.exe") and not s.is_fake()
    assert (paths.tools_dir / "engines" / "sockseek-3.0.5" / "LICENSE").exists()
    # second call reuses the unpacked copy (marker matches) even without the zip
    z.unlink()
    assert resolve_engine("sockseek-3.0.5", paths).argv_prefix == s.argv_prefix


def test_pins_resolve_rejects_tampered_zip(monkeypatch, tmp_path):
    z = _fake_pin(monkeypatch, tmp_path, b"MZ fake exe")
    with zipfile.ZipFile(z, "a") as zf:
        zf.writestr("extra.txt", "tampered")
    with pytest.raises(EngineMissing) as e:
        resolve_engine("sockseek-3.0.5", app_paths(), bundled_dir=z.parent)
    assert "SHA-256" in e.value.msg_es


def test_pins_resolve_missing_and_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(spec_mod, "dev_bin_dir", lambda: tmp_path / "nowhere")
    with pytest.raises(EngineMissing):
        resolve_engine("sldl-2.6.0", app_paths())
    with pytest.raises(EngineMissing):
        resolve_engine("otro-1.0", app_paths())


def test_pins_zip_slip_refused(monkeypatch, tmp_path):
    z = tmp_path / "bundle" / "sockseek_3.0.5_win-x64.zip"
    z.parent.mkdir(parents=True)
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../evil.exe", b"x")
        zf.writestr("sockseek.exe", b"x")
    pin = ENGINE_PINS["sockseek-3.0.5"]
    monkeypatch.setitem(spec_mod.ENGINE_PINS, "sockseek-3.0.5",
                        spec_mod.EnginePin(**{**pin.__dict__, "asset_sha256": sha256_file(z)}))
    monkeypatch.setattr(spec_mod, "dev_bin_dir", lambda: tmp_path / "nowhere")
    with pytest.raises(EngineMissing):
        resolve_engine("sockseek-3.0.5", app_paths(), bundled_dir=z.parent)
    assert not (tmp_path / "evil.exe").exists()
