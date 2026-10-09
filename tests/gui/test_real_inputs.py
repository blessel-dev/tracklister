"""The window with the REAL importer (inputs.importer, frozen interface) on the sample trackid CSV.

SPDX-License-Identifier: GPL-3.0-or-later

Offline: a trackid.net CSV and pasted text need no network. Enrichment stays off here.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from tests.gui.fakes import FakeServices
from tracklister.gui.services import Services

pytestmark = pytest.mark.gui
SAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "inputs" / "fjaak-techno-dj-set-section-may-2026.csv"


class RealImportServices(FakeServices):
    import_source = Services.import_source
    merge_rows = Services.merge_rows
    is_trackid_csv = Services.is_trackid_csv


@pytest.fixture
def real_services(ready_services, tmp_path):
    s = RealImportServices(library_root=tmp_path / "biblioteca")
    s.settings = ready_services.settings
    return s


@pytest.fixture
def real_window(qtbot, app, real_services, prompter):
    from tracklister.gui.app import build_window
    w = build_window(real_services, app=app, prompter=prompter)
    qtbot.addWidget(w)
    w.show()
    yield w
    w.pool.wait_all(10000)


@pytest.mark.skipif(not SAMPLE.is_file(), reason="INPUTS fixture not present")
def test_sample_trackid_csv_through_the_real_importer(real_window, qtbot, real_services):
    page = real_window.new_set
    page.import_source(SAMPLE)
    qtbot.waitUntil(lambda: not page._busy and page.model.rowCount() > 0, timeout=20000)
    m = page.model
    rows = m.rows()
    assert [r.pos for r in rows] == list(range(1, len(rows) + 1))
    ids = [r for r in rows if r.is_id]
    assert len(rows) - len(ids) == 17 and ids                           # 17 tracks + the "ID (hueco)" rows
    dl = m.column_of("download")
    for i, r in enumerate(rows):
        expected = Qt.CheckState.Unchecked if r.is_id else Qt.CheckState.Checked
        assert m.data(m.index(i, dl), Qt.ItemDataRole.CheckStateRole) == expected
    assert page.name.text() == SAMPLE.stem
    assert page.sources and page.sources[0].ref == SAMPLE.name
    assert "trackid.net" in page.banner.message()
    roll = next(r for r in rows if r.title.startswith("The Red House"))
    assert roll.artist_display == "Roll Dann"                            # label removed from the artist
    assert real_services.is_trackid_csv(SAMPLE)


def test_pasted_text_through_the_real_importer(real_window, qtbot):
    page = real_window.new_set
    page.paste.setPlainText("00:00 Fjaak - Spirit\n05:12 Chris Liebing - Higher Things (FJAAK Remix)\n"
                            "10:40 ID - ID")
    page.read_paste()
    qtbot.waitUntil(lambda: not page._busy and page.model.rowCount() == 3, timeout=20000)
    r2 = page.model.row_at(1)
    assert (r2.artist_display, r2.title, r2.version, r2.ts_start) == ("Chris Liebing", "Higher Things",
                                                                     "FJAAK Remix", 312)
    assert page.model.row_at(2).is_id and not page.model.row_at(2).download
