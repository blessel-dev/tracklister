"""The FAKE engine honours the adapter's argv and reproduces the real engines' output shapes.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fakes.scenarios import SCENARIOS, build_scenario
from tracklister.engine.cli import EngineJob, build_command
from tracklister.engine.credentials import Credentials
from tracklister.engine.csvwriter import write_engine_csv
from tracklister.engine.presets import build_preset
from tracklister.engine.spec import EngineDialect, fake_engine_spec

CREDS = Credentials("usuario-prueba", "clave-prueba")
FAKE = Path(__file__).parents[1] / "fakes" / "fake_engine.py"


def run_fake(tmp_path, scenario, dialect=EngineDialect.SOCKSEEK3, preset="lossless", pass_index=0, **jobkw):
    rows, net = build_scenario(scenario, tmp_path / "net")
    work = tmp_path / "work" / "p01"
    work.mkdir(parents=True)
    rows = [r for r in rows if r.download]
    manifest = write_engine_csv(rows, work / "input.csv")
    fmt = build_preset(preset).passes[pass_index]
    job = EngineJob(work, fmt, any(m.length for m in manifest), 49998, **jobkw)
    argv = build_command(fake_engine_spec(dialect), job, CREDS)
    env = dict(os.environ, TRACKLISTER_FAKE_NETWORK=str(net))
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
    return p, work, manifest


def index_rows(work):
    text = (work / "index.csv").read_text(encoding="utf-8")
    return list(csv.DictReader(text.splitlines()))


def test_fake_correcto_sockseek3(tmp_path):
    p, work, manifest = run_fake(tmp_path, "correcto")
    assert p.returncode == 0, p.stdout + p.stderr
    files = sorted(str(f.relative_to(work / "in")).replace("\\", "/") for f in (work / "in").rglob("*") if f.is_file())
    assert files == ["1/Fjaak - Spirit.flac", "2/Chris Liebing - Higher Things (FJAAK Remix).flac"]
    assert not (work / "in" / ".sockseek-staging").exists() or not any((work / "in" / ".sockseek-staging").iterdir())
    idx = index_rows(work)
    assert idx[0]["filepath"] == "./in/1/Fjaak - Spirit.flac" and idx[0]["state"] == "1"
    assert "[003] SongJob: searching: Fjaak - Spirit" in p.stdout
    assert "[003] SongJob: succeeded: Fjaak - Spirit: peerA\\..\\" in p.stdout
    assert "[cli] Completed: 2 succeeded, 0 failed." in p.stdout
    assert "Logging in as usuario-prueba.." in p.stdout       # the real engine prints the user too
    assert "clave-prueba" not in p.stdout + (work / "engine.log").read_text(encoding="utf-8")
    m3u = (work / "playlist.m3u").read_text(encoding="utf-8").splitlines()
    assert m3u[0] == os.path.join("in", "1", "Fjaak - Spirit.flac")      # the OS separator, like Sockseek


def test_fake_sin_resultados_both_dialects(tmp_path):
    p3, w3, _ = run_fake(tmp_path / "a", "sin_resultados")
    assert p3.returncode == 1
    assert "failed [No search results]: Nadie Conocido - Tema Inexistente" in p3.stdout
    assert index_rows(w3)[0]["state"] == "2" and index_rows(w3)[0]["failurereason"] == "9"
    assert "#FAIL: Nadie Conocido - Tema Inexistente [NoSearchResults]" in (w3 / "playlist.m3u").read_text(encoding="utf-8")
    p2, w2, _ = run_fake(tmp_path / "b", "sin_resultados", EngineDialect.SLDL2)
    assert p2.returncode == 0                                   # 2.x exits 0 even when items fail
    assert "Not found: Nadie Conocido - Tema Inexistente" in p2.stdout
    assert index_rows(w2)[0]["failurereason"] == "3"


def test_fake_sldl2_paths_and_lines(tmp_path):
    p, work, _ = run_fake(tmp_path, "correcto", EngineDialect.SLDL2)
    assert p.returncode == 0
    assert "Login usuario-prueba" in p.stdout and "Searching: Fjaak - Spirit (30s)" in p.stdout
    assert any(line.startswith("Succeeded:") for line in p.stdout.splitlines())
    assert index_rows(work)[0]["filepath"] == "./" + os.path.join("in", "1", "Fjaak - Spirit.flac")   # like sldl


# What the REAL engines write, captured on Windows (tests/fixtures/engine/mock-run), and what they write on Unix.
# Sockseek 3.0.5, Sockseek.Core/Files/M3uEditor.cs: the index path is "./" + Path.GetRelativePath(...) with
# every '\' replaced by '/' (WriteSockseekLine), the playlist line is Path.GetRelativePath(...) as it is
# (SongToLine); sldl 2.6.0 writes both as they are (ENGINE-FACTS.md section 2). .NET's Path uses '\' on
# Windows and '/' on Unix, so on macOS every one of them has '/'.
MOCK = Path(__file__).parents[1] / "fixtures" / "engine" / "mock-run"


def _captured(eid: str, name: str) -> str:
    """The first line for 'in/1/Fjaak - Spirit.flac' that the real engine wrote on Windows."""
    lines = (MOCK / eid / name).read_text(encoding="utf-8").splitlines()
    return next(ln.split(",")[0] for ln in lines if "Fjaak - Spirit.flac" in ln)


@pytest.mark.parametrize("dialect,eid", [(EngineDialect.SOCKSEEK3, "sockseek-3.0.5"),
                                         (EngineDialect.SLDL2, "sldl-2.6.0")])
def test_the_fake_writes_the_separators_the_real_engine_writes_on_this_os(tmp_path, dialect, eid):
    on_windows = {"index": _captured(eid, "index.csv"), "playlist": _captured(eid, "playlist.m3u")}
    assert on_windows == {"index": "./in/1/Fjaak - Spirit.flac" if dialect == EngineDialect.SOCKSEEK3
                          else "./in\\1\\Fjaak - Spirit.flac", "playlist": "in\\1\\Fjaak - Spirit.flac"}
    here = {k: v.replace("\\", os.sep) for k, v in on_windows.items()}     # what it writes on this OS
    p, work, _ = run_fake(tmp_path, "correcto", dialect)
    assert p.returncode == 0, p.stdout + p.stderr
    assert index_rows(work)[0]["filepath"] == here["index"]
    assert (work / "playlist.m3u").read_text(encoding="utf-8").splitlines()[0] == here["playlist"]
    if os.sep == "/":
        assert "\\" not in here["index"] + here["playlist"]


def test_fake_peer_timeout_and_ban(tmp_path):
    p, work, _ = run_fake(tmp_path / "t", "peer_timeout")
    assert p.returncode == 1 and "failed [All downloads failed]" in p.stdout
    assert not list((work / "in").rglob("*.flac"))
    b, bw, _ = run_fake(tmp_path / "b", "ban")
    assert b.returncode == 1 and "kicked" in b.stdout
    assert [r["state"] for r in index_rows(bw)] == ["1"]        # only the first search happened


def test_fake_filters_length_bitrate_strict(tmp_path):
    # radio edit: length not announced -> the engine cannot filter it and downloads it
    p, work, _ = run_fake(tmp_path / "r", "radio_edit")
    assert p.returncode == 0 and list((work / "in" / "1").glob("*.flac"))
    # mp3 with unknown bitrate passes --min-bitrate 320 in the search (Addendum 6)
    m, mw, _ = run_fake(tmp_path / "m", "mp3_256", preset="solo_mp3_320")
    assert m.returncode == 0 and list((mw / "in" / "1").glob("*.mp3"))
    # lossless pass never takes an .mp3
    n, nw, _ = run_fake(tmp_path / "n", "mp3_256", preset="lossless")
    assert n.returncode == 1 and not list((nw / "in").rglob("*.mp3"))


def test_fake_respects_banned_users(tmp_path):
    """Like both engines: a banned peer's files are never candidates (first passing candidate wins)."""
    p, work, _ = run_fake(tmp_path / "a", "version_equivocada")
    assert [f.name for f in (work / "in" / "1").iterdir()] == ["Fjaak - Spirit (Kai Van Dongen Remix).flac"]
    b, bw, _ = run_fake(tmp_path / "b", "version_equivocada", banned_users=("peerA",))
    assert b.returncode == 0 and [f.name for f in (bw / "in" / "1").iterdir()] == ["Fjaak - Spirit.flac"]
    assert "peerB\\" in b.stdout and "peerA\\" not in b.stdout
    c, cw, _ = run_fake(tmp_path / "c", "version_equivocada", EngineDialect.SLDL2, banned_users=("peerA", "peerB"))
    assert c.returncode == 0 and not list((cw / "in").rglob("*.flac")) and "Not found: Fjaak - Spirit" in c.stdout


def _r4_run(tmp_path, rows, files, *, clean, desperate=False, short_flag=False, ban_after=None):
    from tests.fakes.scenarios import file as mkfile
    net = {"schema": "tracklister.fakenet/1", "search_delay_ms": 0, "ban_after_searches": ban_after, "peers": {},
           "files": [mkfile(*f) for f in files], "engine_query_clean": clean}
    tmp_path.mkdir(parents=True, exist_ok=True)
    netp = tmp_path / "net.json"
    netp.write_text(json.dumps(net), encoding="utf-8")
    work = tmp_path / "w"
    manifest = write_engine_csv(rows, work / "input.csv")
    job = EngineJob(work, build_preset("lossless").passes[0], any(m.length for m in manifest), 49998,
                    desperate=desperate and not short_flag)
    argv = build_command(fake_engine_spec(), job, CREDS) + (["-d"] if short_flag else [])
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=120,
                       env=dict(os.environ, TRACKLISTER_FAKE_NETWORK=str(netp)))
    got = sorted(f.name for f in (work / "in").rglob("*") if f.is_file()) if (work / "in").exists() else []
    return p, got


def test_r4_v100_scenarios_keep_their_word_rules_without_the_network_key(tmp_path):
    """Without engine_query_clean the fake splits every query on '.' as in v1.0, so the older scenarios
    behave as before; with it, the dotted query finds only files that carry the dot."""
    from tests.fakes.scenarios import row
    rows = [row(1, "Vkn.modular", "Hidden Reason", dur=20)]
    files = [("peerB", "@@m\\Musica\\VKN Modular - Hidden Reason.flac", "", "", 20)]
    _, old = _r4_run(tmp_path / "a", rows, files, clean=False)
    _, new = _r4_run(tmp_path / "b", rows, files, clean=True)
    assert old == ["VKN Modular - Hidden Reason.flac"] and new == []
    dotted = [("peerB", "@@m\\Musica\\Vkn.modular - Hidden Reason.flac", "", "", 20)]
    _, found = _r4_run(tmp_path / "c", rows, dotted, clean=True)
    assert found == ["Vkn.modular - Hidden Reason.flac"]


def test_r4_desperate_short_flag_and_its_searches_count_for_the_ban(tmp_path):
    from tests.fakes.scenarios import row
    rows = [row(1, "Red Rooms", "Trip", dur=20), row(2, "Phil Berg", "Seiko", dur=30)]
    files = [("peerD", "@@m\\Musica\\Red Rooms - Trip.flac", "", "", 26),
             ("peerE", "@@m\\Musica\\Phil Berg - Seiko.flac", "", "", 30)]
    p, got = _r4_run(tmp_path / "a", rows, files, clean=True, short_flag=True)
    assert p.returncode == 0 and got == ["Phil Berg - Seiko.flac", "Red Rooms - Trip.flac"]
    _, plain = _r4_run(tmp_path / "b", rows, files, clean=True)
    assert plain == ["Phil Berg - Seiko.flac"]                  # 6 s off: only --desperate finds it
    # the first row needs 2 searches (base + without the length condition): a ban after 2 stops the second
    b, banned = _r4_run(tmp_path / "c", rows, files, clean=True, desperate=True, ban_after=2)
    assert b.returncode == 1 and "kicked" in b.stdout and banned == ["Red Rooms - Trip.flac"]


def test_fake_print_json_all_downloads_nothing(tmp_path):
    p, work, _ = run_fake(tmp_path, "correcto", print_json_all=True,
                          input_override="artist=Fjaak, title=Spirit, length=30")
    assert p.returncode == 0
    arr = json.loads([line for line in p.stdout.splitlines() if line.startswith("[")][-1])
    assert arr[0]["User"]["Username"] == "peerA" and arr[0]["File"]["Length"] == 30
    assert not (work / "in").exists() or not list((work / "in").rglob("*.flac"))


def test_fake_rejects_unknown_flags_and_needs_no_config(tmp_path):
    base = [sys.executable, str(FAKE)]
    r = subprocess.run(base + ["x.csv", "--no-config", "--user", "u", "--pass", "p", "--output-dir", "o",
                               "--strict-conditions"], capture_output=True, text=True)
    assert r.returncode == 2 and "Unknown argument" in r.stdout
    r2 = subprocess.run(base + ["x.csv", "--no-config", "--user", "u", "--pass", "p", "-p", "o",
                                "--concurrent-jobs", "4"], capture_output=True, text=True)
    assert r2.returncode == 1 and "Unknown argument" in r2.stdout
    r3 = subprocess.run(base + ["x.csv", "--user", "u", "--pass", "p", "--output-dir", "o"],
                        capture_output=True, text=True)
    assert r3.returncode == 2


def test_fake_help_and_version():
    h = subprocess.run([sys.executable, str(FAKE), "--help"], capture_output=True, text=True, encoding="utf-8")
    assert h.returncode == 0 and "--output-dir <path>" in h.stdout
    v = subprocess.run([sys.executable, str(FAKE), "--version"], capture_output=True, text=True)
    assert v.stdout.strip() == "3.0.5"


def test_fake_never_imports_sockets_or_app_code():
    import re
    for f in (FAKE, FAKE.parent / "synth.py"):
        for line in f.read_text(encoding="utf-8").splitlines():
            assert not re.match(r"\s*(import|from)\s+(socket|requests|urllib|http|tracklister)\b", line), line


@pytest.mark.parametrize("name", SCENARIOS)
def test_every_scenario_builds(tmp_path, name):
    rows, net = build_scenario(name, tmp_path)
    data = json.loads(net.read_text(encoding="utf-8"))
    assert data["schema"] == "tracklister.fakenet/1" and rows
    assert [r.pos for r in rows] == list(range(1, len(rows) + 1))
