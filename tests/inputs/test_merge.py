"""Combining trackid.net (base) with a YouTube comment (extra): 02 sections 4 and 5.8."""
from __future__ import annotations

import json
from pathlib import Path

from tracklister.core.model import RowStatus, TrackRow
from tracklister.inputs.clean import clean_rows
from tracklister.inputs.merge import merge_sources
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
    assert "según youtube_comment:@travo1001: 'STIPP, Sandrien - Corrie'" in stipp.notes
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


def test_review_row_in_the_base_is_corrected_by_a_strong_row():
    base = [_r("", "rob hood grey move", ts=13011, status=RowStatus.REVISAR, download=False, confidence=0.4)]
    extra = [_r("Robert Hood", "Grey Move", ts=13011, source="texto")]
    (row,) = merge_sources(base, extra)
    assert (row.artist_display, row.title, row.status, row.download) == ("Robert Hood", "Grey Move",
                                                                          RowStatus.OK, True)
    assert any(n.startswith("corregida con texto") for n in row.notes)
