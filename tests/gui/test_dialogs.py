"""Duplicate dialog (both options + 'Aplicar a todos...') and the lossy checklist.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from tests.gui.fakes import sample_rows
from tracklister.core.model import DuplicateChoice, LibraryEntry
from tracklister.engine.presets import build_preset
from tracklister.gui.dialogs import (APPLY_ALL_TEXT, DOWNLOAD_TEXT, REUSE_TEXT, DuplicateDialog, LossyDialog,
                                     lossless_words, lossy_kbps)
from tracklister.gui.theme import load_theme
from tracklister.pipeline.session import DuplicateHit

pytestmark = pytest.mark.gui


def _hit(tmp_path, n: int = 1) -> DuplicateHit:
    row = sample_rows()[0]
    entries = []
    for i in range(n):
        p = tmp_path / f"Set {i}" / "01 - Fjaak - Spirit.flac"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        entries.append(LibraryEntry(key="fjaak|spirit|original", artist_norm="fjaak", title_norm="spirit",
                                    version_kind="original", path=str(p), set_id=f"s{i}", set_name=f"Set {i}",
                                    pos=i + 1, duration_s=301.0, format="flac", size=1))
    return DuplicateHit(row, entries)


def test_exact_texts():
    assert REUSE_TEXT == "Usar el que ya tengo (copiar a este set)"
    assert DOWNLOAD_TEXT == "Descargar de nuevo en este set"
    assert APPLY_ALL_TEXT == "Aplicar a todos los repetidos de este set"


@pytest.mark.parametrize("tid", ["hormigon", "noche"])
def test_duplicate_dialog_reuse_and_apply_all(qtbot, app, tmp_path, tid):
    hit = _hit(tmp_path)
    dlg = DuplicateDialog(hit, load_theme(tid), index=1, total=3)
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg.reuse_btn.text() == REUSE_TEXT and dlg.download_btn.text() == DOWNLOAD_TEXT
    assert dlg.apply_all.text() == APPLY_ALL_TEXT and dlg.apply_all.isVisible()
    assert "01. Fjaak - Spirit" in dlg.title.text()
    assert not dlg.entry_box.isVisible()                 # a single copy: nothing to choose
    assert not dlg.grab().isNull()
    dlg.apply_all.setChecked(True)
    dlg.reuse_btn.click()
    assert dlg.result_tuple() == (DuplicateChoice.REUSE, hit.entries[0], True)


def test_duplicate_dialog_two_copies_and_download(qtbot, app, tmp_path):
    hit = _hit(tmp_path, 2)
    dlg = DuplicateDialog(hit, load_theme("hormigon"), index=1, total=1)
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg.entry_box.isVisible() and dlg.entry_box.count() == 2
    assert not dlg.apply_all.isVisible()                 # the only repeated track of the set
    dlg.entry_box.setCurrentIndex(1)
    assert dlg.path.text() == hit.entries[1].path
    assert dlg.entry() is hit.entries[1]
    dlg.download_btn.click()
    assert dlg.result_tuple() == (DuplicateChoice.DOWNLOAD, None, False)


def test_duplicate_dialog_closed_answers_nothing(qtbot, app, tmp_path):
    dlg = DuplicateDialog(_hit(tmp_path), load_theme("noche"))
    qtbot.addWidget(dlg)
    dlg.reject()
    assert dlg.result_tuple() is None


def test_lossy_checklist(qtbot, app):
    rows = sample_rows()
    dlg = LossyDialog(rows[:2], build_preset("lossless"))
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg.list.count() == 2 and dlg.checked_uids() == {rows[0].uid, rows[1].uid}   # all checked by default
    assert dlg.yes_btn.text() == "Buscar en MP3 320 las marcadas"
    assert dlg.no_btn.text() == "No, dejarlas sin descargar"
    texts = [lb.text() for lb in dlg.findChildren(QLabel)]
    assert "Estas pistas no están en FLAC, WAV ni AIFF" in texts
    dlg.list.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert dlg.checked_uids() == {rows[1].uid}
    dlg._set_all(False)
    assert dlg.checked_uids() == set()
    dlg._set_all(True)
    assert len(dlg.checked_uids()) == 2


def test_lossy_words_per_preset():
    assert lossless_words(build_preset("lossless")) == "FLAC, WAV ni AIFF"
    assert lossless_words(build_preset("cdj_antiguos")) == "AIFF, WAV ni FLAC"
    assert lossy_kbps(build_preset("lossless")) == 320
