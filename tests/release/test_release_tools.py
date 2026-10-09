"""The build scripts in packaging/: build.py, ci_prepare.py, fetch_ytdlp.py and smoke_test.py.

SPDX-License-Identifier: GPL-3.0-or-later

Offline: no PyInstaller run, no download, the exe is never started here.
"""
from __future__ import annotations

import hashlib
import re
import struct
import zipfile
import zlib
from pathlib import Path

import pytest

from tests.release.helpers import REPO, load
from tracklister import __version__
from tracklister.engine.spec import ENGINE_PINS, asset_name

build = load("build")
ci = load("ci_prepare")
ytdlp = load("fetch_ytdlp")
smoke = load("smoke_test")


# ---- build.py ---------------------------------------------------------------------------------------------------
def test_runtime_pins_are_the_exact_lock():
    pins = build.runtime_pins()
    names = [n for n, _ in pins]
    assert {"PySide6_Essentials", "numpy", "mutagen", "keyring", "requests", "soundfile"} <= set(names)
    assert all(re.fullmatch(r"\d+(\.\d+)*", v) for _, v in pins)
    assert len(names) == len(set(names))


def test_runtime_pins_refuse_an_unpinned_line(tmp_path):
    lock = tmp_path / "lock.txt"
    lock.write_text("# comment\nnumpy==2.5.3\nrequests\n", encoding="utf-8")
    with pytest.raises(build.BuildError, match="requests"):
        build.runtime_pins(lock)


def test_every_runtime_pin_ships_a_licence_text():
    for name, pinned in build.runtime_pins():
        version, files = build.package_licence_files(name)
        assert version == pinned, f"{name}: venv {version} != lock {pinned}"
        assert files and all(src.is_file() for src, _ in files), name


def test_pyside_and_shiboken_ship_the_lgpl3_text():
    for name in ("PySide6_Essentials", "shiboken6"):
        _, files = build.package_licence_files(name)
        assert [(p.name, rel) for p, rel in files] == [("LGPL-3.0.txt", "LGPL-3.0.txt")]
        assert "GNU LESSER GENERAL PUBLIC LICENSE" in files[0][0].read_text(encoding="utf-8")


def test_sha256sums_file_is_coreutils_format(tmp_path):
    a, b = tmp_path / "b.zip", tmp_path / "a.zip"
    a.write_bytes(b"uno")
    b.write_bytes(b"dos")
    sums = tmp_path / "SHA256SUMS.txt"
    build.write_sums([a, b], sums)
    raw = sums.read_bytes()
    assert b"\r" not in raw
    assert raw.decode("ascii").splitlines() == [f"{hashlib.sha256(b'dos').hexdigest()}  a.zip",
                                                f"{hashlib.sha256(b'uno').hexdigest()}  b.zip"]


def test_zip_has_a_single_tracklister_folder(tmp_path):
    app = tmp_path / "Tracklister"
    (app / "_internal" / "x").mkdir(parents=True)
    (app / "Tracklister.exe").write_bytes(b"MZ")
    (app / "_internal" / "x" / "a.txt").write_text("hola", encoding="utf-8")
    out = tmp_path / "out" / "t.zip"
    build.write_zip(app, out)
    with zipfile.ZipFile(out) as z:
        assert sorted(z.namelist()) == ["Tracklister/Tracklister.exe", "Tracklister/_internal/x/a.txt"]
        assert z.read("Tracklister/_internal/x/a.txt") == b"hola"
    assert not out.with_name("t.zip.part").exists()


def test_release_notes_are_filled_in(tmp_path):
    sums = tmp_path / "SHA256SUMS.txt"
    sums.write_text(f"{'a' * 64}  {build.ZIP_NAME}\n", encoding="ascii")
    notes = tmp_path / "notes.md"
    build.write_release_notes(sums, notes)
    text = notes.read_text(encoding="utf-8")
    assert f"# Tracklister {__version__}" in text and build.ZIP_NAME in text and "a" * 64 in text
    assert "{" not in text and "SmartScreen" in text and "Get-FileHash" in text


def _touch(p: Path, data: bytes = b"x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_check_bundle_refuses_scratch_dev_modules_and_user_files(tmp_path):
    app = tmp_path / "Tracklister"
    _touch(app / ".tmp" / "capturas-1" / "shot.png")
    _touch(app / "_internal" / "scipy" / "linalg.pyd")
    _touch(app / "_internal" / "tests" / "fakes" / "fake_engine.py")
    _touch(app / "settings.json")
    _touch(app / "engine.log")
    _touch(app / "sldl.conf")
    problems = build.check_bundle(app, identity_scan=False)
    text = "\n".join(problems)
    for needle in (".tmp", "scipy", "fake_engine.py", "settings.json", "engine.log", "sldl.conf"):
        assert needle in text, needle
    assert "falta en el paquete: Tracklister.exe" in text
    assert "falta en el paquete: _internal\\tracklister\\assets\\tokens.json" in text


def test_check_bundle_detects_a_tampered_engine_or_ytdlp(tmp_path):
    app = tmp_path / "Tracklister"
    pin = ENGINE_PINS["sockseek-3.0.5"]
    _touch(app / "engines" / asset_name(pin), b"not the pinned zip")
    _touch(app / "tools" / "yt-dlp.exe", b"MZ not the pinned exe")
    problems = build.check_bundle(app, identity_scan=False)
    assert f"SHA-256 del motor no coincide: {asset_name(pin)}" in problems
    assert "SHA-256 de yt-dlp.exe no coincide" in problems


def test_openssl_version_has_the_expected_shape():
    assert re.fullmatch(r"\d+\.\d+\.\d+\w*", build.openssl_version())


# ---- ci_prepare.py ----------------------------------------------------------------------------------------------
CONFIG = ('APP_NAME = "Tracklister"\n'
          'GITHUB_OWNER = "OWNER_PLACEHOLDER"       # TODO(publish): set to the GitHub user at publish time\n'
          'GITHUB_REPO = "tracklister"\n')


def test_tag_must_be_v_plus_the_app_version():
    assert ci.app_version() == __version__
    assert ci.check_tag(f"v{__version__}", __version__) is None
    for tag in ("v9.9.9", __version__, f"V{__version__}", f"v{__version__}-rc1"):
        assert tag in ci.check_tag(tag, __version__)
    assert ci.check_tag("v1.0.1rc1", "1.0.1rc1") is None                  # a pre-release follows the same rule


def test_r2_n10_pyproject_must_say_the_same_version(tmp_path, monkeypatch, capsys):
    assert ci.pyproject_version() == __version__                            # the real files agree today
    assert ci.check_versions("1.0.0", "1.0.0") is None
    msg = ci.check_versions("1.0.1", "1.0.0")
    assert "pyproject.toml (1.0.0)" in msg and "(1.0.1" in msg
    other = tmp_path / "pyproject.toml"
    other.write_text('[project]\nname = "tracklister"\nversion = "9.9.9"\n', encoding="utf-8")
    monkeypatch.setattr(ci, "PYPROJECT", other)
    assert ci.main(["--tag", f"v{__version__}", "--owner", "dj-amigo"]) == 1
    assert "::error::" in capsys.readouterr().out and ci.CONFIG.read_text(encoding="utf-8").count("dj-amigo") == 0


def _spec_function(name: str):
    """A function of packaging/tracklister.spec (which only PyInstaller can run as a whole)."""
    import ast
    import re as re_mod
    tree = ast.parse((REPO / "packaging" / "tracklister.spec").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    ns = {"re": re_mod}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "tracklister.spec", "exec"), ns)  # noqa: S102
    return ns[name]


def test_r2_n10_the_spec_accepts_pre_release_versions():
    version_numbers = _spec_function("version_numbers")
    assert version_numbers(__version__) == tuple(int(x) for x in __version__.split(".")) + (0,)
    assert version_numbers("1.0.1rc1") == (1, 0, 1, 0)
    assert version_numbers("1.1.0-beta.2") == (1, 1, 0, 0)
    assert version_numbers("2.0.0.dev3") == (2, 0, 0, 0) and version_numbers("3") == (3, 0, 0, 0)
    with pytest.raises(ValueError):
        version_numbers("versión")
    src = (REPO / "packaging" / "tracklister.spec").read_text(encoding="utf-8")
    assert "nums = version_numbers(version)" in src and "int(x) for x in version.split" not in src


def test_placeholder_owner_is_filled_in_for_the_build_only():
    new, warnings = ci.set_owner(CONFIG, "dj-amigo")
    assert 'GITHUB_OWNER = "dj-amigo"       # TODO(publish)' in new
    assert new.replace('"dj-amigo"', '"OWNER_PLACEHOLDER"') == CONFIG
    assert len(warnings) == 1 and "dj-amigo" in warnings[0]


def test_a_configured_owner_is_kept():
    configured = CONFIG.replace("OWNER_PLACEHOLDER", "dj-amigo")
    assert ci.set_owner(configured, "DJ-Amigo") == (configured, [])        # GitHub names ignore case
    same, warnings = ci.set_owner(configured, "otra-cuenta")               # a fork keeps the original
    assert same == configured and len(warnings) == 1


@pytest.mark.parametrize("bad", ["", "dos palabras", "-guion", "x" * 40, 'x"; import os #', "a/b"])
def test_an_invalid_owner_is_refused(bad):
    with pytest.raises(ValueError):
        ci.set_owner(CONFIG, bad)


def test_repo_name_mismatch_only_warns():
    assert ci.check_repo_name(CONFIG, "Tracklister") == [] and ci.check_repo_name(CONFIG, None) == []
    assert len(ci.check_repo_name(CONFIG, "otro-nombre")) == 1


def test_the_real_config_has_the_lines_the_workflow_edits():
    text = (REPO / "src" / "tracklister" / "config.py").read_text(encoding="utf-8")
    assert ci._OWNER_LINE.search(text) and ci._REPO_LINE.search(text).group(1) == "tracklister"


# ---- fetch_ytdlp.py ---------------------------------------------------------------------------------------------
def test_ytdlp_pin_is_consistent():
    assert re.fullmatch(r"[0-9a-f]{64}", ytdlp.EXE_SHA256)
    assert f"/download/{ytdlp.VERSION}/yt-dlp.exe" in ytdlp.EXE_URL and ytdlp.VERSION in ytdlp.SUMS_URL
    assert all(f"/{ytdlp.VERSION}/" in url for url in ytdlp.LICENCE_FILES.values())
    assert ytdlp.exe_path() == REPO / "third_party" / "yt-dlp" / "bin" / "yt-dlp.exe"


def test_sums_entry_reads_the_release_checksums():
    text = f"{'a' * 64}  yt-dlp.exe\n{'b' * 64}  yt-dlp_x86.exe\n{'c' * 64} *otro.exe\n"
    assert ytdlp.sums_entry(text) == "a" * 64
    assert ytdlp.sums_entry(text, "otro.exe") == "c" * 64
    assert ytdlp.sums_entry(text, "falta.exe") is None


def test_verify_local_reports_missing_and_tampered(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp, "BIN_DIR", tmp_path)
    assert ytdlp.verify_local()[0].startswith("FALTA")
    (tmp_path / "yt-dlp.exe").write_bytes(b"MZ")
    assert ytdlp.verify_local()[0].startswith("ERROR SHA-256")


# ---- smoke_test.py ----------------------------------------------------------------------------------------------
def test_clean_env_has_no_python_and_a_fresh_home(tmp_path):
    base = {"Path": r"C:\Program Files\Python313;C:\proj\.venv\Scripts", "PYTHONPATH": "src", "PYTHONHOME": "x",
            "VIRTUAL_ENV": r"C:\proj\.venv", "SystemRoot": r"C:\Windows", "USERPROFILE": r"C:\Users\u",
            "OTRA": "1"}
    env = smoke.clean_env(tmp_path, offscreen=True, base=base)
    assert env["PATH"] == smoke.system_path() and "Path" not in env
    assert not {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "OTRA"} & set(env)
    assert env["SystemRoot"] == r"C:\Windows" and env["USERPROFILE"] == r"C:\Users\u"
    assert env["TRACKLISTER_HOME"] == str(tmp_path) and env["QT_QPA_PLATFORM"] == "offscreen"
    assert env["PYTHON_KEYRING_BACKEND"] == "keyring.backends.null.Keyring"     # never the real Credential Manager
    assert "QT_QPA_PLATFORM" not in smoke.clean_env(tmp_path, offscreen=False, base=base)


def test_the_smoke_path_reaches_no_python(tmp_path):
    assert smoke.python_on_path(smoke.system_path()) == []
    (tmp_path / "python.exe").write_bytes(b"")
    assert smoke.python_on_path(str(tmp_path))                                # the check does find one


def test_png_size_reads_the_header(tmp_path):
    ihdr = struct.pack(">IIBBBBB", 640, 480, 8, 2, 0, 0, 0)
    chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk)
    assert smoke.png_size(png) == (640, 480)
    (tmp_path / "b.png").write_bytes(b"GIF89a")
    assert smoke.png_size(tmp_path / "b.png") is None and smoke.png_size(tmp_path / "nada.png") is None


def test_log_problems_counts_errors_only(tmp_path):
    log = tmp_path / "tracklister.log"
    log.write_text("2026-10-09 INFO tracklister.gui: ok\n2026-10-09 ERROR tracklister.gui: uncaught: x\n"
                   "Traceback (most recent call last):\n", encoding="utf-8")
    assert len(smoke.log_problems(log)) == 2
    assert smoke.log_problems(tmp_path / "no-existe.log") == []
