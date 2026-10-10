"""Combining trackid.net (base) with a YouTube comment (extra): 02 sections 4 and 5.8."""
from __future__ import annotations

import json
from pathlib import Path

from tracklister.core.model import RowStatus, TrackRow
from tracklister.inputs.clean import clean_rows, renumber
from tracklister.inputs.merge import merge_sources, merge_sources_detailed
from tracklister.inputs.tabular import read_table
from tracklister.inputs.tlparse import to_track_rows
from tracklister.inputs.tlselect import choose
from tracklister.inputs.trackid import GAP_TITLE, parse_trackid

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _fjaak_sources() -> tuple[list[TrackRow], list[TrackRow]]:
    base = clean_rows(parse_trackid(read_table(FIX / "inputs" / "fjaak-techno-dj-set-section-may-2026.csv")))
    meta = json.loads((FIX / "youtube" / "mD9ELt_Pvp4.meta.json").read_text(encoding="utf-8"))
    best, _, merged = choose(meta)
    extra = clean_rows(to_track_rows(merged, f"youtube_comment:{best.author}", meta["webpage_url"]))
    return base, extra


def test_fjaak_trackid_plus_youtube_adds_one_track_and_four_ids():
    base, extra = _fjaak_sources()
    out = merge_sources(base, extra)
    assert [r.pos for r in out] == list(range(1, len(out) + 1))
    real = [r for r in out if not r.is_id]
    assert len(real) == 18                                      # 17 from trackid + Deas
    deas = next(r for r in out if r.artist_display == "Deas")
    assert (deas.title, deas.ts_start, deas.download) == ("Here Again", 3050, True)
    assert any(n.startswith("rellena un hueco") for n in deas.notes)
    ids = [(r.ts_start, r.artist_display, r.title) for r in out if r.is_id]
    assert ids == [(0, "ID", "ID"), (1158, "", GAP_TITLE), (1570, "ID", "ID"), (2340, "FJAAK", "ID"),
                   (2510, "ID", "ID")]
    assert len(out) == 23                                       # the 124 s gap at 00:19:18 stays
    starts = [r.ts_start for r in out]
    assert starts == sorted(starts)


def test_base_wins_on_names_and_differences_go_to_notes():
    base, extra = _fjaak_sources()
    out = merge_sources(base, extra)
    stipp = next(r for r in out if r.title == "Corrie")
    assert stipp.artist_display == "STIPP" and stipp.artists == ["STIPP"]
    assert "según youtube_comment:@oyente-0879: 'STIPP, Sandrien - Corrie'" in stipp.notes
    dextro = next(r for r in out if r.title == "Covil dos Abutres")    # 79 s apart: matched by name
    assert dextro.ts_start == 581 and dextro.source == "trackid_csv"
    blasha = next(r for r in out if r.title == "8AM in Salford")
    assert not any(n.startswith("según") for n in blasha.notes)        # "Blasha, Allatt" == "Blasha & Allatt"
    assert sum(1 for r in out if r.title == "Gunslingers") == 1


def test_merge_does_not_modify_its_inputs():
    base, extra = _fjaak_sources()
    b0, e0 = [r.to_dict() for r in base], [r.to_dict() for r in extra]
    merge_sources(base, extra)
    assert [r.to_dict() for r in base] == b0 and [r.to_dict() for r in extra] == e0


def _r(artist, title, ts=None, **kw):
    return TrackRow(pos=0, title=title, artists=[artist] if artist else [], artist_display=artist, ts_start=ts,
                    source=kw.pop("source", "tabla"), **kw)


def test_without_times_new_tracks_follow_their_neighbour():
    base = [_r("A", "One"), _r("C", "Three")]
    extra = [_r("A", "One", source="texto"), _r("B", "Two", source="texto"), _r("C", "Three", source="texto")]
    out = merge_sources(base, extra)
    assert [r.title for r in out] == ["One", "Two", "Three"]
    assert out[1].notes == ["añadida desde texto"]


def test_time_window_allows_a_weaker_name_match():
    base = [_r("Planetary Assault Systems", "Screen", ts=10976)]
    near = merge_sources(base, [_r("PAS", "Screen", ts=10980, source="texto")])     # abbreviation, +4 s
    assert len(near) == 1 and near[0].artist_display == "Planetary Assault Systems"
    assert any(n.startswith("según texto") for n in near[0].notes)
    far = merge_sources(base, [_r("PAS", "Screen", ts=10000, source="texto")])      # 16 min away
    assert len(far) == 2


def _gap(ts, end, **kw):
    return TrackRow(pos=0, title=GAP_TITLE, artists=[], artist_display="", ts_start=ts, ts_end=end, is_id=True,
                    status=RowStatus.ID, download=False, confidence=0.0, source="trackid_csv", **kw)


def _base_with_gap():
    return renumber([_r("A", "Uno", ts=0, source="trackid_csv"), _r("B", "Dos", ts=300, source="trackid_csv"),
                     _gap(700, 1000), _r("C", "Tres", ts=1000, source="trackid_csv"),
                     _r("D", "Cuatro", ts=1400, source="trackid_csv")])


def test_r2_a_track_takes_the_id_row_of_its_interval_and_its_number():
    base = _base_with_gap()
    # 05:00-16:40 holds the gap; 06:10 is outside the gap's own span (11:40-16:40, +-60 s): nearest one
    res = merge_sources_detailed(base, [_r("X", "Nueva", ts=370, source="texto")])
    assert [r.title for r in res.rows] == ["Uno", "Dos", "Nueva", "Tres", "Cuatro"]
    new = res.rows[2]
    assert new.pos == 3 == base[2].pos and res.replaced_ids == [new.uid] and res.inserted == []
    assert new.notes == ["rellena un hueco de la tracklist base (00:11:40-00:16:40)"]
    assert [r.pos for r in res.rows] == [r.pos for r in base]                 # nobody else moves


def test_r2_with_no_id_row_the_track_is_inserted_by_time():
    base = _base_with_gap()
    res = merge_sources_detailed(base, [_r("X", "Nueva", ts=1200, source="texto")])   # between Tres and Cuatro
    assert [r.title for r in res.rows] == ["Uno", "Dos", GAP_TITLE, "Tres", "Nueva", "Cuatro"]
    assert res.inserted == [res.rows[4].uid] and res.replaced_ids == [] and res.rows[5].pos == 6
    assert res.rows[4].notes == ["añadida desde texto"]
    last = merge_sources_detailed(base, [_r("X", "Final", ts=2000, source="texto")])
    assert last.rows[-1].title == "Final" and last.appended == [last.rows[-1].uid] and last.inserted == []


def test_r2_keep_positions_appends_and_no_number_changes():
    base = _base_with_gap()
    res = merge_sources_detailed(base, [_r("X", "Nueva", ts=1200, source="texto"),
                                        _r("Y", "Otra", ts=360, source="texto")], keep_positions=True)
    assert [r.title for r in res.rows] == ["Uno", "Dos", "Otra", "Tres", "Cuatro", "Nueva"]
    assert [(r.uid, r.pos) for r in res.rows[:5] if r.title != "Otra"] == [
        (b.uid, b.pos) for b in base if b.title != GAP_TITLE]                 # every base number kept
    appended = res.rows[-1]
    assert res.appended == [appended.uid] and res.inserted == [] and res.replaced_ids == [res.rows[2].uid]
    assert appended.notes == ["añadida al final para no cambiar números: en el set va después de «Tres»"]


def test_r2_rows_of_the_other_source_never_replace_each_other_and_keep_time_order():
    base = [_r("A", "Uno", ts=0, source="trackid_csv"), _gap(400, 900), _r("B", "Dos", ts=900, source="trackid_csv")]
    extra = [_r("X", "Segunda", ts=700, source="texto"), _r("Y", "Primera", ts=450, source="texto"),
             TrackRow(pos=0, title="ID", artist_display="ID", is_id=True, status=RowStatus.ID, download=False,
                      ts_start=800, source="texto")]
    out = merge_sources(base, extra)
    assert [r.title for r in out] == ["Uno", "Primera", "Segunda", "ID", "Dos"]
    assert [r.ts_start for r in out] == [0, 450, 700, 800, 900]
    assert [r.pos for r in out] == [1, 2, 3, 4, 5]


def test_r2_merge_sources_is_the_detailed_rows():
    base, extra = _fjaak_sources()
    detailed = merge_sources_detailed(base, extra)
    assert [r.to_dict() | {"uid": ""} for r in merge_sources(base, extra)] == \
        [r.to_dict() | {"uid": ""} for r in detailed.rows]
    # 17 trackid tracks matched; Deas and two YouTube ID rows take trackid gaps; the IDs at 0:00 and
    # 41:50 have no gap in their interval and are inserted
    assert len(detailed.matched) == 17 and len(detailed.replaced_ids) == 3 and len(detailed.inserted) == 2


def test_review_row_in_the_base_is_corrected_by_a_strong_row():
    base = [_r("", "rob hood grey move", ts=13011, status=RowStatus.REVISAR, download=False, confidence=0.4)]
    extra = [_r("Robert Hood", "Grey Move", ts=13011, source="texto")]
    (row,) = merge_sources(base, extra)
    assert (row.artist_display, row.title, row.status, row.download) == ("Robert Hood", "Grey Move",
                                                                          RowStatus.OK, True)
    assert any(n.startswith("corregida con texto") for n in row.notes)
