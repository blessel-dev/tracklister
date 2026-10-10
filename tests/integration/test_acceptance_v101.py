"""1.0.1 acceptance through the REAL window, offline: his set (10 Oct) with recorded answers and the fake engine.

SPDX-License-Identifier: GPL-3.0-or-later

- R1: his trackid.net CSV, imported and completed with the recorded iTunes/Deezer/MusicBrainz answers:
  the gaps are measured with the real durations (none after Inject, Seiko or Hidden Reason; the one after
  Trip stays).
- R2: «Añadir otra fuente del mismo set» with his YouTube comment's list: TR440 (53:32), Border One (1:18:25)
  and Aidan Rudd (1:34:28) go in time order, the other 21 match the trackid.net rows, and ID rows remain only
  where neither source has a track.
- R3/R6: the fake engine serves the file-name patterns of his Diagnóstico and set report (invented folders)
  and his spectral cuts; R4: it finds nothing for the 'aka', dotted and letter-digit spellings as written
  and finds the other spellings, in the download and in the Diagnóstico.
Run with -s to print the tables that construccion/test-report.md records.
"""
from __future__ import annotations

import json

import pytest

from tests.fakes.scenarios import CASA_V101, build_scenario
from tests.integration.conftest import FIX, make_services, replay
from tracklister.core.model import ResultState, SourceRef
from tracklister.gui.models import fmt_clock
from tracklister.inputs.gaps import clock, covered_until, is_auto_gap

pytestmark = [pytest.mark.gui, pytest.mark.slow]
S = ResultState
CSV = FIX / "inputs" / "setaoc-trackid.csv"
YOUTUBE = FIX / "inputs" / "setaoc-youtube.txt"


def _wait(qtbot, page, cond, timeout=60000):
    qtbot.waitUntil(lambda: not page._busy and cond(), timeout=timeout)


def _wait_done(qtbot, window, timeout=180000):
    qtbot.waitUntil(lambda: not window.worker_running() and window.results.phase.text() == "Terminado.",
                    timeout=timeout)


def _hms(s):
    return "" if s is None else (clock(s) if s < 3600 else f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}")


def _gap_table(rows) -> str:
    out = ["| NN | Pista | Start | End | Duración | Cubre hasta | Sin cubrir hasta la siguiente | Hueco |",
           "|---|---|---|---|---|---|---|---|"]
    tracks = [r for r in rows if not is_auto_gap(r)]
    for r in rows:
        if is_auto_gap(r):
            continue
        nxt = next((t for t in tracks if t.ts_start is not None and r.ts_start is not None
                    and t.ts_start > r.ts_start), None)
        cov, _ = covered_until(r)
        gap = next((g for g in rows if is_auto_gap(g) and g.ts_start == cov), None)
        un = (nxt.ts_start - cov) if (nxt is not None and cov is not None) else None
        out.append(f"| {r.pos:02d} | {r.artist_display} - {r.title_with_version} | {_hms(r.ts_start)} | "
                   f"{_hms(r.ts_end) if r.source == 'trackid_csv' else '-'} | {fmt_clock(r.expected_duration_s) or '?'} | "
                   f"{_hms(cov)} | {'' if un is None else f'{un} s'} | "
                   f"{('sí, fila ' + format(gap.pos, '02d')) if gap else 'no'} |")
    return "\n".join(out)


def _row_table(rows) -> str:
    out = ["| NN | Inicio | Artista - Título | Fuente | Duración | Nota |", "|---|---|---|---|---|---|"]
    for r in rows:
        src = "hueco" if is_auto_gap(r) else ("trackid.net" if r.source == "trackid_csv" else "YouTube")
        out.append(f"| {r.pos:02d} | {_hms(r.ts_start)} | {r.artist_display + ' - ' if r.artist_display else ''}"
                   f"{r.title_with_version} | {src} | {fmt_clock(r.expected_duration_s) or '-'} | "
                   f"{(r.notes[0] if r.notes else '')} |")
    return "\n".join(out)


def test_v101_r1_r2_his_csv_then_his_youtube_list_through_the_window(qtbot, open_window, tmp_path, prompter):
    http, rt = replay()
    services = make_services(tmp_path, http=http, enrichment=True)
    w = open_window(services)
    page = w.new_set
    # R1: import + the automatic «Completar datos» (recorded answers), then the gaps measured again
    page.import_source(CSV)
    _wait(qtbot, page, lambda: "Datos completados" in page.banner.message())
    rows = page.model.rows()
    gaps = [r for r in rows if is_auto_gap(r)]
    print("\n### R1 (CSV de trackid.net + duraciones grabadas)\n")
    print(page.banner.message() + "\n")
    print(_gap_table(rows))
    assert len(rows) == 27 and len(gaps) == 6 and [r.pos for r in rows] == list(range(1, 28))
    assert "3 huecos quitados" in page.banner.message()
    after = {next(t for t in reversed(rows[:rows.index(g)]) if not t.is_id).title: g for g in gaps}
    assert set(after) == {"Trip", "Twinfall", "Blind Spot", "Crux", "Incentive Systems", "Talitha"}
    assert not {"Inject", "Seiko", "Hidden Reason"} & set(after)
    assert after["Trip"].notes[0] == "4:13 sin cubrir aunque «Trip» sonara entero"
    # R2: «Añadir otra fuente del mismo set» with what was pasted (his YouTube list, lines only)
    page.paste.setPlainText(YOUTUBE.read_text(encoding="utf-8"))
    prompter.choose_answers = [1]
    page.add_source()
    _wait(qtbot, page, lambda: "Datos completados" in page.banner.message() and page.model.rowCount() > 27)
    rows = page.model.rows()
    print("\n### R2 (+ la lista del comentario de YouTube)\n")
    print(page.banner.message() + "\n")
    print(_row_table(rows))
    tracks = [r for r in rows if not r.is_id]
    assert len(tracks) == 24 and len(rows) == 29
    assert [r.ts_start for r in tracks] == sorted(r.ts_start for r in tracks)          # time order
    yt = {r.title: r for r in tracks if r.source != "trackid_csv"}
    assert set(yt) == {"Somewhen", "Spectral Tension", "Necromancer"}
    assert (yt["Somewhen"].ts_start, yt["Spectral Tension"].ts_start, yt["Necromancer"].ts_start) == \
        (53 * 60 + 32, 3600 + 18 * 60 + 25, 3600 + 34 * 60 + 28)
    assert [yt[t].pos for t in ("Somewhen", "Spectral Tension", "Necromancer")] == [13, 18, 23]
    assert sum(1 for r in tracks if r.source == "trackid_csv") == 21            # the trackid names stay (E.8)
    # ID rows only where neither source has a track
    for g in (r for r in rows if r.is_id):
        assert not any(g.ts_start <= t.ts_start < g.ts_end for t in tracks), g.notes
    assert prompter.choose_defaults == [None]          # before the first download nothing else was asked


def _states_table(session) -> str:
    out = ["| NN | Fila | Estado | Confianza | Archivo en el set | Motivo |", "|---|---|---|---|---|---|"]
    for r in sorted(session.doc.rows, key=lambda x: x.pos):
        res = session.doc.results[r.uid]
        why = "; ".join(x for x in res.reasons if x)[:150]
        out.append(f"| {r.pos:02d} | {r.artist_display} - {r.title_with_version} | {res.state.value}"
                   f"{' · ' + res.doubt.value if res.doubt else ''} | {res.score if res.score is not None else ''} | "
                   f"{res.file or ''} | {why} |")
    return "\n".join(out)


def test_v101_r3_r6_his_file_names_and_cuts_through_the_window(qtbot, open_window, tmp_path, prompter):
    rows, net = build_scenario("casa_v101", tmp_path / "net")
    services = make_services(tmp_path, network=net)
    w = open_window(services)
    prompter.lossy = set()
    assert w.start_download("Casa 1.0.1", rows, [SourceRef("tabla", "casa.csv")])
    _wait_done(qtbot, w)
    print("\n### R3 + R6 (nombres de archivo de su Diagnóstico e informe, sus cortes de espectro)\n")
    print(_states_table(w.session))
    want = {pos: state for pos, *_, state in CASA_V101}
    got = {r.pos: w.session.doc.results[r.uid].state.value for r in w.session.doc.rows}
    assert got == want
    m = w.results.model
    chips = w.results.chips.chips()
    print("\nContadores: " + " | ".join(chips))
    assert chips[:3] == ["Verificado 11", "Verificado · revisar calidad 2", "Dudoso 2"]
    report = (w.session.set_dir / "Informe - Casa 1.0.1.txt").read_text(encoding="utf-8")
    summary = next(x for x in report.splitlines() if x.startswith("Resumen:"))
    print(summary)
    assert summary == "Resumen: verificado 11, verificado · revisar calidad 2, dudoso 2"
    assert "escúch" not in report.lower() and m.retryable() == 4


def test_v101_r4_his_three_rows_by_their_other_spellings_through_the_window(qtbot, open_window, tmp_path,
                                                                             prompter):
    rows, net = build_scenario("variantes_r4_a_fondo", tmp_path / "net")
    services = make_services(tmp_path, network=net)
    w = open_window(services)
    prompter.lossy = set()
    assert w.start_download("Variantes", rows, [SourceRef("tabla", "casa.csv")])
    _wait_done(qtbot, w)
    print("\n### R4, descarga (motor falso con la limpieza de búsqueda de los motores reales)\n")
    print(_states_table(w.session))
    st = {r.pos: w.session.doc.results[r.uid].state for r in w.session.doc.rows}
    assert st == {1: S.VERIFICADO, 2: S.VERIFICADO, 3: S.NO_ENCONTRADO, 4: S.VERIFICADO}
    w.results.retry_btn.click()
    _wait_done(qtbot, w)
    print("\n### R4, «Reintentar fallos» (búsqueda a fondo)\n")
    print(_states_table(w.session))
    print("\nPasadas: " + ", ".join(p.name for p in w.session.doc.passes))
    r3 = w.session.doc.results[w.session.doc.rows[2].uid]
    assert r3.state == S.VERIFICADO and "Encontrado buscando «TR-440 - Somewhen»." in r3.reasons
    assert w.session.doc.passes[-1].name == "lossless-relajada-a-fondo-variante"


def test_v101_a5_the_diagnostico_tries_the_same_spellings(qtbot, open_window, tmp_path):
    rows, net = build_scenario("variantes_r4", tmp_path / "net")
    services = make_services(tmp_path, network=net)
    w = open_window(services)
    w.go("diagnostic")
    w.diagnostic.set_tracklist(rows[:3], "casa.csv")
    w.diagnostic.start()
    qtbot.waitUntil(lambda: bool(w.diagnostic.report), timeout=120000)
    text = w.diagnostic.report
    print("\n### Addendum 5, Diagnóstico de sus tres filas sin resultados\n")
    print("\n".join(x for x in text.splitlines() if x.strip()))
    assert "Encontrado buscando «Jeroen Search - Inject»" in text
    assert "Encontrado buscando «Vkn modular - Hidden Reason»" in text
    assert "Encontrado buscando «TR-440 - Somewhen»" in text
    assert "con resultados: 3; con un candidato válido: 3" in text
    for secret in ("usuario-prueba", "clave-prueba", "peerA", "peerB", "peerC"):
        assert secret not in text
    saved = json.dumps(text)
    assert "--desperate" not in saved
