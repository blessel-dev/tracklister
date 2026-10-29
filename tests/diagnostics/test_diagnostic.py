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


def test_the_diagnostico_uses_the_settings_duration_bands(tmp_path):
    """CL-31 / AG-19: the Diagnóstico judged durations with fixed 3 and 10 s, the download with the settings
    duration_ok_s and duration_review_s, so with other settings the two explained the same file differently."""
    rows, net = build_scenario("correcto", tmp_path / "net")
    data = json.loads(net.read_text(encoding="utf-8"))
    # another copy of row 1 (30 s) that lasts 33 s: inside the engine's --length-tol 3, so the judge sees it
    data["files"].insert(0, file("peerC", "@@c\\Fjaak\\Fjaak - Spirit.flac", "Fjaak", "Spirit", 33))
    net.write_text(json.dumps(data), encoding="utf-8")
    paths = app_paths().ensure()
    runner = EngineRunner(fake_engine_spec(), SearchBudget(paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})

    def peer_c_line(settings):
        diag = run_diagnostic(rows[:1], runner, CREDS, paths=paths, settings=settings)
        return next(c for c in diag[0].candidates if c.peer == "peerC")

    default = peer_c_line(Settings())                         # 3 s apart: within the default 3 s
    assert default.accepted and "duración" not in default.why_es
    strict = peer_c_line(Settings(duration_ok_s=1, duration_review_s=2))
    assert not strict.accepted and "duración 33 s (se esperaban 30 s)" in strict.why_es, strict.why_es
    # a wider band too, judged directly (the engine would filter a result 11 s off): 41 s for a 30 s row
    fmt = build_preset("lossless").passes[0]
    name = "@@c\\Fjaak\\Fjaak - Spirit.flac"
    assert "duración 41 s" in judge_candidate(rows[0], fmt, name, 41.0, None)[2]
    assert "duración" not in judge_candidate(rows[0], fmt, name, 41.0, None, duration_review_s=12)[2]


def _no_results(tmp_path):
    rows, net = build_scenario("sin_resultados", tmp_path / "net")
    paths = app_paths().ensure()
    runner = EngineRunner(fake_engine_spec(), SearchBudget(paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    return run_diagnostic(rows, runner, CREDS, paths=paths)


def test_mac_no_results_explains_the_mac_firewall(as_macos, tmp_path):
    """1.1: on macOS the advice names this Mac, the macOS firewall and the engine's copy in Application Support."""
    diag = _no_results(tmp_path)
    for engine_id in ("fake", "sockseek-3.0.5", "sldl-2.6.0"):
        text = build_report(diag, app_version="1.1.0", engine_id=engine_id, windows_version="macOS 15.6 (arm64)",
                            listen_port=50000, redactor=Redactor(secrets=[CREDS.username]))
        assert "  |  macOS 15.6 (arm64)\n" in text
        assert "  1. Abre el puerto TCP 50000 en el router hacia la IP local de este Mac.\n" in text
        assert ("  2. Si tienes activado el firewall de macOS, permite las conexiones entrantes de «sockseek» (el motor "
                "de descarga de Tracklister) en Ajustes del Sistema > Red > Firewall > Opciones. Está en "
                "~/Library/Application Support/Tracklister/tools/engines.\n") in text
        assert "  3. Si tu operador usa CGNAT" in text and "  5. Comprueba tu usuario" in text
        for windows_only in (".exe", "Firewall de Windows", "%LOCALAPPDATA%", "este PC", "redes privadas"):
            assert windows_only not in text, windows_only


def test_no_results_explains_the_network(as_windows, tmp_path):
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
    # 1.1: the Windows lines are exactly those of 1.0.1
    assert "  1. Abre el puerto TCP 50000 en el router hacia la IP local de este PC.\n" in text
    assert ("  2. Permite «sockseek.exe» (el motor de descarga de Tracklister) en el Firewall de Windows, en redes "
            "privadas. Está en %LOCALAPPDATA%\\Tracklister\\tools\\engines.\n") in text
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


def _his_report(diag, redactor=None):
    return build_report(diag, app_version="1.0.1", engine_id="sockseek-3.0.5", windows_version="Windows 11",
                        listen_port=49998, redactor=redactor or Redactor(secrets=[CREDS.username, CREDS.password]))


def test_r7_pseudonyms_only_in_the_peer_column(tmp_path):
    """1.0.1, R7 (audit r4-3 N8), with his Diagnóstico: peers whose names are numbers or '?' used to turn
    «título distinto (50%)» into «(peer-6%)» and «? MB» into «peer-1 MB». Invented folder names."""
    from tracklister.diagnostics.run import CandidateLine, DiagRow
    from tests.fakes.scenarios import row
    trip = DiagRow(row(3, "Red Rooms", "Trip", dur=305), candidates=[
        CandidateLine("29", "Carpeta Ejemplo\\Red Rooms - Trip.flac", 31_352_422, None, 305, 100, True,
                      "elegido: aceptable: confianza 100/100"),
        CandidateLine("50", "Otra Carpeta\\04-red_rooms-trip.flac", None, None, 305, 49, False,
                      "rechazado: título distinto (50%)"),
        CandidateLine("?", "Lista Ejemplo\\Red Rooms - Trip (Original Mix) 140.flac", None, None, 305, 49, False,
                      "rechazado: título distinto (29%)")])
    kwartz = DiagRow(row(5, "Kwartz", "Show me that light", "Cleric Remix", dur=385), candidates=[
        CandidateLine("6", "Kwartz - Show Me That Light EP\\Kwartz - Show me that light.flac", 42_991_616, 1411, 384,
                      49, False, "rechazado: otra versión (se pedía 'Cleric Remix' y el archivo es la original)")])
    text = _his_report([trip, kwartz])
    assert ("    - peer-1 | Carpeta Ejemplo\\Red Rooms - Trip.flac | 29.9 MB | ? kbps | 5:05 | 100/100 | "
            "elegido: aceptable: confianza 100/100") in text
    assert "    - peer-2 | Otra Carpeta\\04-red_rooms-trip.flac | ? MB | ? kbps | 5:05 | 49/100 | " \
           "rechazado: título distinto (50%)" in text
    assert "    - peer-3 | Lista Ejemplo\\Red Rooms - Trip (Original Mix) 140.flac | ? MB | ? kbps | 5:05 | 49/100 | " \
           "rechazado: título distinto (29%)" in text
    assert "    - peer-4 | Kwartz - Show Me That Light EP\\Kwartz - Show me that light.flac | 41.0 MB | 1411 kbps | " \
           "6:24 | 49/100 | rechazado: otra versión" in text
    assert "peer-6%" not in text and "peer-1 MB" not in text and "(×" not in text
    assert "duración esperada 5:05" in text and "duración esperada 6:25" in text


def test_r7_identical_candidate_lines_become_one(tmp_path):
    """1.0.1, R7: his report listed the same file of one peer 3 times (the same folder under 3 shares)."""
    _, net = build_scenario("sin_resultados", tmp_path / "net")
    data = json.loads(net.read_text(encoding="utf-8"))
    tail = "Kwartz - Show Me That Light EP\\Kwartz - Show me that light (Cleric Remix).flac"
    other = "Kwartz Picks\\Other Artist - Show me that light (Cleric Remix).flac"
    data["files"] = ([file("peerG", f"@@{root}\\{tail}", "Kwartz", "Show me that light (Cleric Remix)", 384,
                           size=42_991_616) for root in ("a\\Musica", "b\\Copia", "c\\Otra")]
                     + [file("peerH", f"@@d\\{tail}", "Kwartz", "Show me that light (Cleric Remix)", 384, size=42_991_616)]
                     + [file("peerK", f"@@{root}\\{other}", "Other Artist", "Show me that light (Cleric Remix)", 384,
                             size=42_000_000) for root in ("e", "f", "g")])
    net.write_text(json.dumps(data), encoding="utf-8")
    paths = app_paths().ensure()
    runner = EngineRunner(fake_engine_spec(), SearchBudget(paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    from tests.fakes.scenarios import row
    diag = run_diagnostic([row(5, "Kwartz", "Show me that light", "Cleric Remix", dur=385)], runner, CREDS,
                          paths=paths, settings=Settings())
    c = diag[0].candidates
    assert [(x.peer, x.repeats) for x in c] == [("peerG", 3), ("peerH", 1), ("peerK", 3)]
    assert c[0].why_es.startswith("elegido") and not c[1].accepted and "primero que cumple" in c[1].why_es
    assert not c[2].accepted
    text = _his_report(diag)
    assert text.count(tail) == 2 and text.count(other) == 1
    line = next(x for x in text.splitlines() if tail in x and "elegido" in x)
    assert line.startswith("    - peer-1 | ") and line.endswith(" (×3)")
    assert next(x for x in text.splitlines() if other in x).endswith(" (×3)")
    assert not next(x for x in text.splitlines() if "primero que cumple" in x).endswith(")")


def test_r7_n7_an_account_named_like_a_word_of_the_engines_json(tmp_path):
    """Audit r4-3 N7: the JSON was parsed after redaction, so a password 'true' or a username 'file'
    broke it and the Diagnóstico said «El motor no devolvió resultados». Now it is read before."""
    rows, runner, paths = _setup(tmp_path)
    creds = Credentials("file", "true")
    diag = run_diagnostic(rows, runner, creds, paths=paths, settings=Settings())
    assert [len(d.candidates) for d in diag] == [2, 1] and all(d.error_es is None for d in diag)
    assert diag[0].candidates[1].path_tail == "Live 2026\\Fjaak - Spirit.flac"
    text = _his_report(diag, Redactor(secrets=[creds.username, creds.password]))
    assert "elegido" in text and "true" not in text.lower() and "file" not in text.lower()


def test_a_soulseek_downloads_folder_is_not_a_kick(tmp_path):
    """Barrido AG-02: one result in a 'Soulseek Downloads\\Kicked Inside' folder made the Diagnóstico say
    «Soulseek cortó la sesión durante la búsqueda.», drop the results and stop before the next row."""
    from tests.fakes.scenarios import row
    net = tmp_path / "net.json"
    net.write_text(json.dumps({"schema": "tracklister.fakenet/1", "search_delay_ms": 0, "ban_after_searches": None,
                               "peers": {}, "files": [file("peerA", "@@x\\Soulseek Downloads\\Kicked Inside\\"
                                                           "Fjaak - Spirit.flac", "Fjaak", "Spirit", 30)]}),
                   encoding="utf-8")
    paths = app_paths().ensure()
    runner = EngineRunner(fake_engine_spec(), SearchBudget(paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    diag = run_diagnostic([row(1, "Fjaak", "Spirit", dur=30), row(2, "Fjaak", "Raw", dur=30)], runner, CREDS,
                          paths=paths, settings=Settings())
    assert len(diag) == 2 and len(diag[0].candidates) == 1
    assert diag[0].error_es is None


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
