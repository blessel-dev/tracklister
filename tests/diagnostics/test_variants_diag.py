"""Addendum 5 (R4): the Diagnóstico tries the same spellings as the download for a row with no results.

SPDX-License-Identifier: GPL-3.0-or-later

Fake engine with "engine_query_clean": true (the real engines' query cleaning, notes v101-c 1.2) and his
three rows of 10 Oct: as written they find nothing; 'Vkn modular' (variant 1), 'Jeroen Search' and 'TR-440'
(variant 2) find their files. No --desperate in the Diagnóstico; the report says «Reintentar fallos» runs it.
Also plan D10 / notes v101-b 1.2: a folder named like the artist only counts when the name gives no artist.
"""
from __future__ import annotations

import json

import pytest

from tests.fakes.scenarios import build_scenario, row
from tracklister.core.paths import app_paths
from tracklister.core.settings import Settings
from tracklister.diagnostics.redact import Redactor
from tracklister.diagnostics.report import DEEP_SEARCH_ES, build_report
from tracklister.diagnostics.run import NO_RESULTS_ES, judge_candidate, run_diagnostic
from tracklister.engine.credentials import Credentials
from tracklister.engine.presets import build_preset
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.runner import EngineRunner
from tracklister.engine.spec import fake_engine_spec

CREDS = Credentials("usuario-prueba", "clave-prueba")


def _diag(tmp_path, extra_rows=()):
    rows, net = build_scenario("variantes_r4", tmp_path / "net")
    rows = rows[:3] + list(extra_rows)
    paths = app_paths().ensure()
    budget = SearchBudget(paths.search_budget_file)
    runner = EngineRunner(fake_engine_spec(), budget, env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    diag = run_diagnostic(rows, runner, CREDS, paths=paths, settings=Settings(), max_rows=5)
    return diag, paths, json.loads(paths.search_budget_file.read_text(encoding="utf-8"))


def test_a5_his_three_rows_are_found_by_the_spellings_the_download_tries(tmp_path):
    diag, paths, budget = _diag(tmp_path)
    by = {d.row.pos: d for d in diag}
    assert by[1].found_by == "Jeroen Search - Inject"
    assert by[1].tried == ["Komplex aka Jeroen Search - Inject", "Komplex - Inject"]
    assert by[2].found_by == "Vkn modular - Hidden Reason" and by[2].tried == ["Vkn.modular - Hidden Reason"]
    assert by[3].found_by == "TR-440 - Somewhen" and by[3].tried == ["TR440 - Somewhen", "TR 440 - Somewhen"]
    for d in diag:
        assert d.error_es is None and d.candidates and d.candidates[0].accepted       # judged against the ROW
        assert d.candidates[0].why_es.startswith("elegido")
    # one search per process, all inside the app-wide budget (no --desperate): row 1 three spellings, row 2
    # two, row 3 three
    assert len(budget["events"]) == 3 + 2 + 3
    text = build_report(diag, app_version="1.0.1", engine_id="sockseek-3.0.5", windows_version="W",
                        listen_port=49998, redactor=Redactor(secrets=[CREDS.username, CREDS.password]))
    assert ("    Encontrado buscando «Jeroen Search - Inject» (sin resultados buscando "
            "«Komplex aka Jeroen Search - Inject»).") in text
    assert "Encontrado buscando «Vkn modular - Hidden Reason»" in text
    assert "Encontrado buscando «TR-440 - Somewhen»" in text
    assert "con resultados: 3; con un candidato válido: 3; sin resultados o con error: 0" in text
    assert "--desperate" not in text and DEEP_SEARCH_ES not in text
    for secret in ("usuario-prueba", "clave-prueba", "peerA", "peerB", "peerC"):
        assert secret not in text
    assert "peer-1" in text                                           # pseudonyms in the peer column only


def test_a5_a_row_nothing_finds_lists_its_spellings_and_the_deep_search(tmp_path):
    diag, _, _ = _diag(tmp_path, extra_rows=[row(4, "TR808", "Nada En Ningun Sitio", dur=20),
                                             row(5, "Nadie Conocido", "Tema Inexistente", dur=20)])
    by = {d.row.pos: d for d in diag}
    assert by[4].candidates == [] and by[4].error_es == NO_RESULTS_ES and by[4].found_by is None
    assert by[4].tried == ["TR808 - Nada En Ningun Sitio", "TR 808 - Nada En Ningun Sitio",
                           "TR-808 - Nada En Ningun Sitio"]
    assert by[5].tried == ["Nadie Conocido - Tema Inexistente"]         # no other spelling: one search only
    text = build_report(diag, app_version="1.0.1", engine_id="sockseek-3.0.5", windows_version="W",
                        listen_port=49998, redactor=Redactor(secrets=[CREDS.username]))
    block4 = text.split("04. TR808 - Nada En Ningun Sitio")[1].split("05. ")[0]
    assert "! " + NO_RESULTS_ES in block4
    assert "También se buscó como «TR 808 - Nada En Ningun Sitio» y «TR-808 - Nada En Ningun Sitio», sin " \
           "resultados." in block4
    assert DEEP_SEARCH_ES in block4
    block5 = text.split("05. Nadie Conocido - Tema Inexistente")[1]
    assert "También se buscó" not in block5.split("\n\n")[0] and DEEP_SEARCH_ES in block5


@pytest.mark.parametrize("path, want_ok", [
    ("Musica\\Fjaak\\Live\\03 Spirit.flac", True),               # the name gives no artist: the folder counts
    ("Musica\\Adam Beyer\\Adam Port - Spirit.flac", False),      # the name says Adam Port: the folder does not
])
def test_d10_the_folder_counts_only_when_the_name_gives_no_artist(path, want_ok):
    fmt = build_preset("lossless").passes[0]
    who = "Fjaak" if "Fjaak" in path else "Adam Beyer"
    score, ok, why = judge_candidate(row(1, who, "Spirit", dur=30), fmt, path, 30, None)
    assert ok is want_ok, why
