"""packaging/build.py, macOS path (1.1): the .app layout, the ad-hoc signature, the checks and the ditto zip.

SPDX-License-Identifier: GPL-3.0-or-later

These run on any OS: the .app is a fake tree in tmp, codesign/xattr/ditto are a fake runner, and every call
passes platform= explicitly. The real build, signature and zip are proved by the macOS job of the release
workflow (build.py --zip, then packaging/smoke_test_macos.py).
"""
from __future__ import annotations

import dataclasses
import hashlib
import os
import plistlib
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.release.helpers import REPO, load
from tracklister import __version__
from tracklister.core.bundled import ytdlp_pin
from tracklister.engine import spec

build = load("build")
ASSETS = REPO / "src" / "tracklister" / "assets"
TAR = "sockseek_3.0.5_osx-arm64.tar.gz"
TAR_DATA = b"\x1f\x8b fake engine archive"
YTDLP_DATA = b"\xca\xfe\xba\xbe fake universal2 yt-dlp"


@pytest.fixture
def fake_inputs(tmp_path, monkeypatch):
    """The downloaded macOS engine and yt-dlp (fake bytes, with the pins pointed at them)."""
    bins = tmp_path / "bin"
    bins.mkdir()
    (bins / TAR).write_bytes(TAR_DATA)
    (bins / "yt-dlp_macos").write_bytes(YTDLP_DATA)
    monkeypatch.setattr(build, "dev_bin_dir", lambda: bins)
    monkeypatch.setattr(build.fetch_ytdlp, "BIN_DIR", bins)
    pin = spec.engine_pins("darwin")["sockseek-3.0.5"]
    monkeypatch.setitem(spec.engine_pins("darwin"), "sockseek-3.0.5",
                        dataclasses.replace(pin, asset_sha256=hashlib.sha256(TAR_DATA).hexdigest(),
                                            asset_size=len(TAR_DATA)))
    mac = dataclasses.replace(ytdlp_pin("darwin"), sha256=hashlib.sha256(YTDLP_DATA).hexdigest(), size=len(YTDLP_DATA))
    monkeypatch.setattr(build, "ytdlp_pin", lambda platform=None: mac if platform == "darwin" else ytdlp_pin(platform))
    return bins


def _info_plist(**changes) -> dict:
    v = build.mac_version()
    values = build.spec_values()
    info = {**values["INFO_PLIST"], "CFBundleIdentifier": values["BUNDLE_ID"], "CFBundleExecutable": "Tracklister",
            "CFBundlePackageType": "APPL", "CFBundleShortVersionString": v, "CFBundleVersion": v,
            "CFBundleIconFile": "tracklister.icns", "CFBundleInfoDictionaryVersion": "6.0"}
    info.update(changes)
    return info


def fake_app(root: Path) -> Path:
    """What PyInstaller's BUNDLE leaves (only the parts build.py relies on)."""
    app = root / "Tracklister.app"
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "MacOS" / "Tracklister").write_bytes(b"\xcf\xfa\xed\xfe\x0c\x00\x00\x01")
    (contents / "Info.plist").write_bytes(plistlib.dumps(_info_plist()))
    assets = contents / "Resources" / "tracklister" / "assets"
    (assets / "fonts").mkdir(parents=True)
    shutil.copy2(ASSETS / "tokens.json", assets / "tokens.json")
    for name in build.FONTS:
        shutil.copy2(ASSETS / "fonts" / name, assets / "fonts" / name)
    (contents / "Frameworks").mkdir()
    return app


def test_names_and_places_per_platform():
    assert build.zip_name("win32") == f"Tracklister-{__version__}-win64.zip"
    assert build.zip_name("darwin") == f"Tracklister-{__version__}-macos-arm64.zip"
    assert build.zip_name("linux") == build.zip_name("win32")              # anything but darwin: Windows policy
    assert build.ZIP_NAME == build.zip_name(sys.platform)
    app = Path("dist") / "Tracklister.app"
    assert build.app_dir_name("darwin") == "Tracklister.app" and build.app_dir_name("win32") == "Tracklister"
    assert build.executable(app, "darwin") == app / "Contents" / "MacOS" / "Tracklister"
    assert build.data_root(app, "darwin") == app / "Contents" / "Resources"
    assert build.data_root(Path("dist/Tracklister"), "win32") == Path("dist/Tracklister")
    assert build.executable(Path("dist/Tracklister"), "win32") == Path("dist/Tracklister/Tracklister.exe")
    assert build.mac_version("1.1.0.dev1") == "1.1.0" and build.mac_version("1.2") == "1.2.0"


def test_assemble_puts_the_mac_files_in_contents_resources(tmp_path, fake_inputs):
    app = fake_app(tmp_path)
    build.assemble(app, platform="darwin")
    res = app / "Contents" / "Resources"
    rel = sorted(p.relative_to(res).as_posix() for p in res.rglob("*") if p.is_file()
                 and "tracklister" not in p.relative_to(res).parts and "licenses" not in p.relative_to(res).parts)
    assert rel == sorted(["LICENSE.txt", "NOTICES.txt", f"engines/{TAR}", "engines/sockseek-3.0.5/LICENSE",
                          "engines/sockseek-3.0.5/SOURCE.md", "tools/yt-dlp/LICENSE", "tools/yt-dlp/SOURCE.md",
                          "tools/yt-dlp/THIRD_PARTY_LICENSES.txt", "tools/yt-dlp_macos"])
    assert (res / "engines" / TAR).read_bytes() == TAR_DATA and (res / "tools" / "yt-dlp_macos").read_bytes() == YTDLP_DATA
    lic = {d.name for d in (res / "licenses").iterdir()}
    assert {f"{n}-{v}" for n, v in build.runtime_pins(platform="darwin")} <= lic
    assert not any(d.startswith("pywin32-ctypes") for d in lic)            # a Windows-only pin
    assert any(d.startswith("python-") for d in lic) and any(d.startswith("openssl-") for d in lic)
    assert any(d.startswith("pyinstaller-") for d in lic)
    # nothing next to the executable or at the top of the bundle
    assert sorted(p.name for p in (app / "Contents" / "MacOS").iterdir()) == ["Tracklister"]
    assert sorted(p.name for p in app.iterdir()) == ["Contents"]
    with pytest.raises(build.BuildError, match="No existe"):
        build.assemble(tmp_path / "otra" / "Tracklister.app", platform="darwin")


def test_check_bundle_accepts_the_assembled_app_and_catches_what_is_wrong(tmp_path, fake_inputs):
    app = fake_app(tmp_path)
    build.assemble(app, platform="darwin")
    assert build.check_bundle(app, identity_scan=False, platform="darwin") == []
    res = app / "Contents" / "Resources"
    (res / "engines" / TAR).write_bytes(b"tampered")
    (res / "tools" / "yt-dlp_macos").write_bytes(b"tampered")
    (res / "NOTICES.txt").unlink()
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(_info_plist(
        CFBundleIdentifier="otro.id", LSMinimumSystemVersion="10.13", CFBundleIconFile="")))
    (res / "tracklister" / "assets" / "settings.json").write_text("{}", encoding="utf-8")
    problems = [p.replace("\\", "/") for p in build.check_bundle(app, identity_scan=False, platform="darwin")]
    for needle in (f"SHA-256 del motor no coincide: {TAR}", "SHA-256 de yt-dlp_macos no coincide",
                   "falta en el paquete: Contents/Resources/NOTICES.txt",
                   "Info.plist: CFBundleIdentifier es 'otro.id', se esperaba 'io.github.blessel-dev.tracklister'",
                   "Info.plist: LSMinimumSystemVersion es '10.13', se esperaba '14.0'",
                   "Info.plist: falta CFBundleIconFile (el icono de la app)",
                   "archivo de usuario o de registro en el paquete: Contents/Resources/tracklister/assets/settings.json"):
        assert needle in problems, (needle, problems)


def test_check_bundle_needs_the_executable_and_the_info_plist(tmp_path):
    problems = [p.replace("\\", "/") for p in build.check_bundle(tmp_path / "Tracklister.app", identity_scan=False,
                                                                   platform="darwin")]
    assert "falta en el paquete: Contents/MacOS/Tracklister" in problems
    assert "falta en el paquete: Contents/Info.plist" in problems
    assert "falta en el paquete: Contents/Resources/tracklister/assets/tokens.json" in problems
    assert f"falta en el paquete: Contents/Resources/engines/{TAR}" in problems
    assert not [p for p in problems if "sldl" in p or "yt-dlp.exe" in p]   # the macOS pins only


def test_info_plist_check_follows_the_spec():
    assert build.info_plist_problems(_info_plist()) == []
    assert build.info_plist_problems(_info_plist(CFBundleShortVersionString="1.1.0.dev1")) == [
        f"Info.plist: CFBundleShortVersionString es '1.1.0.dev1', se esperaba '{build.mac_version()}'"]
    assert any("NSHighResolutionCapable" in p for p in build.info_plist_problems(_info_plist(NSHighResolutionCapable=False)))
    assert build.info_plist_problems(_info_plist(CFBundleDisplayName="Tracklister by Blessel"))[-1] == (
        "el nombre del producto no puede llevar 'Blessel'")


def _can_symlink(tmp_path: Path) -> bool:
    try:
        os.symlink(tmp_path, tmp_path / "probe", target_is_directory=True)
    except (OSError, NotImplementedError):
        return False
    (tmp_path / "probe").unlink()
    return True


def test_a_link_out_of_the_bundle_or_a_broken_one_is_refused(tmp_path):
    if not _can_symlink(tmp_path):
        pytest.skip("this Windows account cannot create symlinks")
    app = tmp_path / "Tracklister.app"
    (app / "Contents" / "Resources" / "x").mkdir(parents=True)
    (app / "Contents" / "Frameworks").mkdir()
    os.symlink("../Resources/x", app / "Contents" / "Frameworks" / "x", target_is_directory=True)  # like PyInstaller's
    os.symlink(tmp_path, app / "Contents" / "fuera", target_is_directory=True)
    os.symlink("no-existe", app / "Contents" / "roto")
    problems = [p.replace("\\", "/") for p in build.symlink_problems(app)]
    assert problems == ["enlace fuera del paquete: Contents/fuera", "enlace roto: Contents/roto"]


class FakeRun:
    """Stands in for subprocess.run: records the argv, answers like codesign; ditto writes its zip."""

    def __init__(self, fail: str | None = None):
        self.calls: list[list[str]] = []
        self.fail = fail

    def __call__(self, cmd, **kwargs):
        assert kwargs == {"capture_output": True, "text": True}
        self.calls.append(list(cmd))
        if self.fail and self.fail in cmd:
            return SimpleNamespace(returncode=1, stdout="", stderr="Tracklister.app: a sealed resource is missing or invalid\n")
        if cmd[0] == build.DITTO:
            Path(cmd[-1]).write_bytes(b"PK fake ditto zip")
        err = "Tracklister.app: valid on disk\nTracklister.app: satisfies its Designated Requirement\n"
        return SimpleNamespace(returncode=0, stdout="", stderr=err if "--verify" in cmd else "")


def test_sign_and_verify_signs_ad_hoc_then_verifies_strictly(tmp_path):
    app = tmp_path / "Tracklister.app"
    run = FakeRun()
    assert build.sign_and_verify(app, run=run) == ["Tracklister.app: valid on disk",
                                                   "Tracklister.app: satisfies its Designated Requirement"]
    assert run.calls == [["/usr/bin/xattr", "-cr", str(app)],
                         ["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(app)],
                         ["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)]]
    flat = " ".join(" ".join(c) for c in run.calls)
    assert "--options" not in flat and "runtime" not in flat and "--entitlements" not in flat


def test_a_failed_verification_stops_the_build_with_codesign_s_words(tmp_path):
    with pytest.raises(build.BuildError, match="codesign --verify falló .código 1.:\nTracklister.app: a sealed resource"):
        build.sign_and_verify(tmp_path / "Tracklister.app", run=FakeRun(fail="--verify"))


def test_the_mac_zip_is_made_by_ditto_and_gets_its_own_checksum(tmp_path):
    app = tmp_path / "Tracklister.app"
    app.mkdir()
    run = FakeRun()
    out = tmp_path / "release"
    files = build.make_release(app, out, platform="darwin", run=run)
    zip_path = out / f"Tracklister-{__version__}-macos-arm64.zip"
    assert run.calls == [["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app),
                          str(zip_path) + ".part"]]
    assert files == [zip_path, out / "SHA256SUMS.txt"] and zip_path.read_bytes() == b"PK fake ditto zip"
    assert (out / "SHA256SUMS.txt").read_text(encoding="ascii") == (
        f"{hashlib.sha256(b'PK fake ditto zip').hexdigest()}  {zip_path.name}\n")
    assert sorted(p.name for p in out.iterdir()) == ["SHA256SUMS.txt", zip_path.name]   # no sources, no .part
    assert not (tmp_path / "release-notes.md").exists()                    # the publish job writes the notes
    with pytest.raises(build.BuildError, match="ditto -c falló"):
        build.write_zip(app, tmp_path / "otro.zip", platform="darwin", run=FakeRun(fail=build.DITTO))
    assert not (tmp_path / "otro.zip").exists()


def test_python_licence_is_found_on_both_layouts(tmp_path):
    lib = tmp_path / "mac" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}"
    lib.mkdir(parents=True)
    (lib / "LICENSE.txt").write_text("PSF", encoding="utf-8")
    assert build.python_licence(tmp_path / "mac") == lib / "LICENSE.txt"
    (tmp_path / "win").mkdir()
    (tmp_path / "win" / "LICENSE.txt").write_text("PSF", encoding="utf-8")
    assert build.python_licence(tmp_path / "win") == tmp_path / "win" / "LICENSE.txt"
    with pytest.raises(build.BuildError, match="licencia de Python"):
        build.python_licence(tmp_path / "ninguna")
    assert build.python_licence().is_file()                                # this Python's, whatever its layout


def test_check_inputs_needs_the_engine_sources_on_windows_only(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(build.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or SimpleNamespace(returncode=0))
    monkeypatch.setattr(build.fetch_ytdlp, "verify_local", lambda platform=None: [])
    monkeypatch.setattr(build, "source_archive", lambda engine_id: tmp_path / f"{engine_id}-src.zip")
    build.check_inputs(fetch=False, need_sources=True, platform="darwin")
    assert seen[-1][-3:] == ["--platform", "darwin", "--verify-only"]
    with pytest.raises(build.BuildError, match="sockseek-3.0.5-src.zip"):
        build.check_inputs(fetch=False, need_sources=True, platform="win32")
    assert seen[-1][-3:] == ["--platform", "win32", "--verify-only"]
    monkeypatch.setattr(build.fetch_ytdlp, "verify_local", lambda platform=None: [f"FALTA {platform}"])
    with pytest.raises(build.BuildError, match="^yt-dlp_macos falta"):
        build.check_inputs(fetch=False, need_sources=False, platform="darwin")
    with pytest.raises(build.BuildError, match="^yt-dlp.exe falta"):
        build.check_inputs(fetch=False, need_sources=False, platform="win32")
