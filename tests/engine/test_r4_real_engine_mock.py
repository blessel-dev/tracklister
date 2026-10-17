"""1.0.1, R4, against what the REAL pinned engines did in MOCK mode (no network; see
tests/fixtures/engine/mock_probe/probe_r4_variants.py and ENGINE-FACTS.md "Search variants and --desperate").

His three no-result rows (Komplex aka Jeroen Search, Vkn.modular, TR440), plus a file 6 s longer than its
row and a row whose title another artist also has:

- as written, the engines find none of them;
- the search variants find them: 'Vkn modular' (variant 1), 'Jeroen Search' and 'TR-440' (variant 2);
  'TR 440' does not pass --strict-artist for a 'TR-440' file, which is why both spellings are tried;
- --desperate alone finds only the file 6 s off (the search without the length condition), and never gives
  'Nobody Real' the 'Trip' of Red Rooms: its title-only and artist-only searches keep the strict artist.

The same runs on the FAKE engine (network key engine_query_clean) must give the same files.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import subprocess
from pathlib import Path, PureWindowsPath

import pytest

from tests.fakes.scenarios import file
from tracklister.engine.cli import EngineJob, build_command, redact_argv
from tracklister.engine.credentials import Credentials
from tracklister.engine.csvwriter import write_engine_csv
from tracklister.engine.presets import build_preset, relaxed
from tracklister.engine.spec import EngineDialect, EngineSpec, engine_pins, fake_engine_spec

FIX = Path(__file__).parents[1] / "fixtures" / "engine"
# the recorded runs are of both Windows engines; on POSIX the C:\ paths become C:/, so '\' -> '/' on both sides
PINS = engine_pins("win32")
_spec = importlib.util.spec_from_file_location("probe_r4_variants", FIX / "mock_probe" / "probe_r4_variants.py")
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

CREDS = Credentials("usuario-prueba", "clave-prueba")
# run -> files downloaded (in/<snum>/<name>), the same for both engines
EXPECTED = {
    "1-base": [],
    "2-variante-1": ["in/2/VKN Modular - Hidden Reason.flac"],
    "3-variante-2": ["in/1/Jeroen Search - Inject.flac", "in/2/TR-440 - Somewhen.flac"],
    "4-desesperado": ["in/4/Red Rooms - Trip.flac"],
}


def _job(work: Path, run: str) -> EngineJob:
    _, _, relax, desperate = probe.RUNS[run]
    fmt = build_preset("lossless").passes[0]
    return EngineJob(work_dir=work, fmt=relaxed(fmt) if relax else fmt, has_lengths=True, listen_port=49998,
                     concurrent=2, desperate=desperate)


@pytest.mark.parametrize("eid", list(PINS))
@pytest.mark.parametrize("run", list(EXPECTED))
def test_real_engine_outcomes_in_mock_mode(eid, run):
    d = FIX / "mock-run-r4" / eid / run
    tree = [x for x in d.joinpath("tree.txt").read_text(encoding="utf-8").splitlines() if x]
    assert tree == EXPECTED[run]
    # the argv the real binary ran is exactly the adapter's (plus the mock-mode options)
    lines = d.joinpath("argv.txt").read_text(encoding="utf-8").splitlines()
    ran = lines[:lines.index("--mock-files-dir")]
    pin = PINS[eid]
    mine = redact_argv(build_command(EngineSpec(eid, pin.dialect, ("x.exe",)),
                                     _job(Path(PureWindowsPath(rf"C:\T\w\{run}")), run), CREDS)[1:])
    assert [t.replace("<TMP>", r"C:\T").replace("\\", "/") for t in ran] == [t.replace("\\", "/") for t in mine]
    assert ("--desperate" in ran) is (run == "4-desesperado")
    out = d.joinpath("stdout.txt").read_text(encoding="utf-8")
    assert "Unknown argument" not in out and "Input error" not in out


def test_real_engines_say_no_search_results_also_when_the_strict_artist_refused_the_file():
    """3.x counts only the files that pass the conditions (Searcher.cs:166-173, 190): 'TR 440' got the
    'TR-440 - Somewhen' file from the mock client, refused it (--strict-artist) and says 'No search results'.
    So his «Sin resultados» rows may have been refused files, not missing ones."""
    out = (FIX / "mock-run-r4" / "sockseek-3.0.5" / "2-variante-1" / "stdout.txt").read_text(encoding="utf-8")
    assert "failed [No search results]: TR 440 - Somewhen" in out
    idx = list(csv.DictReader((FIX / "mock-run-r4" / "sockseek-3.0.5" / "2-variante-1" / "index.csv")
                              .read_text(encoding="utf-8").splitlines()))
    assert [(r["artist"], r["state"], r["failurereason"]) for r in idx] == [
        ("Komplex", "2", "9"), ("Vkn modular", "1", "0"), ("TR 440", "2", "9")]


def test_sldl2_shows_one_searching_line_per_desperate_search():
    """2.6.0 prints every search: base, without the length condition, title only, artist only. At most 7
    per item (with album and the no-diacritics twin); his rows used 2 to 4."""
    out = (FIX / "mock-run-r4" / "sldl-2.6.0" / "4-desesperado" / "stdout.txt").read_text(encoding="utf-8")
    counts = {q: out.count(f"Searching: {q}") for q in ("Komplex aka Jeroen Search - Inject", "Vkn.modular - Hidden Reason",
                                                         "TR440 - Somewhen", "Red Rooms - Trip", "Nobody Real - Trip")}
    assert counts == {"Komplex aka Jeroen Search - Inject": 4, "Vkn.modular - Hidden Reason": 4,
                      "TR440 - Somewhen": 4, "Red Rooms - Trip": 2, "Nobody Real - Trip": 3}
    base = (FIX / "mock-run-r4" / "sldl-2.6.0" / "1-base" / "stdout.txt").read_text(encoding="utf-8")
    assert base.count("Searching: ") == 5


def _fake_network(tmp_path: Path) -> Path:
    files = [file(peer, "@@m\\" + rel.replace("/", "\\"), "", "", seconds) for peer, rel, seconds in probe.MOCK_FILES]
    net = {"schema": "tracklister.fakenet/1", "search_delay_ms": 0, "ban_after_searches": None, "peers": {},
           "files": files, "engine_query_clean": True}
    p = tmp_path / "net.json"
    p.write_text(json.dumps(net, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.mark.parametrize("dialect", [EngineDialect.SOCKSEEK3, EngineDialect.SLDL2])
@pytest.mark.parametrize("run", list(EXPECTED))
def test_fake_engine_matches_the_real_engines(tmp_path, dialect, run):
    net = _fake_network(tmp_path)
    rows = {r.uid: r for r in probe.his_rows()}
    uids, queries, _, _ = probe.RUNS[run]
    work = tmp_path / "w" / run
    write_engine_csv([rows[u] for u in uids], work / "input.csv", queries=queries)
    argv = build_command(fake_engine_spec(dialect), _job(work, run), CREDS)
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=120,
                       env=dict(os.environ, TRACKLISTER_FAKE_NETWORK=str(net)))
    assert "Unknown argument" not in p.stdout, p.stdout
    got = sorted(str(f.relative_to(work)).replace("\\", "/") for f in (work / "in").rglob("*")
                 if f.is_file() and ".sockseek-staging" not in str(f))
    assert got == EXPECTED[run], p.stdout
