"""1.0.1 in the window: the «Verificado · revisar calidad» state, the merge question, the gap hook, renames.

SPDX-License-Identifier: GPL-3.0-or-later

Fake engine and fake inputs (tests/gui/fakes.py); nothing leaves the machine.
"""
from __future__ import annotations

import threading

import pytest
from PySide6.QtCore import Qt

from tests.fakes.scenarios import build_scenario
from tests.gui.conftest import TEST_PASS, TEST_USER
from tests.gui.fakes import fake_import
from tracklister.core.model import DoubtKind, ResultState, RowResult, RowStatus, SourceRef, TrackRow
from tracklister.engine.credentials import Credentials
from tracklister.gui.models import QUALITY_LONG_ES, ResultsTableModel
from tracklister.gui.pages.new_set import MERGE_KEEP_ES, MERGE_TITLE_ES
from tracklister.gui.pages.results import summary_text
from tracklister.gui.services import Services
from tracklister.verify.spectral import LEGACY_FLAG, STRONG_FLAG

S = ResultState


def _wait_done(qtbot, window, timeout=120000):
    qtbot.waitUntil(lambda: not window.worker_running() and window.results.phase.text() == "Terminado.",
                    timeout=timeout)


@pytest.mark.slow
def test_v101_quality_state_has_its_label_icon_text_and_count(window, qtbot, ready_services, prompter, tmp_path):
    rows, net = build_scenario("todos_los_estados_101", tmp_path / "net")
    ready_services.network = net
    prompter.lossy = set()
    window.new_set.set_rows(rows, name="Todos 101")
    window.new_set.request_download()
    _wait_done(qtbot, window)
    page, m = window.results, window.results.model
    i = next(k for k, r in enumerate(m.rows()) if r.pos == 8)
    assert m.state_of(m.rows()[i].uid) == S.REVISAR_CALIDAD
    idx = m.index(i, 2)
    assert m.data(idx) == "Verificado · revisar calidad"
    icon = m.data(idx, Qt.ItemDataRole.DecorationRole)
    assert icon is not None and not icon.isNull()                      # its own icon AND its own text
    assert m.data(idx, Qt.ItemDataRole.ForegroundRole).name() == window.themes.theme.state_color(S.REVISAR_CALIDAD)
    assert m.data(idx, Qt.ItemDataRole.AccessibleTextRole) == "Verificado · revisar calidad"
    tip = m.data(idx, Qt.ItemDataRole.ToolTipRole)
    assert QUALITY_LONG_ES in tip and "escúch" not in tip.lower()
    # counted apart from «Dudoso» (identity doubts), right after «Verificado»
    chips = page.chips.chips()
    assert chips[:3] == ["Verificado 2", "Verificado · revisar calidad 1", "Dudoso 1"]
    counts = m.counts()
    assert counts[S.REVISAR_CALIDAD] == 1 and counts[S.DUDOSO] == 1 and counts[S.VERIFICADO] == 2
    assert "1 verificada · revisar calidad" in summary_text(counts) and "1 dudosa" in summary_text(counts)
    msg = page.banner.message()
    assert "puede ser un MP3 convertido" in msg and "otra copia de las marcadas" in msg
    assert page.retry_btn.isEnabled() and m.quality_marked() == 1
    report = (window.session.set_dir / "Informe - Todos 101.txt").read_text(encoding="utf-8")
    assert "verificado · revisar calidad 1" in report and "escúch" not in report.lower()


def _model_with(results: dict[int, RowResult]):
    from tracklister.gui.theme import load_theme
    rows = [TrackRow(pos=p, title=f"T{p}", artists=["A"], artist_display="A") for p in results]
    m = ResultsTableModel(load_theme("hormigon"))
    m.load(rows, {r.uid: RowResult.from_dict({**results[r.pos].to_dict(), "uid": r.uid}) for r in rows})
    return m


def test_v101_legacy_and_reused_marks_without_escuchalo(app):
    m = _model_with({
        1: RowResult(uid="x", pos=1, state=S.DUDOSO, doubt=DoubtKind.ESPECTRO,
                     reasons=["Posible lossless falso: corte brusco a 16.2 kHz (cae 61 dB)"]),
        2: RowResult(uid="x", pos=2, state=S.YA_EN_BIBLIOTECA, flags=["reutilizado", STRONG_FLAG]),
        3: RowResult(uid="x", pos=3, state=S.YA_EN_BIBLIOTECA, flags=["reutilizado", LEGACY_FLAG]),
        4: RowResult(uid="x", pos=4, state=S.YA_EN_BIBLIOTECA, flags=["reutilizado"]),
        5: RowResult(uid="x", pos=5, state=S.REVISAR_CALIDAD, flags=[STRONG_FLAG]),
    })
    texts = [m.data(m.index(i, 2)) for i in range(5)]
    assert texts == ["Dudoso · marca de espectro de la 1.0.0", "Ya en biblioteca · probable MP3 convertido",
                     "Ya en biblioteca · probable MP3 convertido", "Ya en biblioteca", "Verificado · revisar calidad"]
    assert m.retryable() == 2                        # the 1.0.0 mark and the 1.0.1 one: another copy is looked for
    for i in range(5):
        tip = m.data(m.index(i, 2), Qt.ItemDataRole.ToolTipRole) or ""
        assert "escúch" not in tip.lower()


def test_v101_settings_label_and_library_dialog_wording(window):
    assert window.settings_page.spectral_box.text() == "Análisis de espectro: marcar los probables MP3 convertidos"
    from tracklister.core.model import LibraryEntry
    from tracklister.gui.dialogs import _entry_text
    kw = dict(key="k", artist_norm="border one", title_norm="spectral tension", version_kind="original", path="p",
              set_id="s", set_name="Anterior", pos=3)
    assert _entry_text(LibraryEntry(flags=[STRONG_FLAG], **kw)).endswith("marcado: probable MP3 convertido")
    assert _entry_text(LibraryEntry(flags=[LEGACY_FLAG], **kw)).endswith("marcado: probable MP3 convertido")
    assert "marcado" not in _entry_text(LibraryEntry(flags=[], **kw))


# ---- R2 / D8: the merge question once the set folder holds files ---------------------------------------
def _track(pos, artist, title, start, source="trackid_csv", **kw):
    return TrackRow(pos=pos, title=title, artists=[artist], artist_display=artist, ts_start=start,
                    ts_end=start + 200, source=source, **kw)


def _base():
    return [_track(1, "Komplex aka Jeroen Search", "Inject", 2), _track(2, "Red Rooms", "Trip", 334),
            _track(3, "Kwartz", "Show me that light", 892, version="Cleric Remix")]


def _extra():
    # the other source: Kwartz matches its base row; Seiko (18:01) comes after every base row (appended, no
    # number changes); Velocity (10:00) falls between Trip and Kwartz with no ID row there (an insertion)
    return [_track(1, "Phil Berg", "Seiko", 1081, source="texto"),
            _track(2, "Kwartz", "Show Me That Light", 891, source="texto", version="Cleric Remix"),
            _track(3, "Orbe", "Velocity", 600, source="texto")]


def _downloaded(services, name, rows):
    """A set folder of that name with one file on disk (as after a first download)."""
    s = services.create_session(name, rows, [SourceRef("trackid_csv", "x.csv")])
    first = sorted(s.doc.rows, key=lambda r: r.pos)[0]
    (s.set_dir / "01 - Komplex aka Jeroen Search - Inject.flac").write_bytes(b"x")
    res = s.doc.results[first.uid]
    res.state, res.file = S.VERIFICADO, "01 - Komplex aka Jeroen Search - Inject.flac"
    s.save()
    return s


def _merge_via_paste(page, qtbot, services, prompter, answers):
    services.imports = [fake_import(rows=_extra(), kind="texto", sources=[SourceRef("texto", "pegado")])]
    page.paste.setPlainText("lista")
    prompter.choose_answers = [1] + list(answers)          # «Usar lo pegado», then the merge question
    page.add_source()
    qtbot.waitUntil(lambda: not page._busy, timeout=10000)


def test_d8_a_set_with_files_asks_and_the_default_keeps_every_number(window, qtbot, ready_services, prompter):
    page = window.new_set
    page.set_rows(_base(), name="Set Descargado")
    _downloaded(ready_services, "Set Descargado", _base())
    before = {r.uid: r.pos for r in page.model.rows()}
    _merge_via_paste(page, qtbot, ready_services, prompter, [0])
    asks = [c for c in prompter.calls if c[0] == "choose"]
    assert asks[-1][1] == MERGE_TITLE_ES and asks[-1][2][0] == MERGE_KEEP_ES
    assert prompter.choose_defaults[-1] == 0                       # Enter takes the safe answer
    assert "cambiaría el número" in prompter.choose_texts[-1]
    rows = page.model.rows()
    assert all(r.pos == before[r.uid] for r in rows if r.uid in before)   # no existing row changed its number
    tail = [r for r in rows if r.uid not in before]
    assert [r.title for r in tail] == ["Seiko", "Velocity"] or [r.title for r in tail] == ["Velocity", "Seiko"]
    assert any("añadida al final para no cambiar números" in n for r in tail for n in r.notes)


def test_d8_choosing_the_set_order_inserts_and_closing_changes_nothing(window, qtbot, ready_services, prompter):
    page = window.new_set
    page.set_rows(_base(), name="Set Descargado")
    _downloaded(ready_services, "Set Descargado", _base())
    _merge_via_paste(page, qtbot, ready_services, prompter, [None])
    assert [r.title for r in page.model.rows()] == ["Inject", "Trip", "Show me that light"]
    assert "No se ha cambiado nada" in page.banner.message()
    _merge_via_paste(page, qtbot, ready_services, prompter, [1])
    assert [r.title for r in page.model.rows()] == ["Inject", "Trip", "Velocity", "Show me that light", "Seiko"]


def test_d8_before_the_first_download_nothing_is_asked(window, qtbot, ready_services, prompter, monkeypatch):
    monkeypatch.setattr(ready_services, "merge_rows", lambda b, e: Services.merge_rows(ready_services, b, e))
    page = window.new_set
    page.set_rows(_base(), name="Set Nuevo")
    _merge_via_paste(page, qtbot, ready_services, prompter, [])
    assert [c for c in prompter.calls if c[0] == "choose" and c[1] == MERGE_TITLE_ES] == []
    assert [r.title for r in page.model.rows()] == ["Inject", "Trip", "Velocity", "Show me that light", "Seiko"]
    assert [r.pos for r in page.model.rows()] == [1, 2, 3, 4, 5]


# ---- R1: gaps measured again when the enrichment is applied ------------------------------------------
def _gap(start, end):
    return TrackRow(pos=0, title="ID (hueco)", artists=[], artist_display="", ts_start=start, ts_end=end,
                    source="trackid_csv", confidence=0.0, is_id=True, status=RowStatus.ID, download=False)


def _with_gaps():
    # Inject 0:02-1:47 and Trip at 5:34: 227 s by trackid's End, 71 s once Inject lasts its 4:21 (06 R1)
    rows = [_track(1, "Komplex aka Jeroen Search", "Inject", 2), _gap(107, 334), _track(3, "Red Rooms", "Trip", 334)]
    rows[0].ts_end, rows[2].ts_end = 107, 523
    for i, r in enumerate(rows, start=1):
        r.pos = i
    return rows


def test_r1_completar_datos_removes_the_gap_the_real_duration_covers(window, qtbot, ready_services):
    ready_services.real_gaps = True
    ready_services.enrich_duration = 261                              # Inject lasts 4:21
    page = window.new_set
    page.set_rows(_with_gaps(), name="Huecos")
    page.enrich()
    qtbot.waitUntil(lambda: not page._busy, timeout=10000)
    assert [r.title for r in page.model.rows()] == ["Inject", "Trip"]
    assert "1 hueco quitado" in page.banner.message()


def test_r1_never_once_the_set_has_files(window, qtbot, ready_services):
    ready_services.real_gaps = True
    ready_services.enrich_duration = 261
    page = window.new_set
    page.set_rows(_with_gaps(), name="Huecos Descargado")
    s = ready_services.create_session("Huecos Descargado", _with_gaps(), [SourceRef("trackid_csv", "x.csv")])
    first = sorted(s.doc.rows, key=lambda r: r.pos)[0]
    (s.set_dir / "01 - a.flac").write_bytes(b"x")
    s.doc.results[first.uid].state, s.doc.results[first.uid].file = S.VERIFICADO, "01 - a.flac"
    s.save()
    page.enrich()
    qtbot.waitUntil(lambda: not page._busy, timeout=10000)
    assert [r.title for r in page.model.rows()] == ["Inject", "ID (hueco)", "Trip"]     # decision B
    assert ready_services.gap_calls == []


def test_r1_a_deleted_gap_is_not_brought_back(window, qtbot, ready_services):
    ready_services.real_gaps = True
    ready_services.enrich_duration = 30                               # short: the rule still sees the gap
    page = window.new_set
    page.set_rows(_with_gaps(), name="Huecos Borrados")
    page.table.selectRow(1)
    page._remove()
    assert [r.title for r in page.model.rows()] == ["Inject", "Trip"]
    page.enrich()
    qtbot.waitUntil(lambda: not page._busy, timeout=10000)
    assert [r.title for r in page.model.rows()] == ["Inject", "Trip"]
    assert ready_services.gap_calls and ready_services.gap_calls[-1]       # the deleted slot was passed on


# ---- R5: editing only the artists renames the file, with no download --------------------------------
@pytest.mark.slow
def test_r5_a_rename_only_descargar_still_finalizes(window, qtbot, ready_services, prompter, tmp_path):
    rows, net = build_scenario("correcto", tmp_path / "net")
    ready_services.network = net
    rows[0].artist_display, rows[0].artists = "Fjaak & Laster Records", ["Fjaak", "Laster Records"]
    page = window.new_set
    page.set_rows(rows, name="Renombrar")
    page.request_download()
    _wait_done(qtbot, window)
    set_dir = window.session.set_dir
    assert (set_dir / "01 - Fjaak & Laster Records - Spirit.flac").is_file()
    passes = len(window.session.doc.passes)
    m = page.model
    assert m.setData(m.index(0, m.column_of("artist")), "Fjaak")
    window.go("new_set")
    page.request_download()
    _wait_done(qtbot, window)
    assert len(window.session.doc.passes) == passes                 # nothing searched or downloaded again
    assert (set_dir / "01 - Fjaak - Spirit.flac").is_file()
    assert not (set_dir / "01 - Fjaak & Laster Records - Spirit.flac").exists()
