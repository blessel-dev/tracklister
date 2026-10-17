"""A long set name: paths well over Windows' 260-character MAX_PATH, on a PC WITHOUT long paths.

SPDX-License-Identifier: GPL-3.0-or-later

The brief's offline list asks for accents, reserved characters AND long paths end to end. Windows 10
and 11 ship with LongPathsEnabled=0, and then a path of 260 characters or more only works with the
\\\\?\\ prefix (organize.naming.win_long). Some PCs (this laptop among them) have it set to 1, where
anything works: so every test here first makes the process behave like a default PC
(tests/fakes/maxpath.py). The result no longer depends on the registry of the machine.

The layout is the real-life case of the audit: a set folder of 215 characters (a long YouTube title
under a normal library folder). The set's own .tracklister\\*.json files stay under 260; the report,
the tracklist and the longest track file go well over it.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from tests.fakes.maxpath import simulate_max_path, too_long
from tests.fakes.scenarios import build_scenario
from tests.fakes.synth import make_track
from tracklister.core.model import ResultState, SourceRef
from tracklister.core.paths import app_paths
from tracklister.core.settings import Settings
from tracklister.engine.credentials import Credentials
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.runner import EngineRunner
from tracklister.engine.spec import fake_engine_spec
from tracklister.library.index import LibraryIndex
from tracklister.organize.journal import Journal
from tracklister.organize.naming import safe_component, win_long
from tracklister.organize.reorder import apply_reorder, propose_reorder
from tracklister.pipeline.session import SetSession

pytestmark = [pytest.mark.slow,
              pytest.mark.skipif(os.name != "nt", reason="Windows MAX_PATH and the \\\\?\\ prefix (report 3.1.1)")]

CREDS = Credentials("usuario-prueba", "clave-prueba")
SET_NAME = ("Ñandú & Café: Sesión <Larga> de Prueba, en directo desde el Club de Medianoche de Valencia "
            "(vídeo completo)")
SET_DIR_LEN = 215


def _library_root(tmp_path: Path, set_dir_len: int = SET_DIR_LEN) -> Path:
    """A library folder such that <root>\\<safe set name> is exactly set_dir_len characters."""
    want = set_dir_len - 1 - len(safe_component(SET_NAME))
    base = tmp_path / "Música"
    pad = want - len(str(base)) - 1
    if pad < 4:
        pytest.skip("la carpeta temporal de pytest es demasiado larga para este caso")
    root = base / ("T" + "r" * (pad - 1))
    assert len(str(root)) == want
    return root


def test_the_guard_behaves_like_a_default_windows_pc(tmp_path, monkeypatch):
    long_file = tmp_path / ("a" * 240) / "b.txt"
    refused = simulate_max_path(monkeypatch)
    assert too_long(long_file)
    with pytest.raises(FileNotFoundError):
        long_file.write_text("x", encoding="utf-8")
    assert not os.path.isfile(long_file) and refused
    os.makedirs(win_long(long_file.parent), exist_ok=True)
    with open(win_long(long_file), "w", encoding="utf-8") as f:     # with the prefix it works
        f.write("x")
    assert os.path.isfile(win_long(long_file))


def test_long_set_name_end_to_end_without_long_path_support(tmp_path, monkeypatch):
    paths = app_paths().ensure()
    lib_root = _library_root(tmp_path)
    rows, net = build_scenario("nombres_raros", tmp_path / "net")
    settings = Settings(preset_id="lossless", library_root=str(lib_root))
    refused = simulate_max_path(monkeypatch)
    s = SetSession.create(SET_NAME, rows, [SourceRef("tabla", "raros.csv")], settings, lib_root, paths)
    runner = EngineRunner(fake_engine_spec(), SearchBudget(paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    s.run(runner, CREDS, lambda e: None, threading.Event(), lambda r: set())
    library = LibraryIndex(paths.library_file)
    s.finalize(library)

    assert len(str(s.set_dir)) == SET_DIR_LEN
    files = {r.pos: s.doc.results[r.uid].file for r in s.doc.rows}
    assert all(s.doc.results[r.uid].state == ResultState.VERIFICADO for r in s.doc.rows)
    assert files[1] == "01 - AC DC - What Live Raw.flac" and files[3] == "03 - CON - AUX.flac"
    longest = max((s.set_dir / f for f in files.values()), key=lambda p: len(str(p)))
    assert len(str(longest)) > 260 and len(longest.name) <= 180
    for f in files.values():
        assert os.path.isfile(win_long(s.set_dir / f)), f
    # the report and the tracklist sit next to the music, past 260 characters; the library has all four
    report = s.set_dir / f"Informe - {s.set_dir.name}.txt"
    tracklist = s.set_dir / f"Tracklist - {s.set_dir.name}.txt"
    assert len(str(report)) > 260 and len(str(tracklist)) > 260
    with open(win_long(report), encoding="utf-8") as fh:
        assert "verificado 4" in fh.read()
    with open(win_long(tracklist), encoding="utf-8") as fh:
        assert fh.read().startswith("01. AC/DC - What? <Live>: \"Raw\"")
    assert len(library.entries) == 4
    assert refused == []                     # nothing tried an unprefixed long path
    # a second run of the same set over the long paths changes nothing
    s2 = SetSession.create(SET_NAME, build_scenario("nombres_raros", tmp_path / "net2")[0], [], settings,
                           lib_root, paths)
    assert s2.set_dir == s.set_dir
    s2.run(runner, CREDS, lambda e: None, threading.Event(), lambda r: set())
    assert len(s2.doc.passes) == len(s.doc.passes)
    s2.finalize(library)
    assert refused == []


def test_reorder_reads_the_tags_of_files_past_260_characters(tmp_path, monkeypatch):
    """Tags first (B2): the file names say nothing, only the tags carry artist and title."""
    folder = tmp_path / "Música" / "carpeta vieja de la herramienta anterior"
    folder.mkdir(parents=True)
    rows = build_scenario("correcto", tmp_path / "net")[0]
    pad = "x" * (262 - len(str(folder)) - 12)
    names = [f"pista 1 {pad}.flac", f"pista 2 {pad}.flac"]
    for name, row in zip(names, reversed(rows)):          # the files are in the wrong order
        make_track(Path(win_long(folder / name)), fmt="flac", seconds=2.0,
                   tags={"artist": row.artist_display, "title": row.title_with_version})
    assert all(len(str(folder / n)) > 260 for n in names)
    refused = simulate_max_path(monkeypatch)
    props = propose_reorder(folder, rows)
    matched = {p.pos: p.src.name for p in props if p.status == "match"}
    assert matched == {1: names[1], 2: names[0]}
    apply_reorder(folder, props, Journal(folder))
    assert sorted(p.name for p in folder.iterdir() if p.is_file()) == [
        "01 - Fjaak - Spirit.flac", "02 - Chris Liebing - Higher Things (FJAAK Remix).flac"]
    assert refused == []
