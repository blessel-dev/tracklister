"""Diagnostico against the FAKE engine: search-only by default, redacted report.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import json
import re

from tests.fakes.scenarios import build_scenario, file
from tracklister.core.paths import app_paths
from tracklister.core.settings import Settings
from tracklister.diagnostics.redact import Redactor
from tracklister.diagnostics.report import SELF_CHECK, build_report
from tracklister.diagnostics.run import keyed_input, run_diagnostic
from tracklister.engine.credentials import Credentials
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.runner import EngineRunner
from tracklister.engine.spec import fake_engine_spec

CREDS = Credentials("usuario-prueba", "clave-prueba")


def _setup(tmp_path):
    rows, net = build_scenario("correcto", tmp_path / "net")
    data = json.loads(net.read_text(encoding="utf-8"))
    # a second, worse candidate for row 1 (another version) and one from a peer named like a person
    data["files"].insert(0, file("maria.lopez", "@@m\\Fjaak\\Fjaak - Spirit (Kai Remix).flac", "Fjaak",
                                 "Spirit (Kai Remix)", 30))
    net.write_text(json.dumps(data), encoding="utf-8")
    paths = app_paths().ensure()
    runner = EngineRunner(fake_engine_spec(), SearchBudget(paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    return rows, runner, paths


def test_keyed_input(tmp_path):
    rows, _ = build_scenario("correcto", tmp_path)
    assert keyed_input(rows[1]) == "artist=Chris Liebing, title=Higher Things (FJAAK Remix), length=32"


def test_search_only_candidates_and_report(tmp_path):
    rows, runner, paths = _setup(tmp_path)
    diag = run_diagnostic(rows, runner, CREDS, paths=paths, settings=Settings())
    assert len(diag) == 2 and all(d.error_es is None for d in diag)
    c1 = diag[0].candidates
    assert [c.peer for c in c1] == ["maria.lopez", "peerA"]
    assert not c1[0].accepted and "otra versión" in c1[0].why_es
    assert c1[1].accepted and c1[1].why_es.startswith("elegido")
    assert not list((paths.work_dir / "diagnostico").rglob("*.flac"))      # nothing downloaded
    red = Redactor(secrets=[CREDS.username, CREDS.password], own_ips=["83.45.1.200"])
    text = build_report(diag, app_version="1.0.0", engine_id="sockseek-3.0.5", windows_version="Windows 10.0.19045",
                        listen_port=49998, redactor=red)
    for secret in ("usuario-prueba", "clave-prueba", "maria.lopez", "peerA", "peerB", "83.45.1.200"):
        assert secret not in text
    assert "peer-1" in text and "peer-2" in text and text.rstrip().endswith(SELF_CHECK)
    assert re.search(r"01\. Fjaak - Spirit", text) and "Puerto de escucha: 49998" in text


def test_no_results_explains_the_network(tmp_path):
    rows, net = build_scenario("sin_resultados", tmp_path / "net")
    paths = app_paths().ensure()
    runner = EngineRunner(fake_engine_spec(), SearchBudget(paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    diag = run_diagnostic(rows, runner, CREDS, paths=paths)
    assert diag[0].candidates == [] and "Sin resultados" in diag[0].error_es
    text = build_report(diag, app_version="1.0.0", engine_id="fake", windows_version="W", listen_port=50000,
                        redactor=Redactor(secrets=[CREDS.username]))
    assert "Abre el puerto TCP 50000" in text and "Firewall" in text


def test_download_only_when_opted_in(tmp_path):
    rows, runner, paths = _setup(tmp_path)
    diag = run_diagnostic(rows, runner, CREDS, download=True, max_rows=1, paths=paths, settings=Settings())
    # like the real engine, the fake takes the FIRST candidate that passes its filters (the remix);
    # the app's verification refuses to accept it silently
    assert len(diag) == 1 and diag[0].result_es.startswith("dudoso: Otra versión")
    rows2, runner2, paths2 = _setup(tmp_path / "b")
    diag2 = run_diagnostic(rows2[1:], runner2, CREDS, download=True, max_rows=1, paths=paths2, settings=Settings())
    assert diag2[0].result_es.startswith("verificado")


def test_max_rows_default_is_five(tmp_path):
    rows, net = build_scenario("todos_los_estados", tmp_path / "net")
    paths = app_paths().ensure()
    runner = EngineRunner(fake_engine_spec(), SearchBudget(paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    diag = run_diagnostic(rows, runner, CREDS, paths=paths)
    assert [d.row.pos for d in diag] == [1, 2, 3, 4, 5]
