"""Diagnostico against the FAKE engine: search-only by default, redacted report.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import json
import re

import pytest

from tests.fakes.scenarios import build_scenario, file
from tracklister.core.paths import app_paths
from tracklister.core.settings import Settings
from tracklister.diagnostics.redact import Redactor
from tracklister.diagnostics.report import SELF_CHECK, build_report
from tracklister.diagnostics.run import judge_candidate, keyed_input, run_diagnostic
from tracklister.engine.presets import build_preset
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
    assert c1[0].score < 50                         # another version never shows a high confidence
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
    # the program that listens, and that the Windows Firewall asks about, is the engine
    assert "Permite «sockseek.exe» (el motor de descarga de Tracklister)" in text
    assert "Permite Tracklister" not in text
    text = build_report(diag, app_version="1.0.0", engine_id="sldl-2.6.0", windows_version="W", listen_port=50000,
                        redactor=Redactor(secrets=[CREDS.username]))
    assert "Permite «sldl.exe»" in text


def test_r2_n2_keyed_strings_survive_commas(tmp_path):
    """Audit round 2, N2. Both engines split the keyed string on every ',' and glue a value back with
    ','; only a piece that reads '<key>=' starts a new property (tests/fakes/fake_engine.parse_keyed is
    a port of that parser). Such commas are escaped as a space, every other comma is kept."""
    from tests.fakes.fake_engine import parse_keyed
    from tests.fakes.scenarios import row
    cases = [row(1, "Earth, Wind & Fire", "September", dur=215, artists=["Earth, Wind & Fire"]),
             row(2, "Comma, Artist", "Say, Hi", dur=10, artists=["Comma, Artist"]),
             row(3, "Truco", "Hey, title=Otra Cosa", version="Live, length=1 Edit", dur=300),
             row(4, "A, artist=B", "Tema, album=X, Y", artists=["A, artist=B"])]
    expect = {1: ("Earth, Wind & Fire", "September", "215"), 2: ("Comma, Artist", "Say, Hi", "10"),
              3: ("Truco", "Hey  title=Otra Cosa (Live  length=1 Edit)", "300"),
              4: ("A  artist=B", "Tema  album=X, Y", None)}
    for r in cases:
        props = parse_keyed(keyed_input(r))
        assert set(props) <= {"artist", "title", "length"}, props
        assert (props["artist"], props["title"], props.get("length")) == expect[r.pos]
    assert keyed_input(cases[0]) == "artist=Earth, Wind & Fire, title=September, length=215"   # kept as is
    assert keyed_input(cases[1]) == "artist=Comma, Artist, title=Say, Hi, length=10"
    # end to end with the fake engine, which parses like the real ones
    _, net = build_scenario("sin_resultados", tmp_path / "net")
    data = json.loads(net.read_text(encoding="utf-8"))
    data["files"] = [file("peerA", "@@x\\Comma, Artist\\Comma, Artist - Say, Hi.flac", "Comma, Artist",
                          "Say, Hi", 10)]
    net.write_text(json.dumps(data), encoding="utf-8")
    paths = app_paths().ensure()
    runner = EngineRunner(fake_engine_spec(), SearchBudget(paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    diag = run_diagnostic([cases[1]], runner, CREDS, paths=paths, settings=Settings())
    assert [c.accepted for c in diag[0].candidates] == [True] and diag[0].error_es is None


NAMESAKES = [("Adam Beyer", "Adam Port"), ("Chris Liebing", "Chris Lake"), ("Len Faki", "Ken Faki")]


@pytest.mark.parametrize("dur", [30, None])
@pytest.mark.parametrize("want,got", NAMESAKES)
def test_r3_b1_diagnostic_rejects_an_artist_with_a_similar_name(want, got, dur):
    """Audit round 3, B1: the Diagnostico explains candidates with the same rule as the verification."""
    from tests.fakes.scenarios import row
    fmt = build_preset("lossless").passes[0]
    r = row(1, want, "Rush", dur=30)
    score, ok, why = judge_candidate(r, fmt, f"@@x\\Techno\\{got} - Rush.flac", dur, None)
    assert not ok and score < 50 and f"otro artista con un nombre parecido ('{got}'" in why, why
    for variant in (want.upper(), want):
        score, ok, why = judge_candidate(r, fmt, f"@@x\\Techno\\{variant} - Rush.flac", dur, None)
        assert ok and score >= 80, why


def test_r3_b1_diagnostic_end_to_end_with_a_namesake_first(tmp_path):
    _, net = build_scenario("sin_resultados", tmp_path / "net")
    data = json.loads(net.read_text(encoding="utf-8"))
    # the namesake comes first and passes the engine's filters (the folder carries the row's artist)
    data["files"] = [file("peerA", "@@x\\Adam Beyer Picks\\Adam Port - Rush.flac", "Adam Port", "Rush", 30),
                     file("peerB", "@@y\\Adam Beyer\\Adam Beyer - Rush.flac", "Adam Beyer", "Rush", 30)]
    net.write_text(json.dumps(data), encoding="utf-8")
    paths = app_paths().ensure()
    runner = EngineRunner(fake_engine_spec(), SearchBudget(paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    from tests.fakes.scenarios import row
    diag = run_diagnostic([row(1, "Adam Beyer", "Rush", dur=30)], runner, CREDS, paths=paths, settings=Settings())
    c = diag[0].candidates
    assert [x.peer for x in c] == ["peerA", "peerB"]
    assert not c[0].accepted and "otro artista con un nombre parecido" in c[0].why_es and c[0].score < 50
    assert c[1].accepted and c[1].why_es.startswith("elegido")


@pytest.mark.parametrize("dur", [30, None])
@pytest.mark.parametrize("want,got", [("Feel It", "Feel It All"), ("Higher", "Higher Love"), ("Sin", "Original Sin")])
def test_r4_b2_diagnostic_rejects_a_title_with_a_word_more_or_less(want, got, dur):
    """Audit round 4, B2: the Diagnostico judges titles with the verification's word rule."""
    from tests.fakes.scenarios import row
    fmt = build_preset("lossless").passes[0]
    r = row(1, "Amelie Lens", want, dur=30)
    score, ok, why = judge_candidate(r, fmt, f"@@x\\Techno\\Amelie Lens - {got}.flac", dur, None)
    assert not ok and score < 50 and "título distinto" in why, why
    score, ok, why = judge_candidate(r, fmt, f"@@x\\Techno\\Amelie Lens - {want}.flac", dur, None)
    assert ok and score >= 80, why


@pytest.mark.parametrize("dur", [30, None])
def test_r4_v_diagnostic_rejects_the_originals_radio_edit_for_the_remixs_radio_edit(dur):
    """Audit round 4, second review, B2: the Diagnostico judges versions group by group too."""
    from tests.fakes.scenarios import row
    from tracklister.core.textnorm import split_title_version
    fmt = build_preset("lossless").passes[0]
    base, version = split_title_version("Spirit (Kai Remix) (Radio Edit)")
    r = row(1, "Fjaak", base, version, dur=30)
    assert keyed_input(r) == "artist=Fjaak, title=Spirit (Kai Remix), length=30"
    for wrong in ("Spirit (Radio Edit)", "Spirit (Kai Remix)", "Spirit"):
        score, ok, why = judge_candidate(r, fmt, f"@@x\\Fjaak\\Fjaak - {wrong}.flac", dur, None)
        assert not ok and score < 50 and "otra versión" in why, (wrong, why)
    score, ok, why = judge_candidate(r, fmt, "@@x\\Fjaak\\Fjaak - Spirit (Kai Remix) (Radio Edit).flac", dur, None)
    assert ok and score >= 80, why


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
