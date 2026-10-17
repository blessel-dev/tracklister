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


@pytest.mark.parametrize("text,version", [
    ("Spirit (Kai Remix) (Extended)", "Kai Remix"), ("Spirit (Kai Remix) [Extended]", "Kai Remix"),
    ("Spirit (Kai Remix) (Radio Edit)", "Kai Remix - Radio Edit"), ("Spirit (Kai Remix - Radio Edit)", "Kai Remix - Radio Edit"),
    ("Spirit (Radio Edit) (Kai Remix)", "Radio Edit - Kai Remix"), ("Spirit (Kai Remix) (Edit)", "Kai Remix - Edit"),
    ("Spirit (Kai Remix) (Remastered)", "Kai Remix - Remastered"),
    ("Spirit (feat. Jo) Extended Mix (Kai Remix)", "Kai Remix"),
    ("Spirit (feat. Jo) Kai Remix (Radio Edit)", "Kai Remix - Radio Edit")])
def test_r4_v_the_table_editor_keeps_every_version_group(window, text, version):
    """Audit round 4, second review (B1-B3): the editor gives the same version as every import path."""
    from tracklister.engine.csvwriter import engine_title
    page = window.new_set
    page.set_rows(sample_rows(), name="X")
    m = page.model
    assert m.setData(m.index(0, m.column_of("title")), text)
    r0 = m.row_at(0)
    assert (r0.title, r0.version) == ("Spirit", version) and engine_title(r0) == "Spirit (Kai Remix)"
    assert m.setData(m.index(0, m.column_of("version")), "(Kai Remix) [Radio Edit]")
    assert r0.version == "Kai Remix - Radio Edit"           # typed in the Version column: the same rule
    assert m.setData(m.index(0, m.column_of("version")), "Kai Remix (Extended Mix)") and r0.version == "Kai Remix"


def test_r4_editing_the_track_of_an_enriched_row_forgets_its_store_data(window):
    """Audit round 4 (with B1): a row corrected to another track kept the old track's duration and ids,
    so it was searched with the wrong length. Now they are cleared ('Descargar' completes them again);
    a case-only edit, the label or the start keep them, and a duration typed by the user stays."""
    from tracklister.core.model import TrackIds
    page = window.new_set
    page.set_rows(sample_rows(), name="X")
    m = page.model
    r0, r1 = m.row_at(0), m.row_at(1)
    for r in (r0, r1):
        r.expected_duration_s, r.ids, r.enrich_source = 637, TrackIds(isrc="X1"), "itunes"
    for key, value in (("title", "SPIRIT"), ("label", "Otro sello"), ("start", "0:10")):
        assert m.setData(m.index(0, m.column_of(key)), value)
        assert (r0.expected_duration_s, r0.ids.isrc, r0.enrich_source) == (637, "X1", "itunes"), key
    assert m.setData(m.index(0, m.column_of("title")), "Some Chords")
    assert (r0.expected_duration_s, r0.ids, r0.enrich_source) == (None, TrackIds(), None)
    assert m.setData(m.index(1, m.column_of("version")), "Kai Remix")
    assert (r1.expected_duration_s, r1.enrich_source) == (None, None)
    typed = m.row_at(3)
    assert m.setData(m.index(3, m.column_of("duration")), "6:00") and typed.enrich_source is None
    assert m.setData(m.index(3, m.column_of("title")), "Mercy")
    assert typed.expected_duration_s == 360                     # typed by the user: never cleared (E.23)


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


def _shortcut_keys(page) -> list[str]:
    from PySide6.QtGui import QKeySequence, QShortcut
    return [s.key().toString(QKeySequence.SequenceFormat.PortableText) for s in page.table.findChildren(QShortcut)]


def _press_on_the_table(qtbot, window, key):
    page = window.new_set
    window.activateWindow()
    page.table.setFocus()
    qtbot.waitUntil(lambda: page.table.hasFocus(), timeout=5000)
    qtbot.keyClick(page.table, key)


def test_mac_backspace_removes_the_selected_row(as_macos, window, qtbot):
    """On a Mac keyboard the «delete» key is Backspace (report 3.1 point 18)."""
    page = window.new_set
    page.set_rows(sample_rows(), name="X")
    assert "Backspace" in _shortcut_keys(page)
    gone = page.model.row_at(1).uid
    page.table.selectRow(1)
    _press_on_the_table(qtbot, window, Qt.Key.Key_Backspace)
    assert page.model.rowCount() == 3 and gone not in [r.uid for r in page.model.rows()]
    assert [r.pos for r in page.model.rows()] == [1, 2, 3]


def test_windows_backspace_removes_nothing(as_windows, window, qtbot):
    page = window.new_set
    page.set_rows(sample_rows(), name="X")
    assert "Backspace" not in _shortcut_keys(page)
    page.table.selectRow(1)
    _press_on_the_table(qtbot, window, Qt.Key.Key_Backspace)
    assert page.model.rowCount() == 4                     # unchanged: Supr (Delete) is the key on Windows


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
    cands = [FakeCandidate("Comentario de @oyente-0879 · 22 pistas con tiempos · 11 likes", 22, True, 11,
                           rows=sample_rows()),
             FakeCandidate("Descripción · 1 pista sin tiempos", 1, False, 0, rows=alt, source_ref=alt_ref)]
    ready_services.imports = [fake_import(kind="youtube", candidates=cands, chosen=0)]
    page.import_source("https://www.youtube.com/watch?v=x")
    _wait_rows(qtbot, page, 4)
    assert page.cand_row.isVisible() and page.cand_box.count() == 2
    assert page.cand_box.itemText(0) == "Comentario de @oyente-0879 · 22 pistas con tiempos · 11 likes"
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


def test_download_completes_missing_durations_first(window, qtbot, ready_services):
    """'Descargar' never sends rows without an expected duration while 'Completar datos' is on."""
    page = window.new_set
    page.download_requested.disconnect(window.start_download)   # only the signal is checked here
    got = []
    page.download_requested.connect(lambda *a: got.append(a))
    page.set_rows(sample_rows(), name="Mi set")
    assert all(r.expected_duration_s is None for r in page.model.downloadable())
    ready_services.settings.enrichment_enabled = True
    page.request_download()
    qtbot.waitUntil(lambda: bool(got), timeout=10000)
    assert ready_services.enrich_calls == 1
    sent = [r for r in got[0][1] if r.download and r.title.strip()]
    assert sent and all(r.expected_duration_s == ready_services.enrich_duration for r in sent)
    # every marked row already has a duration -> no second enrichment
    page.request_download()
    assert len(got) == 2 and ready_services.enrich_calls == 1
    # 'Completar datos' off in Ajustes -> the user's choice is respected, download straight away
    page.set_rows(sample_rows(), name="Otro set")
    ready_services.settings.enrichment_enabled = False
    page.request_download()
    assert len(got) == 3 and ready_services.enrich_calls == 1


def test_download_still_starts_when_enrichment_fails(window, qtbot, ready_services, monkeypatch):
    page = window.new_set
    page.download_requested.disconnect(window.start_download)
    got = []
    page.download_requested.connect(lambda *a: got.append(a))
    page.set_rows(sample_rows(), name="Mi set")
    ready_services.settings.enrichment_enabled = True

    def boom(rows, on_progress=None, cancel=None):
        raise RuntimeError("sin red")
    monkeypatch.setattr(ready_services, "enrich", boom)
    page.request_download()
    qtbot.waitUntil(lambda: bool(got), timeout=10000)
    assert not page._busy


@pytest.mark.parametrize("tid", ["hormigon", "noche"])
def test_new_set_renders_in_both_themes(window, tid):
    window.new_set.set_rows(sample_rows(), name="Set")
    window.themes.apply(tid)
    img = window.grab().toImage()
    assert not img.isNull()
    m = window.new_set.model
    assert m.data(m.index(3, m.column_of("status")), Qt.ItemDataRole.ForegroundRole).name() == \
        window.themes.theme.state_color("dudoso")
