"""Golden command lines: the exact argv per engine dialect, preset pass, relaxed and print modes.

Regenerate (only after a deliberate adapter change, then review the diff):
    $env:TRACKLISTER_UPDATE_GOLDEN="1"; .venv\\Scripts\\python.exe -m pytest -q tests\\engine\\test_cli_golden.py
"""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath

import pytest

from tracklister.core.settings import CustomPreset
from tracklister.engine.cli import EngineJob, build_command, redact_argv
from tracklister.engine.credentials import Credentials
from tracklister.engine.presets import build_preset, relaxed
from tracklister.engine.spec import ENGINE_PINS, EngineSpec, fake_engine_spec

GOLDEN = Path(__file__).parent / "golden"
WORK = Path(PureWindowsPath(r"C:\tl\work\abcd1234\p01"))
CREDS = Credentials("usuario-prueba", "clave-prueba")
PRESETS = ("lossless", "cdj_antiguos", "solo_mp3_320", "personalizado")


def _spec(engine_id: str) -> EngineSpec:
    pin = ENGINE_PINS[engine_id]
    return EngineSpec(engine_id, pin.dialect, (rf"C:\engines\{engine_id}\{pin.exe_name}",))


def _cases():
    for eid in ENGINE_PINS:
        for pid in PRESETS:
            custom = CustomPreset(formats=["flac", "aiff", "mp3"], min_mp3_kbps=320,
                                  max_samplerate=96000) if pid == "personalizado" else None
            for p in build_preset(pid, custom).passes:
                yield f"{eid}__{pid}__{p.name}", eid, EngineJob(WORK, p, True, 49998)
        lossless = build_preset("lossless").passes[0]
        yield f"{eid}__lossless__lossless-relaxed-sin-duracion", eid, EngineJob(
            WORK, relaxed(lossless), False, 50123, concurrent=2)
        yield f"{eid}__diagnostico__print-json-all", eid, EngineJob(
            WORK, lossless, True, 49998, print_json_all=True,
            input_override="artist=Fjaak, title=Spirit, length=301")


CASES = list(_cases())


@pytest.mark.parametrize("name,eid,job", CASES, ids=[c[0] for c in CASES])
def test_golden_argv(name, eid, job):
    spec = _spec(eid)
    argv = build_command(spec, job, CREDS)
    assert argv[: len(spec.argv_prefix)] == list(spec.argv_prefix)
    got = "\n".join(redact_argv(argv[len(spec.argv_prefix):])) + "\n"
    path = GOLDEN / f"{name}.txt"
    if os.environ.get("TRACKLISTER_UPDATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(got, encoding="utf-8", newline="\n")
    assert path.read_text(encoding="utf-8") == got


def test_golden_files_have_no_secrets_and_no_forbidden_flags():
    files = sorted(GOLDEN.glob("*.txt"))
    assert len(files) == len(CASES)
    for f in files:
        lines = f.read_text(encoding="utf-8").splitlines()
        assert "usuario-prueba" not in lines and "clave-prueba" not in lines
        for bad in ("-o", "--strict-conditions", "--fast-search", "--profile", "--shared-files"):
            assert bad not in lines, (f.name, bad)
        assert lines[lines.index("--user") + 1] == "***" and lines[lines.index("--pass") + 1] == "***"
        for flag in ("--no-config", "--index-path", "--log-file", "--no-progress", "--listen-port",
                     "--no-modify-share-count", "--name-format", "--no-skip-existing"):
            assert flag in lines, (f.name, flag)
        assert lines[lines.index("--name-format") + 1] == "{snum}/{slsk-filename}"


def test_dialect_differences_are_exactly_the_three_documented():
    p = build_preset("lossless").passes[0]
    job = EngineJob(WORK, p, True, 49998)
    a3 = build_command(_spec("sockseek-3.0.5"), job, CREDS)[1:]
    a2 = build_command(_spec("sldl-2.6.0"), job, CREDS)[1:]
    assert a3[a3.index("--output-dir") + 1] == str(WORK / "in")
    assert a2[a2.index("-p") + 1] == str(WORK / "in")
    swap = {"--output-dir": "-p", "--concurrent-jobs": "--concurrent-downloads"}
    assert [swap.get(t, t) for t in a3] == a2


def test_secret_values_starting_with_dash_use_attached_form():
    p = build_preset("lossless").passes[0]
    argv = build_command(_spec("sockseek-3.0.5"), EngineJob(WORK, p, False, 49998),
                         Credentials("-raro", "-secreto con espacio"))
    assert "--user=-raro" in argv and "--pass=-secreto con espacio" in argv
    red = redact_argv(argv)
    assert "--user=***" in red and "--pass=***" in red
    assert not any("secreto" in t or "raro" in t for t in red)


def test_length_tol_only_with_durations_and_flags_follow_the_pass():
    p = build_preset("solo_mp3_320").passes[0]
    a = build_command(_spec("sockseek-3.0.5"), EngineJob(WORK, p, False, 49998), CREDS)
    assert "--length-tol" not in a
    assert a[a.index("--format") + 1] == "mp3" and a[a.index("--min-bitrate") + 1] == "320"
    r = build_command(_spec("sockseek-3.0.5"), EngineJob(WORK, relaxed(p), True, 49998), CREDS)
    assert "--strict-title" in r and "--strict-artist" not in r and r[r.index("--length-tol") + 1] == "3"


def test_fake_spec_prefix_is_python_plus_script():
    p = build_preset("lossless").passes[0]
    spec = fake_engine_spec()
    argv = build_command(spec, EngineJob(WORK, p, True, 49998), CREDS)
    assert argv[0] == spec.argv_prefix[0] and argv[1].endswith("fake_engine.py")


@pytest.mark.parametrize("eid", list(ENGINE_PINS))
def test_adapter_matches_argv_the_real_engine_accepted_in_mock_mode(eid):
    """tests/fixtures/engine/mock-run/<id>/argv.txt was accepted by the real binary (mock mode)."""
    real = (Path(__file__).parents[1] / "fixtures" / "engine" / "mock-run" / eid / "argv.txt")
    lines = real.read_text(encoding="utf-8").splitlines()
    cut = lines.index("--mock-files-dir")
    accepted = lines[:cut]
    work = Path(PureWindowsPath(r"C:\T\w\p01"))
    p = build_preset("lossless").passes[0]
    mine = redact_argv(build_command(_spec(eid), EngineJob(work, p, True, 49998, concurrent=2), CREDS)[1:])
    assert [t.replace("<TMP>", r"C:\T") for t in accepted] == mine
