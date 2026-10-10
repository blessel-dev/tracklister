"""1.0.1 acceptance (R3, R6) with the fake engine: his set's tracks served with the file names of his
Diagnóstico and report (folders invented, no tags) and the spectral cuts his report measured.

SPDX-License-Identifier: GPL-3.0-or-later

Run with -s to print the outcome table (it goes to test-report.md).
"""
from __future__ import annotations

import threading

from tests.fakes.scenarios import CASA_V101, build_scenario
from tracklister.core.model import ResultState, SourceRef
from tracklister.core.paths import app_paths
from tracklister.core.settings import Settings
from tracklister.engine.credentials import Credentials
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.runner import EngineRunner
from tracklister.engine.spec import fake_engine_spec
from tracklister.library.index import LibraryIndex
from tracklister.pipeline.session import SetSession

CREDS = Credentials("usuario-prueba", "clave-prueba")


def test_v101_acceptance_his_file_names_and_cuts(tmp_path):
    rows, net = build_scenario("casa_v101", tmp_path / "net")
    paths = app_paths().ensure()
    settings = Settings(preset_id="lossless", library_root=str(tmp_path / "biblioteca"))
    s = SetSession.create("Set casa 1.0.1", rows, [SourceRef("texto", "comentario.txt")], settings,
                          tmp_path / "biblioteca", paths)
    runner = EngineRunner(fake_engine_spec(), SearchBudget(paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    s.run(runner, CREDS, lambda e: None, threading.Event(), lambda r: set())
    s.finalize(LibraryIndex(paths.library_file))
    print()
    got = {}
    for pos, artist, title, version, path, lowpass, want in CASA_V101:
        res = s.doc.results[next(r.uid for r in s.doc.rows if r.pos == pos)]
        got[pos] = str(res.state)
        cut = "-" if res.spectral_cutoff_hz is None else f"{res.spectral_cutoff_hz / 1000:.2f}"
        print(f"| {pos:02d} | {artist} - {title}{f' ({version})' if version else ''} | {path.split(chr(92))[-1]} "
              f"| {cut} | {res.state} | {res.score} | {res.file or ''} |")
    assert got == {pos: want for pos, *_, want in CASA_V101}
    by = {r.pos: s.doc.results[r.uid] for r in s.doc.rows}
    for pos in (1, 2, 3, 5, 7, 9, 13):
        assert by[pos].file.startswith(f"{pos:02d} - ") and "sin_tags" in by[pos].flags, pos
    for pos in (4, 10):                                    # 18.75 and 16.25 kHz: the strong mark, in the set
        assert by[pos].flags[-1] == "probable_mp3_convertido" and not by[pos].file.startswith("_dudosos")
    for pos in (6, 8, 11, 12):                             # 20.5 / 20.25 / 20.25 / 19.75 kHz: one neutral line
        assert by[pos].score == 100 and "probable_mp3_convertido" not in by[pos].flags
        assert any(x.startswith("Corte a ") and "no se puede saber solo con el espectro" in x for x in by[pos].reasons)
    for pos in (14, 15):
        assert by[pos].file.startswith("_dudosos/") and by[pos].score < 50
    rep = (s.set_dir / "Informe - Set casa 1.0.1.txt").read_text(encoding="utf-8")
    assert rep.split("\n")[5] == "Resumen: verificado 11, verificado \u00b7 revisar calidad 2, dudoso 2"
    assert "scúchalo" not in rep
