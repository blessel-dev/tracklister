"""Reordenar carpeta existente: mandatory preview, ambiguous rows unchecked, apply, undo.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

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


def test_tracklist_from_new_set_table(window):
    window.go("reorder")
    page = window.reorder
    page.use_table()
    assert "vacía" in page.banner.message()
    window.new_set.set_rows(sample_rows(), name="X")
    page.use_table()
    assert len(page.rows) == 4 and "tabla de Nuevo set" in page.source.summary.text()
