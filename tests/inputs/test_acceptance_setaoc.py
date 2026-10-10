"""Acceptance on the user's real set (06 R1, R2, R5), offline: his trackid.net CSV and his YouTube list
(tests/fixtures/inputs/setaoc-*.{csv,txt}, public tracklist data) with the iTunes/Deezer/MusicBrainz
answers recorded once for them (tools/record_http_fixtures.py --rows ... --merge, 10 Oct 2026).

The flow is the window's: import the CSV, "Completar datos", recompute the gaps; then "Añadir otra
fuente del mismo set" with the YouTube list, "Completar datos" again, recompute the gaps.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tracklister.core.model import TrackRow
from tracklister.enrich.enricher import Enricher
from tracklister.inputs.gaps import clock, is_auto_gap, recompute_gaps
from tracklister.inputs.importer import import_source
from tracklister.inputs.merge import merge_sources_detailed
from tracklister.net.http import HttpClient, ReplayTransport

FIX = Path(__file__).resolve().parents[1] / "fixtures"
CSV = FIX / "inputs" / "setaoc-trackid.csv"
YOUTUBE = FIX / "inputs" / "setaoc-youtube.txt"

# Recorded durations (m:ss). The first 12 are exactly the ones his app enriched at home (06).
DURATIONS = {"Inject": "4:21", "Trip": "5:05", "Show me that light": "6:25", "Seiko": "5:32", "Hidden Reason": "5:33",
             "Dynamic": "5:19", "Velocity": "6:25", "Interchange III": "6:45", "Lx2": "7:38", "Binary Drive": "5:23",
             "Twinfall": "5:23", "Space Noise": "5:16", "Nova Voyager": "5:43", "Blind Spot": "5:45", "Space": "5:35",
             "Crux": "5:59", "Incentive Systems": "5:08", "Talitha": "4:56", "Mind Control": "6:01", "RJ": "9:43",
             "1982": "5:19"}


@pytest.fixture
def enricher(tmp_path):
    rt = ReplayTransport(FIX / "http")                 # a request without a recorded answer raises
    return Enricher(HttpClient(rt, sleep=lambda s: None), tmp_path / "enrich.json")


def _gaps(rows: list[TrackRow]) -> list[tuple[str, str, str, str]]:
    """(track before, gap start, gap end, track after) of every automatic gap row."""
    out = []
    for i, r in enumerate(rows):
        if is_auto_gap(r):
            out.append((rows[i - 1].title if i else "", clock(r.ts_start), clock(r.ts_end), rows[i + 1].title))
    return out


def _csv_completed(enricher) -> list[TrackRow]:
    rows = import_source(CSV).rows
    enricher.enrich(rows)
    res = recompute_gaps(rows)
    assert res.changed
    return res.rows


def test_r1_gaps_of_his_csv_with_the_recorded_durations(enricher):
    rows = _csv_completed(enricher)
    tracks = [r for r in rows if not r.is_id]
    assert {r.title: clock(r.expected_duration_s) for r in tracks} == DURATIONS
    # 1.0.0 gave 9 gap rows (measured from trackid's End); with the real durations there are 6
    assert _gaps(rows) == [
        ("Trip", "10:39", "14:52", "Show me that light"),          # 4:13: real unexplained time
        ("Twinfall", "55:23", "56:55", "Space Noise"),             # 1:32: his YouTube list has TR440 here
        ("Blind Spot", "1:09:01", "1:20:51", "Space"),             # 11:50: Border One at 1:18:25
        ("Crux", "1:30:02", "1:31:36", "Incentive Systems"),       # 1:34
        ("Incentive Systems", "1:36:44", "1:43:04", "Talitha"),    # 6:20: Aidan Rudd at 1:34:28
        ("Talitha", "1:48:00", "1:49:32", "Mind Control"),         # 1:32
    ]
    gone = {"Inject", "Seiko", "Hidden Reason"}
    assert not gone & {g[0] for g in _gaps(rows)}
    assert len(rows) == 27 and [r.pos for r in rows] == list(range(1, 28))
    trip_gap = next(r for r in rows if is_auto_gap(r))
    assert trip_gap.notes[0] == "4:13 sin cubrir aunque «Trip» sonara entero"


def test_r2_his_csv_plus_his_youtube_list(enricher):
    base = _csv_completed(enricher)
    youtube = import_source(YOUTUBE).rows
    assert len(youtube) == 24
    merged = merge_sources_detailed(base, youtube)
    assert len(merged.matched) == 21 and {r.source for r in base if r.uid in merged.matched} == {"trackid_csv"}
    assert merged.inserted == [] and merged.appended == []
    placed = {r.uid: r for r in merged.rows if r.uid in merged.replaced_ids}
    assert sorted((r.artist_display, r.title, clock(r.ts_start)) for r in placed.values()) == [
        ("Aidan Rudd", "Necromancer", "1:34:28"), ("Border One", "Spectral Tension", "1:18:25"),
        ("TR440", "Somewhen", "53:32")]
    # each one took the place (and the number) of the gap row of its interval
    by_title = {r.title: r for r in merged.rows}
    assert by_title["Somewhen"].pos == 13 and by_title["Spectral Tension"].pos == 17
    assert by_title["Necromancer"].pos == 22
    assert all(any(n.startswith("rellena un hueco de la tracklist base") for n in r.notes) for r in placed.values())

    enricher.enrich(merged.rows)                        # the window completes the combined table again
    final = recompute_gaps(merged.rows).rows
    real = [r for r in final if not r.is_id]
    assert len(real) == 24
    starts = [r.ts_start for r in real]
    assert starts == sorted(starts)                     # all 24 tracks in time order
    order = [r.title for r in real]
    assert order.index("Twinfall") + 1 == order.index("Somewhen") == order.index("Space Noise") - 1
    assert order.index("Blind Spot") + 1 == order.index("Spectral Tension") == order.index("Space") - 1
    assert order.index("Incentive Systems") + 1 == order.index("Necromancer") == order.index("Talitha") - 1
    # ID rows only where neither source has a track
    assert _gaps(final) == [
        ("Trip", "10:39", "14:52", "Show me that light"),
        ("Blind Spot", "1:09:01", "1:18:25", "Spectral Tension"),
        ("Crux", "1:30:02", "1:31:36", "Incentive Systems"),
        ("Necromancer", "1:40:11", "1:43:04", "Talitha"),
        ("Talitha", "1:48:00", "1:49:32", "Mind Control"),
    ]
    for g in (r for r in final if r.is_id):
        assert not any(g.ts_start + 60 < y.ts_start < g.ts_end - 60 for y in youtube)
    assert [r.pos for r in final] == list(range(1, 30))
    # E.8: trackid wins the names; the YouTube spelling stays in the notes
    space = by_title["Space"]
    assert space.artist_display == "CONFUSION (RASEREI)" and "según texto: 'Confusion - Space'" in space.notes
    assert by_title["Somewhen"].expected_duration_s is None          # no store has TR440 - Somewhen


def test_r5_store_label_credits_are_not_adopted(enricher):
    rows = {r.title: r for r in _csv_completed(enricher)}
    # iTunes credits "GCOD & KYSH Records" and "Ana Rs & Demolate Records": both are labels
    assert (rows["Incentive Systems"].artist_display, rows["Incentive Systems"].artists) == ("GCOD", ["GCOD"])
    assert (rows["Mind Control"].artist_display, rows["Mind Control"].artists) == ("Ana Rs", ["Ana Rs"])
    assert not any("artista corregido" in n for n in rows["Incentive Systems"].notes + rows["Mind Control"].notes)
    # a real co-artist is still adopted (E.24): iTunes credits Tino Machauer on Interchange III
    inter = rows["Interchange III"]
    assert inter.artist_display == "CONFUSION (RASEREI) & Tino Machauer"
    assert inter.search_artist == "CONFUSION (RASEREI)"
    youtube = {r.title: r for r in import_source(YOUTUBE).rows}           # no labels in the YouTube list
    enricher.enrich(list(youtube.values()))
    assert youtube["Incentive Systems"].artist_display == "GCOD"
    assert youtube["Mind Control"].artist_display == "Ana Rs"
