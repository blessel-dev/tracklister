"""1.0.1 R4 wired into the set session: other spellings after each pass, the deep search in the last retry.

SPDX-License-Identifier: GPL-3.0-or-later

Fake engine only (no network), with the network key engine_query_clean (the real engines' query cleaning
and literal strict filters, notes v101-c 1.2). His three rows that found nothing on 10 Oct are found in a
normal run by their other spellings ('Vkn modular' by variant 1, 'Jeroen Search' and 'TR-440' by variant 2);
a file 6 s off only appears with «Reintentar fallos»'s deep search (--desperate) of the spelling 'TR-440'.
The row itself, its artist display and its file name never change.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from tests.fakes.scenarios import build_scenario
from tracklister.core.model import DoubtKind, ResultState, SourceRef
from tracklister.core.paths import app_paths
from tracklister.core.settings import Settings
from tracklister.engine.credentials import Credentials
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.runner import EngineRunner
from tracklister.engine.spec import fake_engine_spec
from tracklister.pipeline.session import (
    ALSO_SEARCHED_ES, DESPERATE_TRIED_ES, FOUND_AS_ES, SetSession,
)

CREDS = Credentials("usuario-prueba", "clave-prueba")


def _session(tmp_path: Path, scenario: str):
    rows, net = build_scenario(scenario, tmp_path / "net")
    paths = app_paths().ensure()
    settings = Settings(preset_id="lossless", library_root=str(tmp_path / "biblioteca"))
    s = SetSession.create("Variantes", rows, [SourceRef("tabla", "t.csv")], settings, tmp_path / "biblioteca", paths)
    # a big budget: this test is about the passes, not about waiting for the search window
    runner = EngineRunner(fake_engine_spec(), SearchBudget(paths.search_budget_file, per_time=500),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    return s, runner, net


def _res(s: SetSession, pos: int):
    return s.doc.results[next(r.uid for r in s.doc.rows if r.pos == pos)]


def _work_inputs(s: SetSession) -> list[list[str]]:
    """The Artist,Title lines each engine process was given, pass by pass."""
    out = []
    for p in s.doc.passes:
        doc = json.loads((Path(p.work_dir) / "pass.json").read_text(encoding="utf-8"))
        out.append([f"{it['artist']} - {it['title']}" for it in doc["items"]])
    return out


def test_r4_a_normal_run_finds_his_three_rows_by_their_other_spellings(tmp_path):
    s, runner, _ = _session(tmp_path, "variantes_r4")
    events = []
    s.run(runner, CREDS, events.append, threading.Event(), lambda rows: set())
    assert [_res(s, p).state for p in (1, 2, 3, 4)] == [ResultState.VERIFICADO] * 4
    # one process as written, then variant 1 of the 3 rows not found, then variant 2 of the 2 still missing
    assert _work_inputs(s) == [
        ["Komplex aka Jeroen Search - Inject", "Vkn.modular - Hidden Reason", "TR440 - Somewhen", "Red Rooms - Trip"],
        ["Komplex - Inject", "Vkn modular - Hidden Reason", "TR 440 - Somewhen"],
        ["Jeroen Search - Inject", "TR-440 - Somewhen"],
    ]
    assert [p.name for p in s.doc.passes] == ["lossless", "lossless-variante", "lossless-variante"]
    labels = [e.message_es for e in events if e.kind == "pass_started"]
    assert labels[1].startswith("Pasada 2: lossless (variante 1)") and "(variante 2)" in labels[2]
    assert FOUND_AS_ES.format(query="Vkn modular - Hidden Reason") in _res(s, 2).reasons
    assert FOUND_AS_ES.format(query="Jeroen Search - Inject") in _res(s, 1).reasons
    assert FOUND_AS_ES.format(query="TR-440 - Somewhen") in _res(s, 3).reasons
    assert not any("Encontrado buscando" in x for x in _res(s, 4).reasons)       # found as written
    # the files keep the row's own names
    assert _res(s, 1).file == "01 - Komplex aka Jeroen Search - Inject.flac"
    assert _res(s, 2).file == "02 - Vkn.modular - Hidden Reason.flac"
    assert _res(s, 3).file == "03 - TR440 - Somewhen.flac"


def test_r4_the_deep_search_runs_only_in_the_retry_and_with_each_spelling(tmp_path):
    s, runner, _ = _session(tmp_path, "variantes_r4_a_fondo")
    s.run(runner, CREDS, lambda e: None, threading.Event(), lambda rows: set())
    r3 = _res(s, 3)
    assert r3.state == ResultState.NO_ENCONTRADO
    assert ALSO_SEARCHED_ES.format(queries="«TR 440 - Somewhen» y «TR-440 - Somewhen»") in r3.reasons
    assert not any(".a-fondo" in p.name or "a-fondo" in p.name for p in s.doc.passes)      # never in a normal run
    n = len(s.doc.passes)
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    new = s.doc.passes[n:]
    assert [p.name for p in new] == ["lossless-relajada", "lossless-relajada-variante", "lossless-relajada-variante",
                                     "lossless-relajada-a-fondo", "lossless-relajada-a-fondo-variante",
                                     "lossless-relajada-a-fondo-variante"]
    assert _work_inputs(s)[n:] == [["TR440 - Somewhen"], ["TR 440 - Somewhen"], ["TR-440 - Somewhen"],
                                   ["TR440 - Somewhen"], ["TR 440 - Somewhen"], ["TR-440 - Somewhen"]]
    # only the deep search without the length condition, spelled 'TR-440', brings the 26 s file; the
    # verification then judges the 6 s difference as always (inside its "revisar" band, the identity is 100)
    r3 = _res(s, 3)
    assert r3.state == ResultState.VERIFICADO and r3.doubt is None and r3.file == "03 - TR440 - Somewhen.flac"
    assert round(r3.duration_s) == 26
    assert FOUND_AS_ES.format(query="TR-440 - Somewhen") in r3.reasons
    assert DESPERATE_TRIED_ES not in r3.reasons
    # the other rows were already verified: a retry never touches them
    assert [_res(s, p).state for p in (1, 2, 4)] == [ResultState.VERIFICADO] * 3


def test_r4_a_row_that_nothing_finds_says_what_was_tried(tmp_path):
    s, runner, net = _session(tmp_path, "variantes_r4_a_fondo")
    data = json.loads(net.read_text(encoding="utf-8"))
    data["files"] = [f for f in data["files"] if "TR-440" not in f["path"]]
    net.write_text(json.dumps(data), encoding="utf-8")
    s.run(runner, CREDS, lambda e: None, threading.Event(), lambda rows: set())
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    r3 = _res(s, 3)
    assert r3.state == ResultState.NO_ENCONTRADO
    assert r3.reasons[0].startswith("Soulseek no devolvió ningún resultado")
    assert ALSO_SEARCHED_ES.format(queries="«TR 440 - Somewhen» y «TR-440 - Somewhen»") in r3.reasons
    assert r3.reasons[-1] == DESPERATE_TRIED_ES


def test_r4_variants_never_run_for_failed_or_kept_rows(tmp_path):
    """Only «no encontrado» is a spelling problem: a failed download is not searched with another spelling."""
    s, runner, net = _session(tmp_path, "variantes_r4")
    data = json.loads(net.read_text(encoding="utf-8"))
    data["peers"] = {"peerD": {"timeout": True}}       # Red Rooms - Trip: found, but the download fails
    data["files"] = [f for f in data["files"] if f["peer"] == "peerD"]
    net.write_text(json.dumps(data), encoding="utf-8")
    s.run(runner, CREDS, lambda e: None, threading.Event(), lambda rows: set())
    assert _res(s, 4).state == ResultState.FALLIDA
    inputs = _work_inputs(s)
    assert all("Red Rooms - Trip" not in batch for batch in inputs[1:])
