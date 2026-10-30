"""Reordenar carpeta existente: mandatory preview, ambiguous rows unchecked, apply, undo.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt

from tests.gui.fakes import sample_rows

pytestmark = pytest.mark.gui
CHECK = Qt.ItemDataRole.CheckStateRole


def _folder(tmp_path, names):
    d = tmp_path / "carpeta vieja"
    d.mkdir()
    for n in names:
        (d / n).write_bytes(n.encode("utf-8"))
    return d


def _propose(qtbot, page, folder, rows):
    page.folder.setText(str(folder))
    page.set_tracklist(rows, "prueba")
    assert page.propose_btn.isEnabled()
    page.propose()
    qtbot.waitUntil(lambda: page.model.rowCount() > 0, timeout=10000)


def test_preview_apply_and_undo(window, qtbot, prompter, tmp_path):
    folder = _folder(tmp_path, ["Fjaak - Spirit.mp3", "05. Chris Liebing - Higher Things (FJAAK Remix).flac",
                                "Duffy - Mercy.mp3"])
    window.go("reorder")
    page = window.reorder
    _propose(qtbot, page, folder, sample_rows()[:2])
    m = page.model
    by_status = {}
    for p in m.proposals():
        by_status.setdefault(p.status, []).append(p)
    assert len(by_status["match"]) == 2 and len(by_status["extra"]) == 1
    assert m.checked_count() == 2 and page.apply_btn.text() == "Aplicar cambios (2)"
    names = {m.data(m.index(i, 3)) for i in range(m.rowCount())}
    assert {"01 - Fjaak - Spirit.mp3", "02 - Chris Liebing - Higher Things (FJAAK Remix).flac"} <= names
    assert list(folder.iterdir()).__len__() == 3                     # nothing renamed by the preview
    prompter.confirm_answer = True
    page.apply()
    qtbot.waitUntil(lambda: page.undo_btn.isEnabled(), timeout=10000)
    assert (folder / "01 - Fjaak - Spirit.mp3").exists()
    assert (folder / "02 - Chris Liebing - Higher Things (FJAAK Remix).flac").exists()
    assert (folder / "Duffy - Mercy.mp3").exists()                  # extra file left as it was
    assert "2 archivos renombrados" in page.banner.message()
    page.undo()
    assert (folder / "Fjaak - Spirit.mp3").exists() and not (folder / "01 - Fjaak - Spirit.mp3").exists()
    assert (folder / "05. Chris Liebing - Higher Things (FJAAK Remix).flac").exists()
    assert not page.undo_btn.isEnabled() and "Deshecho" in page.banner.message()


def test_ambiguous_rows_start_unchecked(window, qtbot, prompter, tmp_path):
    folder = _folder(tmp_path, ["Fjaak - Spirit.mp3", "01 Fjaak - Spirit.mp3"])
    page = window.reorder
    _propose(qtbot, page, folder, sample_rows()[:1])
    m = page.model
    i = next(i for i, p in enumerate(m.proposals()) if p.pos == 1)
    assert m.proposals()[i].status == "ambiguous"
    assert m.data(m.index(i, 0), CHECK) == Qt.CheckState.Unchecked and m.checked_count() == 0
    assert not page.apply_btn.isEnabled()
    assert m.setData(m.index(i, 0), Qt.CheckState.Checked, CHECK)
    chosen = [p for p in m.chosen() if p.pos == 1]
    assert chosen[0].status == "match" and page.apply_btn.isEnabled()
    prompter.confirm_answer = False                                  # 'Cancelar' in the confirmation
    page.apply()
    assert (folder / "Fjaak - Spirit.mp3").exists() and (folder / "01 Fjaak - Spirit.mp3").exists()


def test_r2_b4_apply_renames_only_the_previewed_folder(window, qtbot, prompter, tmp_path):
    """Audit round 2, B4: preview folder A, then type folder B in the field: the proposals go, nothing can
    be applied until a new preview, and a preview that arrives for another folder is never shown."""
    a = _folder(tmp_path, ["Fjaak - Spirit.mp3"])
    b = tmp_path / "otra carpeta"
    b.mkdir()
    (b / "Fjaak - Spirit.mp3").write_bytes(b"b")
    window.go("reorder")
    page = window.reorder
    _propose(qtbot, page, a, sample_rows()[:1])
    assert page.preview_folder == a and page.model.checked_count() == 1 and page.apply_btn.isEnabled()
    page.folder.setText(str(b))
    assert page.model.rowCount() == 0 and page.preview_folder is None and not page.apply_btn.isEnabled()
    page.apply()
    assert (a / "Fjaak - Spirit.mp3").exists() and (b / "Fjaak - Spirit.mp3").exists()
    assert not [c for c in prompter.calls if c[0] == "confirm"]
    page.folder.setText(str(a))
    page._on_proposed(window.services.propose_reorder(b, page.rows), b)     # late answer for B
    assert page.model.rowCount() == 0 and page.preview_folder is None
    _propose(qtbot, page, a, sample_rows()[:1])
    prompter.confirm_answer = True
    page.apply()
    qtbot.waitUntil(lambda: page.undo_btn.isEnabled(), timeout=10000)
    assert str(a) in [c for c in prompter.calls if c[0] == "confirm"][-1][2]
    assert (a / "01 - Fjaak - Spirit.mp3").exists() and (b / "Fjaak - Spirit.mp3").exists()
    assert window.services.can_undo_reorder(a) and not window.services.can_undo_reorder(b)


def test_tracklist_from_new_set_table(window):
    window.go("reorder")
    page = window.reorder
    page.use_table()
    assert "vacía" in page.banner.message()
    window.new_set.set_rows(sample_rows(), name="X")
    page.use_table()
    assert len(page.rows) == 4 and "tabla de Nuevo set" in page.source.summary.text()


def test_reordenar_refuses_the_folder_of_the_running_download(window, qtbot, ready_services, prompter, tmp_path,
                                                             monkeypatch):
    """Barrido CL-09: during a download of a set, «Reordenar» on that set's own folder renamed files under the
    download (its results then named old files), and the two undo journals overwrote each other's batches.
    «Ver propuesta», «Aplicar cambios» and «Deshacer el último reordenado» refuse that folder now; another folder
    works as before."""
    from tracklister.gui.main_window import MainWindow
    from tracklister.gui.pages.reorder import RUNNING_SET_ES
    from tracklister.organize.reorder import ReorderProposal
    calls = []
    monkeypatch.setattr(ready_services, "apply_reorder", lambda f, props: calls.append(("apply", Path(f))) or "b")
    monkeypatch.setattr(ready_services, "undo_reorder", lambda f: calls.append(("undo", Path(f))) or [])
    monkeypatch.setattr(ready_services, "propose_reorder", lambda f, rows: calls.append(("propose", Path(f))) or [])
    running = _folder(tmp_path, ["a.flac"])
    window.go("reorder")
    page = window.reorder

    def preview(folder):
        page.folder.setText(str(folder))
        page.preview_folder = folder
        page.model.set_proposals([ReorderProposal("u1", 1, folder / "a.flac", folder / "01 - X - A.flac", 90.0,
                                                  "match", "Coincide 90%.")])
    page.set_tracklist(sample_rows(), "X")
    preview(running)
    window.session = SimpleNamespace(set_dir=running)
    monkeypatch.setattr(MainWindow, "worker_running", lambda self: True)
    prompter.confirm_answer = True
    try:
        page.apply()
        page.undo()
        page.propose()
        qtbot.wait(300)
        assert calls == []
        assert not [c for c in prompter.calls if c[0] == "confirm"]
        assert page.banner.message() == RUNNING_SET_ES
        other = tmp_path / "otra carpeta"
        other.mkdir()
        (other / "a.flac").write_bytes(b"a")
        preview(other)                                       # another folder during the download: as before
        page.apply()
        qtbot.waitUntil(lambda: calls == [("apply", other)], timeout=10000)
    finally:
        monkeypatch.undo()          # no download runs when the window closes after the test
        window.session = None
