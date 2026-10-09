"""Nuevo set: drop zone, 'Pega un enlace o un texto', the editable review table, sources, watcher.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, Qt, QUrl

from tests.gui.fakes import FakeCandidate, fake_import, sample_rows
from tracklister import config
from tracklister.core.model import RowStatus, SourceRef, TrackRow
from tracklister.gui.widgets import source_from_mime

pytestmark = pytest.mark.gui
CHECK = Qt.ItemDataRole.CheckStateRole


def _wait_rows(qtbot, page, n):
    qtbot.waitUntil(lambda: not page._busy and page.model.rowCount() == n, timeout=10000)


def test_paste_import_fills_the_review_table(window, qtbot, ready_services):
    page = window.new_set
    assert window.current_page() == "new_set"
    page.paste.setPlainText("01. Fjaak - Spirit")
    page.read_paste()
    _wait_rows(qtbot, page, 4)
    assert ready_services.import_calls == ["01. Fjaak - Spirit"]
    assert page.name.text() == "Set de prueba"
    m = page.model
    assert [r.pos for r in m.rows()] == [1, 2, 3, 4]
    dl = m.column_of("download")
    assert m.data(m.index(0, dl), CHECK) == Qt.CheckState.Checked
    assert m.data(m.index(2, dl), CHECK) == Qt.CheckState.Unchecked        # ID (hueco)
    assert m.data(m.index(3, dl), CHECK) == Qt.CheckState.Unchecked        # revisar
    assert m.data(m.index(3, m.column_of("status"))) == "Revisar"
    assert m.data(m.index(2, m.column_of("status"))) == "ID"
    assert m.data(m.index(1, m.column_of("start"))) == "05:12"
    assert page.download_btn.text() == "Descargar 2 pistas" and page.download_btn.isEnabled()
    assert "4 pistas leídas" in page.banner.message()
    assert page.count_label.text() == "4 pistas · 2 marcadas"


def test_empty_paste_and_failed_import_explain(window, qtbot, ready_services):
    page = window.new_set
    page.read_paste()
    assert "Pega primero" in page.banner.message() and ready_services.import_calls == []
    ready_services.imports = [fake_import([], kind="trackid_url",
                                          message_es="trackid.net no permite lectura automática: exporta el CSV.")]
    page.import_source("https://trackid.net/audiostreams/x")
    qtbot.waitUntil(lambda: not page._busy, timeout=5000)
    assert "exporta el CSV" in page.banner.message() and page.model.rowCount() == 0
    btn = page.banner.actions.itemAt(0).widget()
    assert btn.text() == "Abrir en trackid.net"
    btn.click()
    assert ready_services.opened_urls == [config.TRACKID_URL]


def test_drop_file_and_trackid_button(window, qtbot, ready_services, tmp_path):
    f = tmp_path / "set.csv"
    f.write_text("Pos,Start,End,Artist,Title,Label\n", encoding="utf-8")
    window.new_set.drop.dropped.emit(str(f))
    _wait_rows(qtbot, window.new_set, 4)
    assert ready_services.import_calls == [f]
    window.new_set.trackid_btn.click()
    assert ready_services.opened_urls == [config.TRACKID_URL]


def test_source_from_mime(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("a", encoding="utf-8")
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(f))])
    assert Path(source_from_mime(md)) == f
    md2 = QMimeData()
    md2.setUrls([QUrl("https://www.youtube.com/watch?v=abc")])
    assert source_from_mime(md2) == "https://www.youtube.com/watch?v=abc"
    md3 = QMimeData()
    md3.setText("01. A - B")
    assert source_from_mime(md3) == "01. A - B"
    assert source_from_mime(QMimeData()) is None


def test_editing_cells(window):
    page = window.new_set
    page.set_rows(sample_rows(), name="X")
    m = page.model
    assert m.setData(m.index(0, m.column_of("artist")), "Fjaak & Kobosil")
    r0 = m.row_at(0)
    assert r0.artists == ["Fjaak", "Kobosil"] and r0.artist_display == "Fjaak & Kobosil"
    assert m.setData(m.index(0, m.column_of("title")), "Spirit (Kobosil Remix)")
    assert (r0.title, r0.version) == ("Spirit", "Kobosil Remix")
    assert m.setData(m.index(0, m.column_of("version")), "")
    assert r0.version is None
    assert m.setData(m.index(0, m.column_of("duration")), "5:09") and r0.expected_duration_s == 309
    assert not m.setData(m.index(0, m.column_of("duration")), "5:99")
    assert m.setData(m.index(0, m.column_of("start")), "1:02:03") and r0.ts_start == 3723
    # an identified ID row becomes a normal, checked row
    assert m.setData(m.index(2, m.column_of("artist")), "Kobosil")
    assert m.setData(m.index(2, m.column_of("title")), "Aggression")
    r2 = m.row_at(2)
    assert not r2.is_id and r2.download and r2.status == RowStatus.OK
    # a row without title cannot be checked
    i = m.insert_row(4)
    assert not m.setData(m.index(i, 0), Qt.CheckState.Checked, CHECK)
    assert m.setData(m.index(i, m.column_of("title")), "Nueva")
    assert m.row_at(i).download is True
    assert [r.pos for r in m.rows()] == [1, 2, 3, 4, 5]
    assert m.setData(m.index(0, 0), Qt.CheckState.Unchecked, CHECK) and not r0.download


def test_move_and_remove_keep_row_index_numbering(window):
    page = window.new_set
    page.set_rows(sample_rows(), name="X")
    m = page.model
    first = m.row_at(0).uid
    page.table.selectRow(0)
    page._move(1)
    assert m.row_at(1).uid == first and [r.pos for r in m.rows()] == [1, 2, 3, 4]
    assert m.data(m.index(1, m.column_of("pos"))) == "02"
    page.table.selectRow(3)
    page._remove()
    assert m.rowCount() == 3 and [r.pos for r in m.rows()] == [1, 2, 3]


def test_second_import_replace_or_merge(window, qtbot, prompter, ready_services):
    page = window.new_set
    page.import_source("a")
    _wait_rows(qtbot, page, 4)
    prompter.choose_answers = [1]                                      # "Combinar con la actual"
    ready_services.imports = [fake_import([TrackRow(pos=1, title="Aggression", artists=["Kobosil"],
                                                    artist_display="Kobosil")])]
    page.import_source("b")
    _wait_rows(qtbot, page, 5)
    assert ready_services.merge_calls == 1 and page.name.text() == "Set de prueba"
    assert "Fuentes combinadas" in page.banner.message()
    prompter.choose_answers = [0]                                      # "Reemplazar la tabla"
    ready_services.imports = [fake_import([TrackRow(pos=1, title="Solo", artists=["Uno"], artist_display="Uno")],
                                          suggested_name="Otro set")]
    page.import_source("c")
    _wait_rows(qtbot, page, 1)
    assert page.name.text() == "Otro set"
    prompter.choose_answers = []                                       # closing the question changes nothing
    page.import_source("d")
    qtbot.waitUntil(lambda: not page._busy, timeout=5000)
    assert page.model.rowCount() == 1 and "No se ha cambiado nada" in page.banner.message()


def test_add_other_source_merges(window, qtbot, prompter, ready_services, tmp_path):
    page = window.new_set
    page.set_rows(sample_rows(), name="X")
    f = tmp_path / "otra.csv"
    f.write_text("x", encoding="utf-8")
    prompter.choose_answers = [0]
    prompter.files = [str(f)]
    page.add_source()
    _wait_rows(qtbot, page, 7)            # 4 + 3 non-ID rows of the default fake import
    assert ready_services.import_calls == [f] and ready_services.merge_calls == 1


def test_youtube_candidates(window, qtbot, ready_services):
    page = window.new_set
    alt = [TrackRow(pos=1, title="Otra", artists=["X"], artist_display="X")]
    alt_ref = SourceRef("youtube", "https://www.youtube.com/watch?v=x", "youtube_description (1 pistas)")
    cands = [FakeCandidate("Comentario de @travo1001 · 22 pistas con tiempos · 11 likes", 22, True, 11,
                           rows=sample_rows()),
             FakeCandidate("Descripción · 1 pista sin tiempos", 1, False, 0, rows=alt, source_ref=alt_ref)]
    ready_services.imports = [fake_import(kind="youtube", candidates=cands, chosen=0)]
    page.import_source("https://www.youtube.com/watch?v=x")
    _wait_rows(qtbot, page, 4)
    assert page.cand_row.isVisible() and page.cand_box.count() == 2
    assert page.cand_box.itemText(0) == "Comentario de @travo1001 · 22 pistas con tiempos · 11 likes"
    assert page.cand_box.isEnabled() and page.cand_box.currentIndex() == 0
    page._on_candidate(1)
    assert page.model.rowCount() == 1 and page.model.row_at(0).title == "Otra"
    assert page.sources == [alt_ref]
    # candidates without rows are shown but cannot be switched
    ready_services.imports = [fake_import(kind="youtube", candidates=[FakeCandidate("A", 3), FakeCandidate("B", 2)],
                                          chosen=1)]
    page.model.set_rows([])
    page.import_source("https://www.youtube.com/watch?v=y")
    _wait_rows(qtbot, page, 4)
    assert page.cand_box.currentIndex() == 1 and not page.cand_box.isEnabled()
    assert "pégala" in page.cand_hint.text()


def test_doubtful_lists_and_linked_tracklist(window, qtbot, ready_services):
    """No clear tracklist: the doubtful ones are offered in the list, plus the linked page."""
    page = window.new_set
    cands = [FakeCandidate("Comentario de @a · 5 pistas sin tiempos", 5, False, 2, rows=sample_rows())]
    ready_services.imports = [fake_import([], kind="youtube", candidates=cands, chosen=None,
                                          message_es="No he encontrado una tracklist clara.",
                                          suggested_name="Boiler Room",
                                          links=["https://www.1001tracklists.com/tracklist/x"])]
    page.import_source("https://www.youtube.com/watch?v=z")
    qtbot.waitUntil(lambda: not page._busy, timeout=5000)
    assert page.model.rowCount() == 0 and page.cand_row.isVisible() and page.cand_box.currentIndex() == -1
    btn = page.banner.actions.itemAt(0).widget()
    assert btn.text() == "Abrir la tracklist enlazada"
    btn.click()
    assert ready_services.opened_urls[-1] == "https://www.1001tracklists.com/tracklist/x"
    page._on_candidate(0)
    assert page.model.rowCount() == 4 and page.name.text() == "Boiler Room"


def test_enrichment_runs_after_import(window, qtbot, ready_services):
    ready_services.settings.enrichment_enabled = True
    page = window.new_set
    page.import_source("x")
    qtbot.waitUntil(lambda: ready_services.enrich_calls == 1 and not page._busy, timeout=10000)
    m = page.model
    assert m.data(m.index(0, m.column_of("duration"))) == "05:00"
    assert m.row_at(2).expected_duration_s is None                   # ID rows are skipped
    assert "Datos completados: 3 de 4 pistas (iTunes 3)" in page.banner.message()
    page.enrich_btn.click()                                          # "Completar datos" again
    qtbot.waitUntil(lambda: ready_services.enrich_calls == 2 and not page._busy, timeout=10000)


def test_downloads_watcher_offers_new_trackid_csv(window, qtbot, ready_services, tmp_path):
    folder = tmp_path / "Descargas"
    folder.mkdir()
    (folder / "viejo-trackid.csv").write_text("x", encoding="utf-8")    # already there: ignored
    ready_services.settings.watch_downloads_folder = True
    page = window.new_set
    assert page.start_watching(folder)
    (folder / "otra-cosa.csv").write_text("a,b\n", encoding="utf-8")
    (folder / "trackid-fjaak.csv").write_text("Pos,Start\n", encoding="utf-8")
    page.watcher.scan()
    assert "trackid-fjaak.csv" in page.watch_banner.message()
    assert "viejo" not in page.watch_banner.message()
    page.watch_banner.actions.itemAt(0).widget().click()
    _wait_rows(qtbot, page, 4)
    assert ready_services.import_calls == [folder / "trackid-fjaak.csv"]
    page.stop_watching()
    assert page.watcher is None


def test_download_needs_rows_and_a_name(window):
    page = window.new_set
    page.request_download()
    assert "Marca al menos una pista" in page.banner.message()
    page.set_rows(sample_rows(), name="")
    got = []
    page.download_requested.connect(lambda *a: got.append(a))
    page.request_download()
    assert "nombre" in page.banner.message() and got == []
    page.name.setText("Mi set")
    page.download_requested.disconnect(window.start_download)   # only the signal is checked here
    page.request_download()
    assert got and got[0][0] == "Mi set" and [r.pos for r in got[0][1]] == [1, 2, 3, 4]
    assert got[0][1][0] is not page.model.row_at(0)                    # copies, never the table's rows


@pytest.mark.parametrize("tid", ["hormigon", "noche"])
def test_new_set_renders_in_both_themes(window, tid):
    window.new_set.set_rows(sample_rows(), name="Set")
    window.themes.apply(tid)
    img = window.grab().toImage()
    assert not img.isNull()
    m = window.new_set.model
    assert m.data(m.index(3, m.column_of("status")), Qt.ItemDataRole.ForegroundRole).name() == \
        window.themes.theme.state_color("dudoso")
