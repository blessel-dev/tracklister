"""The publish job's script (packaging/publish_release.py) and the CI failure annotations
(packaging/ci_annotate.py). Offline, on fake zips: nothing is published here.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.release.helpers import PACKAGING, REPO, load
from tracklister import __version__
from tracklister.engine.spec import SOURCE_ARCHIVES

pub = load("publish_release")
ann = load("ci_annotate")

WIN = f"Tracklister-{__version__}-win64.zip"
MAC = f"Tracklister-{__version__}-macos-arm64.zip"
SOURCES = [f"{eid}-source.zip" for eid in SOURCE_ARCHIVES]


def _artifacts(root: Path) -> dict[str, bytes]:
    """The layout of the two downloads: the Windows artifact unzipped, the macOS zip as it was uploaded."""
    data = {WIN: b"PK windows", MAC: b"PK macos"} | {name: f"PK {name}".encode() for name in SOURCES}
    for name, payload in data.items():
        folder = root / ("mac" if name == MAC else "windows-release")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(payload)
    (root / "windows-release" / "LEEME.txt").write_text("no es un zip", encoding="utf-8")   # ignored
    return data


def _run(tmp_path: Path, mode: str) -> tuple[int, Path, Path]:
    out, notes = tmp_path / "out", tmp_path / "release-notes.md"
    code = pub.main(["--files", str(tmp_path / "in"), "--out", str(out), "--notes", str(notes), "--mode", mode])
    return code, out, notes


def test_the_names_follow_the_version_and_the_engine_sources():
    assert pub.expected_names() == [WIN, MAC] + SOURCES
    assert SOURCES == ["sockseek-3.0.5-source.zip", "sldl-2.6.0-source.zip"]
    assert pub.mac_zip_name("1.1.0") == "Tracklister-1.1.0-macos-arm64.zip"
    build = load("build")
    assert build.zip_name("win32") == WIN and build.zip_name("darwin") == MAC


def test_a_dry_run_writes_one_checksum_file_and_marked_notes(tmp_path, capsys):
    data = _artifacts(tmp_path / "in")
    code, out, notes = _run(tmp_path, "dry-run")
    log = capsys.readouterr().out
    assert code == 0, log
    assert sorted(p.name for p in out.iterdir()) == sorted([WIN, MAC, *SOURCES, "SHA256SUMS.txt"])
    raw = (out / "SHA256SUMS.txt").read_bytes()
    assert b"\r" not in raw
    expected = [f"{hashlib.sha256(data[n]).hexdigest()}  {n}" for n in sorted(data)]
    assert raw.decode("ascii").splitlines() == expected
    text = notes.read_text(encoding="utf-8")
    assert f"# Tracklister {__version__}" in text and WIN in text and MAC in text
    assert pub.MAC_MARKER in text and "MARCADOR" in text and "no publica nada" in text
    assert all(line in text for line in expected) and "{" not in text
    assert "::group::SHA256SUMS.txt" in log and "::group::Notas de la release (dry-run)" in log
    assert "no se publica nada" in log and "::error" not in log


def test_publish_refuses_notes_without_the_macos_section(tmp_path, capsys):
    _artifacts(tmp_path / "in")
    assert "{mac_zip_name}" not in pub.TEMPLATE.read_text(encoding="utf-8")   # phase D writes it
    code, out, notes = _run(tmp_path, "publish")
    log = capsys.readouterr().out
    assert code == 1 and "::error title=Publicar::" in log and "{mac_zip_name}" in log
    assert not out.exists() and not notes.exists()                           # nothing prepared


def test_publish_fills_a_template_with_the_macos_section(tmp_path, monkeypatch, capsys):
    _artifacts(tmp_path / "in")
    template = tmp_path / "plantilla.md"
    template.write_text("# Tracklister {version}\n\nWindows: {zip_name}\nMac: {mac_zip_name}\n\n```\n{sums}\n```\n",
                        encoding="utf-8")
    monkeypatch.setattr(pub, "TEMPLATE", template)
    code, out, notes = _run(tmp_path, "publish")
    assert code == 0, capsys.readouterr().out
    text = notes.read_text(encoding="utf-8")
    assert f"Mac: {MAC}" in text and f"Windows: {WIN}" in text and pub.MAC_MARKER not in text
    assert (out / "SHA256SUMS.txt").read_text(encoding="ascii").count("\n") == 4


@pytest.mark.parametrize("case", ["missing", "duplicate", "other_version"])
def test_a_missing_repeated_or_unexpected_zip_stops_it(tmp_path, capsys, case):
    root = tmp_path / "in"
    _artifacts(root)
    if case == "missing":
        (root / "mac" / MAC).unlink()
    elif case == "duplicate":
        (root / "otra").mkdir()
        (root / "otra" / WIN).write_bytes(b"PK otra")
    else:
        (root / "mac" / "Tracklister-1.0.1-macos-arm64.zip").write_bytes(b"PK vieja")
    code, out, _ = _run(tmp_path, "dry-run")
    log = capsys.readouterr().out
    assert code == 1 and not out.exists()
    needle = {"missing": f"falta {MAC}", "duplicate": f"{WIN} aparece 2 veces",
              "other_version": "zip inesperado: Tracklister-1.0.1-macos-arm64.zip"}[case]
    assert f"::error title=Publicar::{needle}" in log, log


def _stdlib_only(script: str, args: list[str]) -> subprocess.CompletedProcess:
    """Run a script with `python -S` (no site-packages): the publish job has no venv."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop("PYTHONPATH", None)
    return subprocess.run([sys.executable, "-S", str(PACKAGING / script), *args], capture_output=True,
                          text=True, encoding="utf-8", env=env, cwd=str(REPO), timeout=120)


def test_both_scripts_need_only_the_standard_library(tmp_path):
    _artifacts(tmp_path / "in")
    r = _stdlib_only("publish_release.py", ["--files", str(tmp_path / "in"), "--out", str(tmp_path / "out"),
                                            "--notes", str(tmp_path / "notas.md"), "--mode", "dry-run"])
    assert r.returncode == 0, r.stdout + r.stderr
    log = tmp_path / "build.log"
    log.write_text("ERROR: El paquete no está listo:\n  falta en el paquete: Contents/Info.plist\n", encoding="utf-8")
    r = _stdlib_only("ci_annotate.py", ["--title-prefix", "macOS", "--log", str(log)])
    assert r.returncode == 0 and r.stdout.startswith("::error title=macOS build.log::ERROR"), r.stdout + r.stderr


JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="1" failures="12" tests="20">
<testcase classname="tests.darwin.test_volumes" name="test_nfd[HFS+]"><failure message="AssertionError: 100%&#10;segunda línea">detalle</failure></testcase>
<testcase classname="tests.darwin.test_quarantine" name="test_copies"><error message="hdiutil: attach failed, x"/></testcase>
<testcase classname="tests.core.test_ok" name="test_bien"/>
{more}
</testsuite></testsuites>
"""


def test_annotations_list_failing_tests_then_log_lines_capped_and_escaped(tmp_path, capsys):
    more = "\n".join(f'<testcase classname="tests.x" name="t{i}"><failure message="m{i}"/></testcase>' for i in range(11))
    junit = tmp_path / "pytest.xml"
    junit.write_text(JUNIT.format(more=more), encoding="utf-8")
    assert ann.main(["--title-prefix", "macOS", "--junit", str(junit), "--max", "10"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 10 and all(ln.startswith("::error title=macOS test::") for ln in lines)
    assert lines[0] == "::error title=macOS test::tests.darwin.test_volumes::test_nfd[HFS+]: AssertionError: 100%25"
    assert lines[1] == "::error title=macOS test::tests.darwin.test_quarantine::test_copies: hdiutil: attach failed, x"


def test_pytest_s_own_summary_lines_are_not_repeated_after_the_junit_ones(tmp_path, capsys):
    junit = tmp_path / "pytest.xml"
    junit.write_text(JUNIT.format(more=""), encoding="utf-8")
    log = tmp_path / "pytest.log"
    log.write_text("FAILED tests/darwin/test_volumes.py::test_nfd[HFS+] - AssertionError: 100%\n"
                   "ERROR tests/darwin/test_quarantine.py::test_copies - hdiutil\n"
                   "ERROR: algo que no es un test\n", encoding="utf-8")
    assert ann.main(["--title-prefix", "macOS", "--junit", str(junit), "--log", str(log)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3 and lines[2] == "::error title=macOS pytest.log::ERROR: algo que no es un test"
    assert ann.main(["--title-prefix", "macOS", "--log", str(log)]) == 0      # without JUnit they are the news
    assert len(capsys.readouterr().out.splitlines()) == 3


def test_annotations_from_logs_and_the_smoke_json(tmp_path, capsys):
    log = tmp_path / "build.log"
    log.write_text("PyInstaller...\nERROR: El paquete no está listo:\n  falta en el paquete: Contents/Info.plist\n"
                   "  SHA-256 del motor no coincide: sockseek_3.0.5_osx-arm64.tar.gz\nfin\n"
                   "Traceback (most recent call last):\n  File \"x.py\", line 1, in <module>\n"
                   "BuildError: codesign falló\n"
                   "Tracklister.app: a sealed resource is missing or invalid\n", encoding="utf-8")
    smoke = tmp_path / "smoke.json"
    smoke.write_text(json.dumps({"ok": False, "checks": {"codesign_verify": False, "launch": True},
                                 "info": {"details": {"codesign_verify": "codesign --verify: exit 1"}}}),
                     encoding="utf-8")
    assert ann.main(["--title-prefix", "macOS", "--log", str(log), str(tmp_path / "no-existe.log"),
                     "--smoke", str(smoke), "--junit", str(tmp_path / "no-existe.xml")]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "::error title=macOS build.log::ERROR: El paquete no está listo: / falta en el paquete: Contents/Info.plist"
        " / SHA-256 del motor no coincide: sockseek_3.0.5_osx-arm64.tar.gz",
        "::error title=macOS build.log::Traceback: BuildError: codesign falló",
        "::error title=macOS build.log::Tracklister.app: a sealed resource is missing or invalid",
        "::error title=macOS smoke::codesign_verify: codesign --verify: exit 1",
    ]


def _junit_with_13_failures(tmp_path: Path) -> Path:
    more = "\n".join(f'<testcase classname="tests.x" name="t{i}"><failure message="m{i}"/></testcase>'
                     for i in range(11))
    junit = tmp_path / "pytest.xml"
    junit.write_text(JUNIT.format(more=more), encoding="utf-8")
    return junit


@pytest.mark.parametrize("build_errors,tests_shown", [(8, 5), (1, 8)])
def test_many_failing_tests_leave_room_for_the_packaging_failures(tmp_path, capsys, build_errors, tests_shown):
    """1.1b: a branch build still packages the app after failed tests, so up to half of the 10 annotations stay
    for the build and the smoke test."""
    junit = _junit_with_13_failures(tmp_path)
    log = tmp_path / "build.log"
    log.write_text("".join(f"ERROR: fallo {i} del paquete\n" for i in range(build_errors)), encoding="utf-8")
    smoke = tmp_path / "smoke.json"
    smoke.write_text(json.dumps({"ok": False, "checks": {"codesign_verify": False}, "info": {"details": {}}}),
                     encoding="utf-8")
    assert ann.main(["--title-prefix", "macOS", "--junit", str(junit), "--log", str(log), "--smoke", str(smoke)]) == 0
    titles = [line.split("::")[1] for line in capsys.readouterr().out.splitlines()]
    others = ["error title=macOS build.log"] * build_errors + ["error title=macOS smoke"]
    assert titles == ["error title=macOS test"] * tests_shown + others[:10 - tests_shown]


@pytest.mark.parametrize("last,expected", [
    ("5 failed, 1531 passed, 6 skipped in 386.35s (0:06:26)", "5 failed, 1531 passed, 6 skipped in 386.35s"),
    ("====== 1542 passed, 6 skipped, 2 warnings in 380.10s (0:06:20) ======",
     "1542 passed, 6 skipped, 2 warnings in 380.10s"),
    ("1 error in 0.52s", "1 error in 0.52s"),
])
def test_the_totals_notice_is_pytest_s_own_summary_line(tmp_path, capsys, last, expected):
    log = tmp_path / "pytest.log"
    log.write_text(f"....F..s\nFAILED tests/x.py::t - 1 passed in 2s\n{last}\n3 apples in 2s\n", encoding="utf-8")
    junit = _junit_with_13_failures(tmp_path)
    assert ann.main(["--title-prefix", "macOS", "--summary", str(log), "--junit", str(junit)]) == 0
    assert capsys.readouterr().out.splitlines() == [f"::notice title=macOS pytest::{expected}"]    # no ::error


def test_the_totals_notice_falls_back_to_the_junit_counts(tmp_path, capsys):
    log = tmp_path / "pytest.log"
    log.write_text("....F\nFatal Python error: Segmentation fault\n", encoding="utf-8")
    junit = tmp_path / "pytest.xml"
    junit.write_text(JUNIT.format(more=""), encoding="utf-8")                # tests 20, failures 12, errors 1
    assert ann.main(["--title-prefix", "macOS", "--summary", str(log), "--junit", str(junit)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "::notice title=macOS pytest::7 passed, 12 failed, 0 skipped, 1 errors "
        "(del JUnit: pytest no escribió su resumen)"]
    assert ann.main(["--title-prefix", "macOS", "--summary", str(tmp_path / "no-existe.log")]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "::notice title=macOS pytest::pytest no dejó resumen (¿se cortó antes de terminar?)"]


def test_annotations_fall_back_to_the_last_log_line_and_never_fail(tmp_path, capsys):
    log = tmp_path / "pip.log"
    log.write_text("Collecting x\nNo matching distribution found for macholib==9\n\n", encoding="utf-8")
    assert ann.main(["--title-prefix", "mac:OS,x", "--log", str(log)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "::error title=mac%3AOS%2Cx pip.log (última línea)::No matching distribution found for macholib==9"]
    assert ann.main(["--max", "no-es-un-numero"]) == 0                      # bad arguments: still exit 0
    assert ann.escape_data("50%\r\nx") == "50%25%0D%0Ax" and ann.escape_property("a:b,c") == "a%3Ab%2Cc"
