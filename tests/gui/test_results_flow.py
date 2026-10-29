"""Descargando/resultados end to end through the window, with the FAKE engine (no network).

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import json
import threading

import pytest
from PySide6.QtCore import Qt

from tests.fakes.scenarios import build_scenario
from tests.gui.conftest import TEST_PASS, TEST_USER
from tests.gui.fakes import sample_rows
from tracklister.core.model import DuplicateChoice, ResultState, SourceRef
from tracklister.engine.credentials import CredentialStore, Credentials

pytestmark = [pytest.mark.gui, pytest.mark.slow]
S = ResultState


def _previous_set(services, tmp_path):
    """'Anterior' downloaded and finalized: Fjaak - Spirit and the FJAAK remix are in the library."""
    rows, net = build_scenario("correcto", tmp_path / "net-anterior")
    s = services.create_session("Anterior", rows, [SourceRef("tabla", "anterior.csv")])
    runner = services.make_runner()
    runner.env["TRACKLISTER_FAKE_NETWORK"] = str(net)
    s.run(runner, Credentials(TEST_USER, TEST_PASS), lambda e: None, threading.Event(), lambda r: set())
    s.finalize(services.library())


def _wait_done(qtbot, window, timeout=120000):
    qtbot.waitUntil(lambda: not window.worker_running() and window.results.phase.text() == "Terminado.",
                    timeout=timeout)


def test_every_state_with_icon_and_text_then_retry(window, qtbot, ready_services, prompter, tmp_path):
    _previous_set(ready_services, tmp_path)
    rows, net = build_scenario("todos_los_estados", tmp_path / "net-todos")
    ready_services.network = net
    prompter.duplicates = [(DuplicateChoice.DOWNLOAD, None, False), (DuplicateChoice.REUSE, "first", False)]
    prompter.lossy = set()
    window.new_set.set_rows(rows, name="Todos")
    window.new_set.request_download()
    assert window.current_page() == "results" and window.worker_running()
    assert window.results.cancel_btn.isVisible()
    _wait_done(qtbot, window)
    m = window.results.model
    got = {r.pos: m.state_of(r.uid) for r in m.rows()}
    assert got == {1: S.VERIFICADO, 2: S.DUDOSO, 3: S.NO_ENCONTRADO, 4: S.NO_CUMPLE_FORMATO, 5: S.FALLIDA,
                   6: S.YA_EN_BIBLIOTECA, 7: S.OMITIDA}
    labels = {}
    for i in range(m.rowCount()):
        idx = m.index(i, 2)
        icon = m.data(idx, Qt.ItemDataRole.DecorationRole)
        assert icon is not None and not icon.isNull()                      # icon AND text, never colour alone
        labels[i + 1] = m.data(idx)
        assert m.data(idx, Qt.ItemDataRole.ForegroundRole).name() == \
            window.themes.theme.state_color(got[i + 1])
    assert labels == {1: "Verificado", 2: "Dudoso · otra versión", 3: "No encontrado", 4: "No cumple formato",
                      5: "Fallida", 6: "Ya en biblioteca", 7: "Omitida"}
    assert m.data(m.index(0, 4)) == "FLAC · 44,1 kHz · 16 bit" and m.data(m.index(0, 5)) == "100/100"
    # each repeated track was asked about, with both options; the lossy checklist once
    asked = [c for c in prompter.calls if c[0] == "ask_duplicate"]
    assert asked == [("ask_duplicate", 1, 1, 2), ("ask_duplicate", 6, 2, 2)]
    lossy = [c for c in prompter.calls if c[0] == "ask_lossy"]
    assert len(lossy) == 1 and 3 in lossy[0][1]
    chips = window.results.chips.chips()
    for text in ("Verificado 1", "Ya en biblioteca 1", "Dudoso 1", "No encontrado 1", "No cumple formato 1",
                 "Fallida 1", "Omitida 1"):
        assert text in chips
    # 1.0.1, R11: the top bar counts in hundredths of a row (it also moves with the rows in flight)
    assert window.results.progress.value() == window.results.progress.maximum() == 600
    assert window.results.count.text() == "6 de 6"
    assert "Listo:" in window.results.banner.message() and "_dudosos" in window.results.banner.message()
    # details of the selected row
    window.results.table.selectRow(1)
    assert "Otra versión" in window.results.detail.text()
    # Copiar tracklist / informe
    window.results.copy_btn.click()
    assert ready_services.copied[-1].startswith("01. Fjaak - Spirit\n02. Fjaak - Raw")
    set_dir = window.session.set_dir
    assert (set_dir / "Informe - Todos.txt").is_file() and (set_dir / "Tracklist - Todos.txt").is_file()
    assert window.results.report_btn.isEnabled()
    window.results.report_btn.click()
    assert ready_services.opened_paths[-1].name == "Informe - Todos.txt"
    window.results.folder_btn.click()
    assert ready_services.opened_paths[-1] == set_dir
    # Reintentar fallos: one more (relaxed) pass, then the same final picture
    assert window.results.retry_btn.isEnabled()
    passes_before = len(window.session.doc.passes)
    window.results.retry_btn.click()
    assert window.worker_running()
    _wait_done(qtbot, window)
    assert len(window.session.doc.passes) > passes_before
    names = [p.name for p in window.session.doc.passes[passes_before:]]
    assert names[0].endswith("-relajada")
    # 1.0.1, R4: the row still not found ends the retry with the engine's deep search (--desperate)
    assert names[-1] == "lossless-relajada-a-fondo"
    assert m.state_of(m.rows()[0].uid) == S.VERIFICADO


def test_apply_to_all_repeated_and_closing_the_question(window, ready_services, prompter, tmp_path, monkeypatch):
    _previous_set(ready_services, tmp_path)
    rows, _ = build_scenario("todos_los_estados", tmp_path / "net-todos")
    started = []
    monkeypatch.setattr(window, "_start_worker", lambda mode, creds, choices: started.append((mode, choices)))
    prompter.duplicates = [None]                         # the dialog was closed: nothing starts
    assert window.start_download("Todos", rows, []) is False
    assert started == [] and "no iniciada" in window.new_set.banner.message()
    assert not ready_services.set_dir_for("Todos").exists()          # round 2, N7: and no set folder
    prompter.duplicates = [(DuplicateChoice.REUSE, "first", True)]
    assert window.start_download("Todos", rows, []) is True
    assert (ready_services.set_dir_for("Todos") / ".tracklister" / "set.json").is_file()
    assert len([c for c in prompter.calls if c[0] == "ask_duplicate"]) == 2   # 1 (closed) + 1 (applied to all)
    mode, choices = started[0]
    assert mode == "run" and [c[1] for c in choices] == [DuplicateChoice.REUSE, DuplicateChoice.REUSE]
    assert all(c[2] is not None for c in choices)


def test_r2_n7_closing_the_question_on_an_existing_set_changes_nothing(window, ready_services, prompter, tmp_path,
                                                                     monkeypatch):
    _previous_set(ready_services, tmp_path)
    rows, _ = build_scenario("duplicado_entre_sets", tmp_path / "net-1")
    existing = ready_services.create_session("Existente", rows, [])         # saved, nothing downloaded yet
    doc = existing.set_dir / ".tracklister" / "set.json"
    before = doc.read_bytes()
    monkeypatch.setattr(window, "_start_worker", lambda mode, creds, choices: None)
    prompter.duplicates = [None]
    again, _ = build_scenario("duplicado_entre_sets", tmp_path / "net-2")    # the same table imported again
    assert window.start_download("Existente", again, []) is False
    assert doc.read_bytes() == before and window.session is None


def test_r2_b1_a_flac_of_the_library_is_not_even_offered_to_an_mp3_set(window, ready_services, prompter, tmp_path,
                                                                     monkeypatch):
    _previous_set(ready_services, tmp_path)                 # "Anterior" (Lossless): two FLACs in the library
    rows, _ = build_scenario("correcto", tmp_path / "net-mp3")
    ready_services.settings.preset_id = "solo_mp3_320"
    started = []
    monkeypatch.setattr(window, "_start_worker", lambda mode, creds, choices: started.append(choices))
    assert window.start_download("Solo MP3", rows, []) is True
    assert not [c for c in prompter.calls if c[0] == "ask_duplicate"] and started == [[]]


def test_r2_b1_apply_to_all_under_cdj_converts_the_library_flacs(window, qtbot, ready_services, prompter, tmp_path):
    _previous_set(ready_services, tmp_path)
    rows, net = build_scenario("correcto", tmp_path / "net-cdj")
    ready_services.network = net
    ready_services.settings.preset_id = "cdj_antiguos"
    prompter.duplicates = [(DuplicateChoice.REUSE, "first", True)]          # "Aplicar a todos"
    assert window.start_download("CDJ", rows, []) is True
    _wait_done(qtbot, window)
    assert len([c for c in prompter.calls if c[0] == "ask_duplicate"]) == 1
    set_dir = window.session.set_dir
    assert sorted(p.name for p in set_dir.glob("*.aif*")) == [
        "01 - Fjaak - Spirit.aiff", "02 - Chris Liebing - Higher Things (FJAAK Remix).aiff"]
    assert sorted(p.name for p in (set_dir / "_originales").iterdir()) == [
        "01 - Fjaak - Spirit.flac", "02 - Chris Liebing - Higher Things (FJAAK Remix).flac"]
    assert not list(set_dir.glob("*.flac"))                                  # no FLAC for the old CDJs
    m = window.results.model
    assert {m.state_of(r.uid) for r in m.rows()} == {S.YA_EN_BIBLIOTECA}


def test_cancel_keeps_what_is_done_and_offers_continue(window, qtbot, ready_services, tmp_path):
    rows, net = build_scenario("correcto", tmp_path / "net-slow")
    data = json.loads(net.read_text(encoding="utf-8"))
    data["peers"] = {"peerB": {"slow": True, "slow_s": 60}}
    net.write_text(json.dumps(data), encoding="utf-8")
    ready_services.network = net
    assert window.start_download("Lento", rows, [])
    m = window.results.model
    qtbot.waitUntil(lambda: m.counts().get(S.EN_CURSO, 0) == 2, timeout=30000)
    window.results.cancel_btn.click()
    # CL-28: a cancelled run now ends with the phase «Cancelado.» instead of «Terminado.»
    qtbot.waitUntil(lambda: not window.worker_running() and window.results.phase.text() == "Cancelado.",
                    timeout=60000)
    assert {m.state_of(r.uid) for r in m.rows()} <= {S.PENDIENTE, S.VERIFICADO}
    assert window.results.continue_btn.isVisible()


def test_after_cancelar_the_final_texts_say_cancelado(window, qtbot, ready_services, tmp_path):
    """CL-28 (his decision, 29 Oct): after «Cancelar», «Cancelando…» was replaced by «Pasada N: …: terminada.», the
    phase ended with «Terminado.», the notice read «Listo: …» and the status bar «Descarga terminada.». Now
    «Cancelando…» stays until the end, the phase says «Cancelado.», the notice starts with «Cancelado: » and the
    status bar says «Descarga cancelada.»."""
    from tracklister.pipeline.session import SessionEvent
    rows, net = build_scenario("correcto", tmp_path / "net-slow")
    data = json.loads(net.read_text(encoding="utf-8"))
    data["peers"] = {"peerB": {"slow": True, "slow_s": 60}}
    net.write_text(json.dumps(data), encoding="utf-8")
    ready_services.network = net
    assert window.start_download("Lento", rows, [])
    m = window.results.model
    qtbot.waitUntil(lambda: m.counts().get(S.EN_CURSO, 0) == 2, timeout=30000)
    window.results.cancel_btn.click()
    window.results.on_session_event(SessionEvent("pass_finished", message_es="Pasada 1: lossless: terminada."), None)
    assert window.results.phase.text().startswith("Cancelando"), window.results.phase.text()
    qtbot.waitUntil(lambda: window.worker is None, timeout=60000)
    assert window.results.phase.text() == "Cancelado."
    assert window.results.banner.message().startswith("Cancelado: "), window.results.banner.message()
    assert window.statusBar().currentMessage() == "Descarga cancelada."


def test_closing_during_the_checks_waits_for_them(window, qtbot, ready_services, prompter, tmp_path, monkeypatch):
    """CL-35 (V.6 N15): «Salir» promises «se guarda lo que ya esté descargado». After cancelling, the files that
    already arrived are still checked and placed; when that takes longer than the close wait, the window stays
    open, says so and closes by itself once they are placed. Before, it closed anyway and the process died with
    the QThread still running, in the middle of a file."""
    from tracklister.core.layout import set_doc_path
    from tracklister.gui.main_window import MainWindow
    from tracklister.pipeline.session import SetSession
    rows, net = build_scenario("correcto", tmp_path / "net-cerrar")
    ready_services.network = net
    monkeypatch.setattr(MainWindow, "CLOSE_WAIT_MS", 200)
    entered, gate = threading.Event(), threading.Event()
    real_settle = SetSession._settle_row

    def slow_settle(self, *args, **kwargs):          # placing the downloaded files takes a while
        entered.set()
        gate.wait(60)
        return real_settle(self, *args, **kwargs)

    monkeypatch.setattr(SetSession, "_settle_row", slow_settle)
    try:
        assert window.start_download("Cerrar", rows, [])
        qtbot.waitUntil(entered.is_set, timeout=60000)
        prompter.confirm_answer = True                 # «Salir»
        window.close()
        assert window.isVisible() and window.worker_running()
        assert "se cerrará al terminar" in window.statusBar().currentMessage()
        window.close()                                 # asking again while it waits: still open, no new question
        assert window.isVisible()
        assert [c[1] for c in prompter.calls if c[0] == "confirm"] == ["Salir"]
    finally:
        gate.set()
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=60000)
    assert not window.worker_running()
    doc = json.loads(set_doc_path(window.session.set_dir).read_text(encoding="utf-8"))
    states = [res["state"] for res in doc["results"].values()]
    assert len(states) == 2 and "en_curso" not in states
    assert set(states) == {"verificado"}


def test_download_without_account_goes_to_settings(window, prompter):
    CredentialStore().clear()
    assert window.start_download("X", sample_rows(), []) is False
    assert window.current_page() == "settings"
    assert prompter.calls[-1][0] == "error" and "Falta tu cuenta" in prompter.calls[-1][2]


def test_open_previous_set(window, ready_services, prompter, tmp_path):
    _previous_set(ready_services, tmp_path)
    set_dir = ready_services.set_dir_for("Anterior")
    prompter.folders = [str(set_dir)]
    window.open_previous_set()
    assert window.current_page() == "results" and window.results.title.text() == "Anterior"
    m = window.results.model
    assert [m.state_of(r.uid) for r in m.rows()] == [S.VERIFICADO, S.VERIFICADO]
    assert window.results.report_btn.isEnabled() and not window.results.retry_btn.isEnabled()
    prompter.folders = [str(tmp_path)]
    window.open_previous_set()
    assert prompter.calls[-1][0] == "error"
