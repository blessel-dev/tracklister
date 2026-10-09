"""Odd names in a deep library folder: final paths well over Windows' 260-character MAX_PATH.

SPDX-License-Identifier: GPL-3.0-or-later

The brief's offline list asks for accents, reserved characters AND long paths end to end. The
unit tests cover win_long() on its own; this runs the whole pass (fake engine -> verify -> place
-> finalize -> library) with a set folder of about 200 characters.
"""
from __future__ import annotations

import os
import threading

import pytest

from tests.fakes.scenarios import build_scenario
from tracklister.core.model import ResultState, SourceRef
from tracklister.core.paths import app_paths
from tracklister.core.settings import Settings
from tracklister.engine.credentials import Credentials
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.runner import EngineRunner
from tracklister.engine.spec import fake_engine_spec
from tracklister.library.index import LibraryIndex
from tracklister.organize.naming import win_long
from tracklister.pipeline.session import SetSession

pytestmark = pytest.mark.slow


def _deep_root(tmp_path, target_len: int = 170):
    root = tmp_path
    i = 0
    while len(str(root)) < target_len:
        root = root / f"Música {i} - carpeta con un nombre bastante largo"
        i += 1
    return root


def test_nombres_raros_in_a_deep_library_folder(tmp_path):
    paths = app_paths().ensure()
    lib_root = _deep_root(tmp_path)
    rows, net = build_scenario("nombres_raros", tmp_path / "net")
    settings = Settings(preset_id="lossless", library_root=str(lib_root))
    name = "Ñandú & Café: Sesión <Larga> de Prueba"
    s = SetSession.create(name, rows, [SourceRef("tabla", "raros.csv")], settings, lib_root, paths)
    runner = EngineRunner(fake_engine_spec(), SearchBudget(paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    s.run(runner, Credentials("usuario-prueba", "clave-prueba"), lambda e: None, threading.Event(), lambda r: set())
    library = LibraryIndex(paths.library_file)
    s.finalize(library)

    assert s.set_dir.name == "Ñandú & Café Sesión Larga de Prueba"
    files = {r.pos: s.doc.results[r.uid].file for r in s.doc.rows}
    assert all(s.doc.results[r.uid].state == ResultState.VERIFICADO for r in s.doc.rows)
    assert files[1] == "01 - AC DC - What Live Raw.flac"
    assert files[3] == "03 - CON - AUX.flac"
    longest = max((s.set_dir / f for f in files.values()), key=lambda p: len(str(p)))
    assert len(str(longest)) > 260 and len(longest.name) <= 180
    for f in files.values():
        assert os.path.isfile(win_long(s.set_dir / f)), f
    # the report and the tracklist sit next to the music; the library indexed all four
    assert os.path.isfile(win_long(s.set_dir / f"Informe - {s.set_dir.name}.txt"))
    assert os.path.isfile(win_long(s.set_dir / f"Tracklist - {s.set_dir.name}.txt"))
    assert len(library.entries) == 4
    # a second run of the same set over the long paths changes nothing
    s2 = SetSession.create(name, build_scenario("nombres_raros", tmp_path / "net2")[0], [], settings, lib_root, paths)
    assert s2.set_dir == s.set_dir
    s2.run(runner, Credentials("usuario-prueba", "clave-prueba"), lambda e: None, threading.Event(),
           lambda r: set())
    assert len(s2.doc.passes) == len(s.doc.passes)
