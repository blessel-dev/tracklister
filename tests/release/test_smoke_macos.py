"""packaging/smoke_test_macos.py, the six checks of the macOS app, tested on any OS with fake files and a
fake runner. The real run is a step of the macOS job (after build.py --zip).

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import dataclasses
import hashlib
import os
import plistlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.release.helpers import load
from tracklister.core.bundled import ytdlp_pin

smoke = load("smoke_test_macos")
build = smoke.build

ARM64 = b"\xcf\xfa\xed\xfe\x0c\x00\x00\x01\x00\x00\x00\x00"
X86_64 = b"\xcf\xfa\xed\xfe\x07\x00\x00\x01\x03\x00\x00\x00"
FAT = b"\xca\xfe\xba\xbe\x00\x00\x00\x02\x01\x00\x00\x07"


def test_the_six_checks_are_the_report_s():
    assert smoke.CHECKS == ("app_starts", "ytdlp_copy", "codesign_verify", "info_plist_arm64", "engine_sha256",
                            "zip_roundtrip")
    assert smoke.DEFAULT_ZIP.name == build.zip_name("darwin") and smoke.DEFAULT_APP.name == "Tracklister.app"


@pytest.mark.parametrize("head, arch", [(ARM64, "arm64"), (X86_64, "x86_64"), (FAT, "universal"),
                                        (b"\xbe\xba\xfe\xca\x00\x00\x00\x02", "universal"), (b"MZ\x90\x00", "unknown"),
                                        (b"\xcf\xfa\xed\xfe\x12\x00\x00\x00", "cputype 0x12")])
def test_the_mach_o_header_says_thin_arm64_or_not(tmp_path, head, arch):
    exe = tmp_path / "Tracklister"
    exe.write_bytes(head)
    assert smoke.macho_arch(exe) == arch
    assert smoke.macho_arch(tmp_path / "no-existe") == "unknown"


def _app(tmp_path: Path, exe: bytes = ARM64, **plist_changes) -> Path:
    app = tmp_path / "Tracklister.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "Tracklister").write_bytes(exe)
    values = build.spec_values()
    v = build.mac_version()
    info = {**values["INFO_PLIST"], "CFBundleIdentifier": values["BUNDLE_ID"], "CFBundleExecutable": "Tracklister",
            "CFBundlePackageType": "APPL", "CFBundleShortVersionString": v, "CFBundleVersion": v,
            "CFBundleIconFile": "tracklister.icns"} | plist_changes
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(info))
    return app


def test_info_plist_and_architecture_check(tmp_path):
    ok, text = smoke.info_plist_check(_app(tmp_path / "a"))
    assert ok and text == f"io.github.blessel-dev.tracklister {build.mac_version()} arm64"
    ok, text = smoke.info_plist_check(_app(tmp_path / "b", exe=FAT))
    assert not ok and "Contents/MacOS/Tracklister es universal, no arm64 solo" in text
    ok, text = smoke.info_plist_check(_app(tmp_path / "c", LSMinimumSystemVersion="15.0"))
    assert not ok and "LSMinimumSystemVersion es '15.0', se esperaba '14.0'" in text
    (tmp_path / "d" / "Tracklister.app" / "Contents").mkdir(parents=True)
    assert smoke.info_plist_check(tmp_path / "d" / "Tracklister.app") == (False, "falta Contents/Info.plist")


def test_the_environment_has_no_python_and_a_fresh_home(tmp_path):
    base = {"PATH": "/Users/x/.venv/bin:/opt/homebrew/bin:/usr/bin", "PYTHONPATH": "src", "PYTHONHOME": "/x",
            "VIRTUAL_ENV": "/Users/x/.venv", "HOME": "/Users/x", "TMPDIR": "/var/folders/t", "USER": "x",
            "LOGNAME": "x", "LANG": "es_ES.UTF-8", "LC_ALL": "es_ES.UTF-8", "LC_CTYPE": "UTF-8", "OTRA": "1",
            "QT_QPA_PLATFORM": "cocoa"}
    env = smoke.clean_env(tmp_path, offscreen=True, base=base)
    assert env == {"HOME": "/Users/x", "TMPDIR": "/var/folders/t", "USER": "x", "LOGNAME": "x", "LANG": "es_ES.UTF-8",
                   "LC_ALL": "es_ES.UTF-8", "LC_CTYPE": "UTF-8", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                   "TRACKLISTER_HOME": str(tmp_path), "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
                   "QT_QPA_PLATFORM": "offscreen"}
    assert "QT_QPA_PLATFORM" not in smoke.clean_env(tmp_path, offscreen=False, base=base)


class FakeTools:
    """xattr, codesign and ditto as a fake runner: records argv; `marked` is the set of quarantined paths."""

    def __init__(self, verify_ok: bool = True, unzip_names: tuple[str, ...] = ("Tracklister.app",)):
        self.calls: list[list[str]] = []
        self.marked: set[str] = set()
        self.verify_ok = verify_ok
        self.unzip_names = unzip_names

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        code = 0
        if cmd[:2] == [build.XATTR, "-w"]:
            self.marked.add(cmd[-1])
        elif cmd[:2] == [build.XATTR, "-p"]:
            code = 0 if cmd[-1] in self.marked else 1
        elif cmd[0] == build.CODESIGN:
            code = 0 if self.verify_ok else 1
        elif cmd[:3] == [build.DITTO, "-x", "-k"]:
            for name in self.unzip_names:
                (Path(cmd[-1]) / name).mkdir(parents=True)
        return SimpleNamespace(returncode=code, stdout="", stderr="Tracklister.app: valid on disk\n")


def test_the_quarantine_probe_and_mark(tmp_path):
    run = FakeTools()
    f = tmp_path / "yt-dlp_macos"
    assert not smoke.has_quarantine(f, run)
    assert smoke.plant_quarantine(f, run) and smoke.has_quarantine(f, run)
    assert run.calls == [["/usr/bin/xattr", "-p", "com.apple.quarantine", str(f)],
                         ["/usr/bin/xattr", "-w", "com.apple.quarantine", "0081;00000000;Tracklister-smoke;", str(f)],
                         ["/usr/bin/xattr", "-p", "com.apple.quarantine", str(f)]]


def _home_with_copy(tmp_path: Path, monkeypatch, data: bytes) -> Path:
    home = tmp_path / "home"
    (home / "data" / "tools").mkdir(parents=True)
    copy = home / "data" / "tools" / "yt-dlp"
    copy.write_bytes(data)
    os.chmod(copy, 0o755)
    pin = dataclasses.replace(ytdlp_pin("darwin"), sha256=hashlib.sha256(b"el pin").hexdigest(), size=6)
    monkeypatch.setattr(smoke, "ytdlp_pin", lambda platform=None: pin)
    return home


@pytest.mark.skipif(os.name == "nt", reason="needs POSIX file modes")
def test_the_ytdlp_copy_needs_the_pin_mode_755_and_no_quarantine(tmp_path, monkeypatch):
    home = _home_with_copy(tmp_path, monkeypatch, b"el pin")
    run = FakeTools()
    assert smoke.ytdlp_copy_check(home, run) == (True, "sha256 del pin, modo 755, sin cuarentena")
    run.marked.add(str(home / "data" / "tools" / "yt-dlp"))
    os.chmod(home / "data" / "tools" / "yt-dlp", 0o644)
    assert smoke.ytdlp_copy_check(home, run) == (False, "modo 644, no 755; lleva com.apple.quarantine")
    (home / "data" / "tools" / "yt-dlp").write_bytes(b"otro")
    assert smoke.ytdlp_copy_check(home, run)[1].startswith("SHA-256 distinto del pin")


def test_a_missing_ytdlp_copy_says_whether_a_part_file_was_left(tmp_path, monkeypatch):
    home = _home_with_copy(tmp_path, monkeypatch, b"el pin")
    (home / "data" / "tools" / "yt-dlp").unlink()
    assert smoke.ytdlp_copy_check(home, FakeTools()) == (False, "no existe yt-dlp en data/tools")
    (home / "data" / "tools" / "yt-dlp.part").write_bytes(b"a medias")
    assert smoke.ytdlp_copy_check(home, FakeTools()) == (False, "no existe yt-dlp en data/tools (quedó un .part)")


def test_the_engine_archive_must_be_the_pinned_one(tmp_path):
    app = tmp_path / "Tracklister.app"
    assert smoke.engine_check(app) == (False, "falta Contents/Resources/engines/sockseek_3.0.5_osx-arm64.tar.gz")
    tar = app / "Contents" / "Resources" / "engines" / "sockseek_3.0.5_osx-arm64.tar.gz"
    tar.parent.mkdir(parents=True)
    tar.write_bytes(b"no es el motor")
    ok, text = smoke.engine_check(app)
    assert not ok and text.startswith("sockseek_3.0.5_osx-arm64.tar.gz sha256=")


def test_the_zip_round_trip(tmp_path):
    zip_path = tmp_path / build.zip_name("darwin")
    work = tmp_path / "work"
    work.mkdir()
    assert smoke.zip_roundtrip(zip_path, work, FakeTools()) == (False, f"no existe {zip_path.name}")
    zip_path.write_bytes(b"PK")
    run = FakeTools()
    ok, text = smoke.zip_roundtrip(zip_path, work, run)
    assert ok and text.startswith("descomprimida y firmada: ")
    assert run.calls[0] == ["/usr/bin/ditto", "-x", "-k", str(zip_path), str(work / "unzip")]
    assert run.calls[1] == ["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2",
                            str(work / "unzip" / "Tracklister.app")]
    cases = ((("Tracklister.app", "otra"), True, "no tiene solo Tracklister.app"),
             (("Tracklister.app", "__MACOSX"), True, "descomprimida y firmada"),
             (("Tracklister.app",), False, "la app descomprimida no verifica"))
    for i, (names, verify_ok, needle) in enumerate(cases):
        w = tmp_path / f"caso{i}"
        w.mkdir()
        assert needle in smoke.zip_roundtrip(zip_path, w, FakeTools(verify_ok=verify_ok, unzip_names=names))[1]


def test_run_smoke_without_an_app_fails_every_check(tmp_path):
    result = smoke.run_smoke(tmp_path / "Tracklister.app", tmp_path / "x.zip", tmp_path / "shot.png", offscreen=True,
                             timeout_s=5, keep=False, run=FakeTools())
    assert result["ok"] is False and set(result["checks"]) == set(smoke.CHECKS) and not any(result["checks"].values())
    assert result["info"]["details"]["app_starts"].startswith("no existe")


def test_it_only_runs_on_a_mac(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "platform", "linux")
    assert smoke.main(["--json", str(tmp_path / "s.json")]) == 2
    assert "solo se puede probar en un Mac" in capsys.readouterr().out and not (tmp_path / "s.json").exists()
