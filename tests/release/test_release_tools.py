"""The build scripts in packaging/: build.py, ci_prepare.py, fetch_ytdlp.py and smoke_test.py.

SPDX-License-Identifier: GPL-3.0-or-later

Offline: no PyInstaller run, no download, the exe is never started here.
"""
from __future__ import annotations

import hashlib
import re
import struct
import sys
import zipfile
import zlib
from pathlib import Path

import pytest

from tests.release.helpers import REPO, load
from tracklister import __version__
from tracklister.core.bundled import ytdlp_pin
from tracklister.engine.spec import asset_name, engine_pins

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


@pytest.mark.parametrize("line", ["requests>=2.0", "requests==2.*", "requests==2.0,!=2.1", "no es ; un pin =="])
def test_runtime_pins_refuse_anything_but_one_exact_version(tmp_path, line):
    lock = tmp_path / "lock.txt"
    lock.write_text(f"numpy==2.5.3\n{line}\n", encoding="utf-8")
    with pytest.raises(build.BuildError, match=r"lock\.txt"):
        build.runtime_pins(lock, platform="darwin")


def test_runtime_pins_follow_the_platform_markers(tmp_path):
    """macOS 1.1: one lock with environment markers; pywin32-ctypes is a Windows-only pin."""
    win, mac = dict(build.runtime_pins(platform="win32")), dict(build.runtime_pins(platform="darwin"))
    assert win["pywin32-ctypes"] == "0.2.3" and "pywin32-ctypes" not in mac
    assert {k: v for k, v in win.items() if k != "pywin32-ctypes"} == mac
    assert build.runtime_pins() == build.runtime_pins(platform=sys.platform)
    lock = tmp_path / "lock.txt"
    lock.write_text('numpy==2.5.3\nsolo-mac==1.0 ; sys_platform == "darwin"  # comentario\n'
                    "solo-win==2.0; sys_platform == 'win32'\n", encoding="utf-8")
    assert build.runtime_pins(lock, platform="darwin") == [("numpy", "2.5.3"), ("solo-mac", "1.0")]
    assert build.runtime_pins(lock, platform="win32") == [("numpy", "2.5.3"), ("solo-win", "2.0")]


def test_check_lock_warns_about_unpinned_different_and_missing(tmp_path, monkeypatch, capsys):
    check = load("check_lock")
    (tmp_path / "base.txt").write_text('numpy==2.5.3\nsolo-win==1.0 ; sys_platform == "win32"\n', encoding="utf-8")
    dev = tmp_path / "dev.txt"
    dev.write_text("# dev\n-r base.txt\npytest==9.1.1\nPyYAML==6.0.3\nfalta==3.0\n", encoding="utf-8")
    assert check.lock_pins(dev, "darwin") == {"numpy": "2.5.3", "pytest": "9.1.1", "pyyaml": "6.0.3", "falta": "3.0"}
    assert check.lock_pins(dev, "win32")["solo-win"] == "1.0"
    have = {"numpy": "2.5.3", "pytest": "9.0.0", "pyyaml": "6.0.3", "pip": "26.0", "macholib": "1.16.4"}
    monkeypatch.setattr(check, "installed", lambda: have)
    assert check.main(["--lock", str(dev), "--platform", "darwin"]) == 0
    warnings = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("::warning")]
    assert len(warnings) == 3, warnings                                 # pip is never reported
    assert any("macholib 1.16.4" in w and "no lo fija" in w for w in warnings)
    assert any("pytest instalado 9.0.0" in w and "9.1.1" in w for w in warnings)
    assert any("falta 3.0" in w and "no está instalado" in w for w in warnings)
    assert check.main(["--lock", str(tmp_path / "no-existe.txt")]) == 0     # never stops the job
    assert "::warning" in capsys.readouterr().out


def test_check_lock_reads_the_real_locks():
    check = load("check_lock")
    pins = check.lock_pins(check.DEFAULT_LOCK, "darwin")
    assert pins["macholib"] == "1.16.4" and pins["pyyaml"] == "6.0.3" and pins["pyside6-essentials"] == "6.12.0"
    assert not {"pywin32-ctypes", "pefile", "colorama"} & set(pins)
    assert {"pywin32-ctypes", "pefile", "colorama"} <= set(check.lock_pins(check.DEFAULT_LOCK, "win32"))
    assert "macholib" not in check.lock_pins(check.DEFAULT_LOCK, "win32")


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
    build.write_zip(app, out, platform="win32")
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
    problems = build.check_bundle(app, identity_scan=False, platform="win32")
    text = "\n".join(problems).replace("\\", "/")
    for needle in (".tmp", "scipy", "fake_engine.py", "settings.json", "engine.log", "sldl.conf"):
        assert needle in text, needle
    assert "falta en el paquete: Tracklister.exe" in text
    assert "falta en el paquete: _internal/tracklister/assets/tokens.json" in text


def test_check_bundle_detects_a_tampered_engine_or_ytdlp(tmp_path):
    app = tmp_path / "Tracklister"
    pin = engine_pins("win32")["sockseek-3.0.5"]
    _touch(app / "engines" / asset_name(pin), b"not the pinned zip")
    _touch(app / "tools" / "yt-dlp.exe", b"MZ not the pinned exe")
    problems = build.check_bundle(app, identity_scan=False, platform="win32")
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
    release = re.match(r"(\d+)\.(\d+)\.(\d+)", __version__).groups()
    assert version_numbers(__version__) == tuple(int(x) for x in release) + (0,)
    assert version_numbers("1.1.0.dev1") == (1, 1, 0, 0)                   # the macOS test builds (1.1)
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


def _run_ci_on_the_real_config(tmp_path, monkeypatch, owner: str) -> tuple[int, str, str, str]:
    """main() on a copy of the real config.py: (exit code, stdout, original text, text afterwards)."""
    original = (REPO / "src" / "tracklister" / "config.py").read_text(encoding="utf-8")
    copy = tmp_path / "config.py"
    copy.write_text(original, encoding="utf-8", newline="\n")
    monkeypatch.setattr(ci, "CONFIG", copy)
    import io
    from contextlib import redirect_stdout
    out = io.StringIO()
    with redirect_stdout(out):
        code = ci.main(["--tag", f"v{__version__}", "--owner", owner, "--repo", "tracklister"])
    return code, out.getvalue(), original, copy.read_text(encoding="utf-8")


def test_r12_the_real_owner_is_in_the_code():
    from tracklister import config
    assert config.GITHUB_OWNER == "blessel-dev" and "TODO(publish)" not in (
        REPO / "src" / "tracklister" / "config.py").read_text(encoding="utf-8")
    assert config.project_url() == "https://github.com/blessel-dev/tracklister"
    assert config.user_agent() == f"Tracklister/{__version__} ( https://github.com/blessel-dev/tracklister )"


def test_r12_ci_is_silent_with_the_real_owner(tmp_path, monkeypatch):
    code, out, original, after = _run_ci_on_the_real_config(tmp_path, monkeypatch, "blessel-dev")
    assert code == 0 and "::warning::" not in out and "::error::" not in out
    assert after == original                                               # nothing injected


def test_r12_ci_keeps_the_owner_and_warns_in_a_fork(tmp_path, monkeypatch):
    code, out, original, after = _run_ci_on_the_real_config(tmp_path, monkeypatch, "dj-amigo")
    assert code == 0 and out.count("::warning::") == 1 and "(¿un fork?)" in out and "'dj-amigo'" in out
    assert after == original and 'GITHUB_OWNER = "blessel-dev"' in after   # the update notice keeps our repo


def test_mac_a_branch_push_is_a_test_build_without_a_tag(tmp_path, monkeypatch, capsys):
    """1.1: a push to branch mac checks the versions and the owner, but there is no tag to match."""
    copy = tmp_path / "config.py"
    copy.write_text((REPO / "src" / "tracklister" / "config.py").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(ci, "CONFIG", copy)
    assert ci.main(["--tag", "mac", "--ref-type", "branch", "--owner", "blessel-dev", "--repo", "tracklister"]) == 0
    out = capsys.readouterr().out
    assert (f"OK: rama mac, build de prueba (no publica ni crea etiquetas), versión {__version__}, "
            "propietario blessel-dev") in out and "::" not in out
    assert ci.main(["--tag", "mac", "--owner", "blessel-dev"]) == 1         # the default is still a tag
    assert "::error::" in capsys.readouterr().out
    assert ci.main(["--tag", f"v{__version__}", "--ref-type", "tag", "--owner", "blessel-dev"]) == 0
    assert f"OK: etiqueta v{__version__}" in capsys.readouterr().out
    other = tmp_path / "pyproject.toml"                                     # versions must still agree
    other.write_text('[project]\nname = "tracklister"\nversion = "9.9.9"\n', encoding="utf-8")
    monkeypatch.setattr(ci, "PYPROJECT", other)
    assert ci.main(["--tag", "mac", "--ref-type", "branch", "--owner", "blessel-dev"]) == 1
    assert "::error::" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        ci.main(["--tag", "mac", "--ref-type", "", "--owner", "blessel-dev"])  # an empty GITHUB_REF_TYPE


def test_r12_ci_still_injects_into_a_placeholder_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "CONFIG", tmp_path / "config.py")
    ci.CONFIG.write_text(CONFIG, encoding="utf-8", newline="\n")
    assert ci.main(["--tag", f"v{__version__}", "--owner", "dj-amigo"]) == 0
    assert 'GITHUB_OWNER = "dj-amigo"' in ci.CONFIG.read_text(encoding="utf-8")


# ---- fetch_ytdlp.py ---------------------------------------------------------------------------------------------
def test_ytdlp_pin_is_consistent():
    """The pins live in tracklister.core.bundled (the app reads the same ones); the module constants are
    this platform's (Windows: yt-dlp.exe, as before 1.1)."""
    bin_dir = REPO / "third_party" / "yt-dlp" / "bin"
    for platform, name in (("win32", "yt-dlp.exe"), ("darwin", "yt-dlp_macos")):
        pin = ytdlp_pin(platform)
        assert pin.asset_name == name and re.fullmatch(r"[0-9a-f]{64}", pin.sha256) and pin.size > 10_000_000
        assert ytdlp.asset_url(pin) == f"https://github.com/yt-dlp/yt-dlp/releases/download/{pin.version}/{name}"
        assert ytdlp.sums_url(pin).endswith(f"/download/{pin.version}/SHA2-256SUMS")
        assert ytdlp.exe_path(platform) == bin_dir / name
    here = ytdlp_pin(ytdlp.default_platform())
    assert (ytdlp.VERSION, ytdlp.EXE_NAME, ytdlp.EXE_SHA256, ytdlp.EXE_SIZE) == (
        here.version, here.asset_name, here.sha256, here.size)
    assert ytdlp.EXE_URL == ytdlp.asset_url(here) and ytdlp.VERSION in ytdlp.SUMS_URL
    assert all(f"/{ytdlp.VERSION}/" in url for url in ytdlp.LICENCE_FILES.values())
    assert ytdlp.default_platform() == ("darwin" if sys.platform == "darwin" else "win32")


def test_sums_entry_reads_the_release_checksums():
    text = f"{'a' * 64}  yt-dlp.exe\n{'b' * 64}  yt-dlp_x86.exe\n{'c' * 64} *otro.exe\n{'d' * 64}  yt-dlp_macos\n"
    assert ytdlp.sums_entry(text, "yt-dlp.exe") == "a" * 64
    assert ytdlp.sums_entry(text, "otro.exe") == "c" * 64
    assert ytdlp.sums_entry(text, "yt-dlp_macos") == "d" * 64
    assert ytdlp.sums_entry(text, "falta.exe") is None


def test_verify_local_reports_missing_and_tampered(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp, "BIN_DIR", tmp_path)
    assert ytdlp.verify_local("win32")[0].startswith("FALTA")
    (tmp_path / "yt-dlp.exe").write_bytes(b"MZ")
    assert ytdlp.verify_local("win32")[0].startswith("ERROR SHA-256 yt-dlp.exe")
    assert ytdlp.verify_local("darwin")[0].startswith("FALTA")               # each platform its own file
    (tmp_path / "yt-dlp_macos").write_bytes(b"\xca\xfe\xba\xbe not the pinned binary")
    assert ytdlp.verify_local("darwin")[0].startswith("ERROR SHA-256 yt-dlp_macos")


def test_verify_local_checks_the_size_of_the_macos_binary(tmp_path, monkeypatch):
    import dataclasses
    data = b"\xca\xfe\xba\xbe fake universal2"
    monkeypatch.setattr(ytdlp, "BIN_DIR", tmp_path)
    (tmp_path / "yt-dlp_macos").write_bytes(data)
    real = ytdlp_pin("darwin")
    good = dataclasses.replace(real, sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    monkeypatch.setattr(ytdlp, "ytdlp_pin", lambda platform=None: good)
    assert ytdlp.verify_local("darwin") == []
    assert ytdlp.main(["--verify-only", "--platform", "darwin"]) == 0
    monkeypatch.setattr(ytdlp, "ytdlp_pin", lambda platform=None: dataclasses.replace(good, size=len(data) + 1))
    assert ytdlp.verify_local("darwin") == [f"ERROR tamaño yt-dlp_macos: esperado {len(data) + 1} bytes, "
                                            f"obtenido {len(data)}"]


def _fetch_engine():
    import importlib.util
    spec = importlib.util.spec_from_file_location("tracklister_tools_fetch_engine", REPO / "tools" / "fetch_engine.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_fetch_engine_checks_each_platform_with_its_own_pins(tmp_path, monkeypatch, capsys):
    """--verify-only, no network: Windows looks for its two zips, macOS for the Sockseek tar.gz, also by size."""
    import dataclasses
    from tracklister.engine import spec
    fe = _fetch_engine()
    monkeypatch.setattr(fe, "dev_bin_dir", lambda: tmp_path)
    assert fe.verify(fetch=False, platform="win32") == 1
    out = capsys.readouterr().out
    assert "FALTA sockseek_3.0.5_win-x64.zip" in out and "FALTA sldl_win-x86_self-contained.zip" in out
    data = b"\x1f\x8b fake tar.gz"
    (tmp_path / "sockseek_3.0.5_osx-arm64.tar.gz").write_bytes(data)
    pin = spec.engine_pins("darwin")["sockseek-3.0.5"]
    assert pin.asset_size == 46570010
    monkeypatch.setitem(spec.engine_pins("darwin"), "sockseek-3.0.5",
                        dataclasses.replace(pin, asset_sha256=hashlib.sha256(data).hexdigest(), asset_size=len(data)))
    assert fe.verify(fetch=False, platform="darwin") == 0
    out = capsys.readouterr().out
    assert f"OK sockseek_3.0.5_osx-arm64.tar.gz sha256={hashlib.sha256(data).hexdigest()} ({len(data)} bytes)" in out
    assert "sldl" not in out                                               # no sldl and no sldl source on macOS
    monkeypatch.setitem(spec.engine_pins("darwin"), "sockseek-3.0.5",
                        dataclasses.replace(pin, asset_sha256=hashlib.sha256(data).hexdigest(), asset_size=1))
    assert fe.verify(fetch=False, platform="darwin") == 1
    assert "ERROR tamaño sockseek_3.0.5_osx-arm64.tar.gz: esperado 1 bytes" in capsys.readouterr().out


def test_fetch_engine_never_keeps_a_bad_download(tmp_path, monkeypatch, capsys):
    """CL-45: a cut or tampered engine download got its final name first and failed the SHA-256 afterwards, so
    every later run found the file, never downloaded it again and failed until someone deleted it by hand. The
    .part is checked first now, and deleted when it does not match. No network: _get is faked."""
    from tracklister.engine.spec import asset_name, engine_pins
    fe = _fetch_engine()
    monkeypatch.setattr(fe, "dev_bin_dir", lambda: tmp_path)
    asked: list[str] = []

    class Bad:
        def iter_content(self, chunk_size=0):
            yield b"not the pinned archive"

    def get(url, stream=False):
        asked.append(url)
        return Bad()
    monkeypatch.setattr(fe, "_get", get)
    pin = engine_pins("darwin")["sockseek-3.0.5"]
    name = asset_name(pin)
    for attempt in (1, 2):
        assert fe.verify(fetch=True, platform="darwin") == 1
        assert not (tmp_path / name).exists() and not (tmp_path / (name + ".part")).exists()
        assert asked.count(pin.asset_url) == attempt         # nothing was kept: the next run downloads it again
    assert f"ERROR SHA-256 {name}" in capsys.readouterr().out


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
