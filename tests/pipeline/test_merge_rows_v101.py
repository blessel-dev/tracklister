"""1.0.1 R5 (rename part): a row whose artists only changed is the same track; any other edit is not (R4-B1).

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import json
import threading

from tests.fakes.scenarios import file, row
from tracklister.core.model import ResultState, RowResult, RowStatus, SetDoc, SourceRef, TrackRow
from tracklister.core.paths import app_paths
from tracklister.core.settings import Settings
from tracklister.engine.credentials import Credentials
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.runner import EngineRunner
from tracklister.engine.spec import fake_engine_spec
from tracklister.library.index import LibraryIndex
from tracklister.pipeline.session import SetSession, _merge_rows

CREDS = Credentials("usuario-prueba", "clave-prueba")


def _r(pos, artist, title, version=None, artists=None, **kw):
    return TrackRow(pos=pos, title=title, artists=artists or [a.strip() for a in artist.split("&")],
                    artist_display=artist, version=version, **kw)


def _doc(*rows):
    return SetDoc(set_id="s1", name="Set", preset_id="lossless", rows=list(rows),
                  results={r.uid: RowResult(r.uid, r.pos, ResultState.VERIFICADO, file=f"{r.pos:02d} - x.flac")
                           for r in rows})


def _edited(old: TrackRow, **changes) -> TrackRow:
    """The same row edited in Nuevo set (it keeps the uid it had in the table)."""
    return TrackRow.from_dict({**old.to_dict(), **changes})


def test_r5_only_the_artists_changed_keeps_the_track():
    cases = [
        (_r(1, "KYSH Records & GCOD", "Incentive Systems"), {"artist_display": "GCOD", "artists": ["GCOD"]}),
        (_r(1, "GCOD & KYSH Records", "Incentive Systems"), {"artist_display": "GCOD", "artists": ["GCOD"]}),
        (_r(1, "Ana Rs & Demolate Records", "Mind Control"), {"artist_display": "Ana Rs", "artists": ["Ana Rs"]}),
        (_r(1, "Allatt & Blasha", "8AM in Salford"), {"artist_display": "Blasha & Allatt",
                                                       "artists": ["Blasha", "Allatt"]}),
        (_r(1, "STIPP", "Corrie"), {"artist_display": "STIPP & Sandrien", "artists": ["STIPP", "Sandrien"]}),
        (_r(1, "Komplex aka Jeroen Search", "Inject", artists=["Komplex aka Jeroen Search"]),
         {"artist_display": "Jeroen Search", "artists": ["Jeroen Search"]}),
        (_r(1, "Fjaak", "Spirit", "Kai Remix - Radio Edit"),
         {"artist_display": "Fjaak & Kobosil", "artists": ["Fjaak", "Kobosil"], "version": "Radio Edit - Kai Remix"}),
    ]
    for old, change in cases:
        new = _edited(old, **change, uid="otro-uid")
        doc = _doc(old)
        _merge_rows(doc, [new])
        assert new.uid == old.uid and old.uid in doc.results, (old.artist_display, change)


def test_r5_any_other_edit_is_another_track():
    """R4-B1 stays: another title, version or artist gets a new uid (its old result is dropped)."""
    old = _r(1, "Adam Beyer", "Rush", "Kai Remix")
    for change in ({"title": "Rush Hour"}, {"version": "Other Remix"}, {"version": None},
                   {"artist_display": "Adam Port", "artists": ["Adam Port"]},
                   {"artist_display": "Ken Faki", "artists": ["Ken Faki"]}):
        new = _edited(old, **change)
        doc = _doc(old)
        _merge_rows(doc, [new])
        assert new.uid != old.uid and old.uid not in doc.results, change


def test_r5_two_old_rows_that_fit_are_no_match():
    a, b = _r(1, "KYSH Records & GCOD", "Incentive Systems"), _r(2, "Otro & GCOD", "Incentive Systems")
    new = _r(1, "GCOD", "Incentive Systems")
    doc = _doc(a, b)
    _merge_rows(doc, [new, _r(2, "Otra Gente", "Otra Pista")])
    assert new.uid not in (a.uid, b.uid)


def test_r5_an_identified_id_row_is_a_new_track():
    idr = TrackRow(pos=3, title="ID", artist_display="ID", is_id=True, status=RowStatus.ID, download=False)
    new = _edited(idr, title="Necromancer", artist_display="Aidan Rudd", artists=["Aidan Rudd"], is_id=False,
                  status="ok", download=True)
    doc = _doc(idr)
    _merge_rows(doc, [new])
    assert new.uid != idr.uid


def test_r5_end_to_end_the_first_artist_removed_renames_without_downloading(tmp_path):
    """A 1.0.1 set: the store credited the label FIRST ('KYSH Records & GCOD'), so the old library key was
    another artist's; the edit to 'GCOD' still renames the file and downloads nothing."""
    paths = app_paths().ensure()
    net = tmp_path / "net.json"
    net.write_text(json.dumps({"schema": "tracklister.fakenet/1", "search_delay_ms": 0, "ban_after_searches": None,
                               "peers": {}, "files": [file("peerA", "@@x\\KYSH\\KYSH Records & GCOD - Incentive Systems.flac",
                                                          "KYSH Records & GCOD", "Incentive Systems", 20)]}),
                   encoding="utf-8")
    runner = EngineRunner(fake_engine_spec(), SearchBudget(paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    settings = Settings(preset_id="lossless", library_root=str(tmp_path / "lib"))
    first = row(1, "KYSH Records & GCOD", "Incentive Systems", dur=20)
    s = SetSession.create("Set R5", [first], [SourceRef("tabla", "t.csv")], settings, tmp_path / "lib", paths)
    s.run(runner, CREDS, lambda e: None, threading.Event(), lambda rows: set())
    lib = LibraryIndex(paths.library_file)
    s.finalize(lib)
    assert s.doc.results[first.uid].file == "01 - KYSH Records & GCOD - Incentive Systems.flac"
    edited = _edited(first, artist_display="GCOD", artists=["GCOD"])
    s2 = SetSession.create("Set R5", [edited], [], settings, tmp_path / "lib", paths)
    s2.run(runner, CREDS, lambda e: None, threading.Event(), lambda rows: set())
    s2.finalize(lib)
    assert len(s2.doc.passes) == 1 and s2.doc.results[edited.uid].file == "01 - GCOD - Incentive Systems.flac"
    assert (s2.set_dir / "01 - GCOD - Incentive Systems.flac").is_file()
    assert [e.key for e in lib.entries] == ["gcod|incentive systems|original"]
