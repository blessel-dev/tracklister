"""1.0.1 R11: the progress bar in the Estado column of the Descarga screen.

SPDX-License-Identifier: GPL-3.0-or-later

Model and delegate unit tests (texts, bar modes, throttling, no timers when idle, contrast from the
tokens) and one offline run with the fake engine in its slow mode, where a row goes Buscando ->
Descargando 0..100 % -> Comprobando -> Verificado.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QRect

from tests.fakes.scenarios import file as mkfile, row
from tracklister.assets import load_tokens
from tracklister.core.model import ResultState, RowResult, SourceRef
from tracklister.core.paths import app_paths
from tracklister.core.settings import Settings
from tracklister.engine.credentials import Credentials
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.runner import EngineRunner
from tracklister.engine.spec import EngineDialect, fake_engine_spec
from tracklister.gui.models import (
    BAR_BUSY, BAR_NONE, BAR_VALUE, PROGRESS_MIN_INTERVAL_S, PROGRESS_ROLE, ResultsTableModel, RowProgress,
    progress_detail, progress_fraction, progress_view,
)
from tracklister.gui.progress import BAR_H, BAR_W, bar_rect, fill_rect
from tracklister.pipeline.session import SetSession

MB = 1024 * 1024


@pytest.mark.parametrize("p, text, bar", [
    (RowProgress("espera"), "En espera", BAR_NONE),
    (RowProgress("buscando"), "Buscando…", BAR_BUSY),
    (RowProgress("cola"), "En cola", BAR_BUSY),
    (RowProgress("descargando", 0, None), "Descargando…", BAR_BUSY),
    (RowProgress("descargando", int(25.9 * MB), None), "Descargando 25,9 MB", BAR_BUSY),
    (RowProgress("descargando", int(25.9 * MB), int(41.0 * MB)), "Descargando 63 %", BAR_VALUE),
    (RowProgress("descargando", 0, int(41.0 * MB)), "Descargando 0 %", BAR_VALUE),
    (RowProgress("otra_copia", 0, None), "Probando otra copia…", BAR_BUSY),
    (RowProgress("descargado", int(41.0 * MB), int(41.0 * MB)), "Por comprobar", BAR_VALUE),
    (RowProgress("comprobando"), "Comprobando…", BAR_BUSY),
    (RowProgress("sin_resultados"), "Sin resultados", BAR_NONE),
    (RowProgress("sin_descargar"), "No se pudo descargar", BAR_NONE),
])
def test_r11_each_phase_has_its_text_and_bar(p, text, bar):
    v = progress_view(p)
    assert v.text == text and v.bar == bar
    if v.bar == BAR_VALUE:
        assert 0.0 <= v.fraction <= 1.0


def test_r11_detail_and_share_of_the_top_bar():
    assert progress_detail(RowProgress("descargando", int(25.9 * MB), int(41.0 * MB))) == "25,9 de 41,0 MB"
    assert progress_detail(RowProgress("descargando", int(25.9 * MB), None)) == "25,9 MB recibidos"
    assert progress_detail(RowProgress("buscando")) == ""
    assert progress_fraction(RowProgress("descargando", 50, 100)) == pytest.approx(0.45)
    assert progress_fraction(RowProgress("buscando")) == 0.0
    assert progress_fraction(RowProgress("comprobando")) == pytest.approx(0.95)


class Clock:
    def __init__(self):
        self.t = 50.0

    def __call__(self):
        return self.t


def _model(app, n=3):
    from tracklister.gui.theme import load_theme
    clock = Clock()
    m = ResultsTableModel(load_theme("hormigon"), clock=clock)
    rows = [row(i, f"Artista {i}", f"Tema {i}", dur=30) for i in range(1, n + 1)]
    m.load(rows, {r.uid: RowResult(uid=r.uid, pos=r.pos, state=ResultState.EN_CURSO) for r in rows})
    return m, rows, clock


def test_r11_updates_touch_only_the_estado_and_detalle_cells_and_are_throttled(app, qtbot):
    m, rows, clock = _model(app)
    seen = []
    m.dataChanged.connect(lambda a, b, *_: seen.append((a.row(), a.column(), b.row(), b.column())))
    resets = []
    m.modelReset.connect(lambda: resets.append(1))
    u = rows[1].uid
    assert m.apply_progress(u, "descargando", 0, 1000)
    assert seen == [(1, 2, 1, 3)]                                  # one row, Estado..Detalle only
    clock.t += 0.05
    assert not m.apply_progress(u, "descargando", 100, 1000)       # held back: at most 4 per second
    assert not m.apply_progress(u, "descargando", 200, 1000)
    assert len(seen) == 1 and m._flush.isActive()
    qtbot.waitUntil(lambda: len(seen) == 2, timeout=2000)           # the last value is shown, once
    assert m.index(1, 2).data() == "Descargando 20 %" and not m._flush.isActive()
    clock.t += 0.01
    assert m.apply_progress(u, "comprobando")                      # a phase change is never held back
    assert len(seen) == 3 and resets == []
    # the final state clears the bar: icon and label only
    m.apply_event(u, ResultState.VERIFICADO, "", RowResult(uid=u, pos=2, state=ResultState.VERIFICADO))
    assert m.index(1, 2).data() == "Verificado" and m.index(1, 2).data(PROGRESS_ROLE) is None


def test_r11_many_rows_at_once_and_the_top_bar_share(app):
    m, rows, clock = _model(app, n=32)
    for i, r in enumerate(rows):
        clock.t += 0.001
        m.apply_progress(r.uid, "descargando", i, 31)
    assert m.progress_emits == 32
    assert m.in_flight() == pytest.approx(sum(0.9 * i / 31 for i in range(32)))
    assert len(m.busy_rows()) == 0                                 # determinate bars need no animation
    m.apply_progress(rows[0].uid, "buscando")
    assert m.busy_rows() == [0]


def test_r11_accessible_text_is_the_state_text(app):
    m, rows, clock = _model(app)
    m.apply_progress(rows[0].uid, "descargando", int(25.9 * MB), int(41.0 * MB))
    from PySide6.QtCore import Qt
    idx = m.index(0, 2)
    assert idx.data(Qt.ItemDataRole.AccessibleTextRole) == "Descargando 63 %"
    assert m.index(0, 3).data() == "25,9 de 41,0 MB"
    # while a row is in flight its Detalle only carries bytes: never a stale «En cola» next to «Comprobando…»
    m.apply_event(rows[1].uid, ResultState.EN_CURSO, "En cola")
    m.apply_progress(rows[1].uid, "comprobando")
    assert m.index(1, 2).data() == "Comprobando…" and m.index(1, 3).data() == ""


def test_r11_bar_geometry_is_flat_and_inside_the_cell():
    cell = QRect(300, 60, 262, 30)
    bar = bar_rect(cell)
    assert (bar.width(), bar.height()) == (BAR_W, BAR_H) and 60 <= BAR_W <= 90 and 6 <= BAR_H <= 8
    assert cell.contains(bar) and bar.center().y() in (cell.center().y(), cell.center().y() + 1)
    v = progress_view(RowProgress("descargando", 63, 100))
    f = fill_rect(bar, v, 0.0)
    assert f.left() == bar.left() + 1 and f.width() == round((BAR_W - 2) * 0.63)
    busy = progress_view(RowProgress("buscando"))
    a, b = fill_rect(bar, busy, 0.0), fill_rect(bar, busy, 0.35)
    assert a.width() == b.width() and a.left() != b.left()               # the segment moves with the clock
    assert bar.adjusted(1, 1, -1, -1).contains(a) and bar.adjusted(1, 1, -1, -1).contains(b)


def _ratio(a: str, b: str) -> float:
    def lum(h):
        h = h.lstrip("#")
        c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("theme", ["hormigon", "noche"])
def test_r11_the_fill_reaches_3_to_1_on_its_track_and_every_cell_background(theme):
    c = load_tokens()["themes"][theme]["colors"]
    assert _ratio(c["accent"], c["surface"]) >= 3.0                     # the track
    for bg in ("surface", "surface_alt", "selection"):                  # plain, alternate and selected rows
        assert _ratio(c["accent"], c[bg]) >= 3.0, bg
        assert _ratio(c["line_strong"], c[bg]) >= 3.0, bg               # the 1 px border


def test_r11_no_timer_and_no_repaint_while_idle(window, qtbot):
    page = window.results
    m = page.model
    rows = [row(1, "Fjaak", "Spirit", dur=30)]
    m.load(rows, {rows[0].uid: RowResult(uid=rows[0].uid, pos=1, state=ResultState.EN_CURSO)})
    page.running = True
    page.on_session_event(_ev("row_progress", rows[0].uid, phase="buscando"), None)
    assert page._anim.isActive()                                        # something runs: the segment moves
    page.set_running(False)
    assert not page._anim.isActive() and not m._flush.isActive() and m.progress_of(rows[0].uid) is None
    seen = []
    m.dataChanged.connect(lambda *a: seen.append(a))
    qtbot.wait(400)
    assert seen == []


def _ev(kind, uid, **kw):
    from tracklister.pipeline.session import SessionEvent
    return SessionEvent(kind, uid, ResultState.EN_CURSO, **kw)


def test_r11_a_row_goes_from_buscando_to_verificado_offline(app, tmp_path):
    """Pipeline + fake engine (sldl 2.x mimic: it prints the size) in slow mode, fed into the results model."""
    from tracklister.gui.theme import load_theme
    net = {"schema": "tracklister.fakenet/1", "search_delay_ms": 0, "ban_after_searches": None, "peers": {},
           "write_s": 2.4, "files": [mkfile("peerA", "@@x\\Fjaak\\Fjaak - Spirit.flac", "Fjaak", "Spirit", 20)]}
    netp = tmp_path / "net.json"
    netp.write_text(json.dumps(net), encoding="utf-8")
    paths = app_paths().ensure()
    settings = Settings(preset_id="lossless", library_root=str(tmp_path / "bib"))
    s = SetSession.create("Progreso", [row(1, "Fjaak", "Spirit", dur=20)], [SourceRef("tabla", "t.csv")], settings,
                          tmp_path / "bib", paths)
    runner = EngineRunner(fake_engine_spec(EngineDialect.SLDL2), SearchBudget(paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(netp)})
    events = []
    s.run(runner, Credentials("usuario-prueba", "clave-prueba"), events.append, threading.Event(), lambda r: set())
    uid = s.doc.rows[0].uid
    phases = [e.phase for e in events if e.kind == "row_progress" and e.uid == uid]
    # each phase in order (repeated byte updates collapsed)
    order = [p for i, p in enumerate(phases) if i == 0 or phases[i - 1] != p]
    assert order == ["espera", "buscando", "descargando", "descargado", "comprobando"]
    m = ResultsTableModel(load_theme("noche"), clock=lambda: 0.0)
    m.load(s.doc.rows, {uid: RowResult(uid=uid, pos=1)})
    texts = []
    for e in events:
        if e.uid != uid:
            continue
        if e.kind == "row_progress":
            m._last_emit.clear()                          # replayed at once: skip the throttle
            m.apply_progress(uid, e.phase, e.bytes_done, e.bytes_total)
        elif e.kind == "row_state" and e.done:
            m.apply_event(uid, e.state, e.message_es, s.doc.results[uid])
        texts.append(m.index(0, 2).data())
    pct = [t for t in texts if t.startswith("Descargando ") and t.endswith("%")]
    assert pct[0] == "Descargando 0 %" and len(set(pct)) >= 3
    assert [int(t.split()[1]) for t in pct] == sorted(int(t.split()[1]) for t in pct)
    assert "Por comprobar" in texts and "Comprobando…" in texts and texts[-1] == "Verificado"
    assert s.doc.results[uid].state == ResultState.VERIFICADO
