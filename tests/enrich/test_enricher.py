"""Enricher on the sample set with recorded answers: durations, version rule, corrections, cache."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from tracklister.core.model import RowStatus, TrackIds, TrackRow
from tracklister.enrich.enricher import CACHE_SCHEMA, EMPTY_RESULT_TTL_S, Enricher, cache_key
from tracklister.enrich.providers import Candidate, MusicBrainzProvider
from tracklister.inputs.importer import import_source
from tracklister.net.http import HttpClient, HttpError, ReplayMiss, ReplayTransport

FIX = Path(__file__).resolve().parents[1] / "fixtures"
SAMPLE = FIX / "inputs" / "fjaak-techno-dj-set-section-may-2026.csv"

# recorded on 2026-10-09 (tools/record_http_fixtures.py): iTunes answered every track first
EXPECTED_S = {"8AM in Salford": 361, "Grey Ribbon": 333, "Visions": 286, "The Red House": 340,
              "Covil dos Abutres": 310, "Last Ray": 334, "Zoned Out": 295, "No Money No Problems": 306,
              "I'm Still Here": 282, "Dust 1": 290, "Corrie": 357, "Gunslingers": 327, "Glaður Og Reifur": 303,
              "Zona Neutra": 308, "Caballero": 338, "Duff": 304, "Higher Things": 289}


@pytest.fixture
def replay():
    rt = ReplayTransport(FIX / "http")
    return HttpClient(rt, sleep=lambda s: None), rt


def _sample_rows() -> list[TrackRow]:
    return import_source(SAMPLE).rows


def test_sample_set_gets_durations_from_itunes(replay, tmp_path):
    http, rt = replay
    rows = _sample_rows()
    progress = []
    outcomes = Enricher(http, tmp_path / "enrich.json").enrich(rows, on_progress=lambda d, t: progress.append((d, t)))
    assert len(outcomes) == 21 and progress[-1] == (21, 21)
    tracks = [r for r in rows if not r.is_id]
    assert {r.title: r.expected_duration_s for r in tracks} == EXPECTED_S
    assert all(r.enrich_source == "itunes" and r.confidence == 0.9 and r.ids.itunes for r in tracks)
    gaps = [o for r, o in zip(rows, outcomes) if r.is_id]
    assert len(gaps) == 4 and all(not o.accepted and o.provider is None for o in gaps)
    assert all(r.expected_duration_s is None for r in rows if r.is_id)
    assert {r.host for r in rt.calls} == {"itunes.apple.com"}       # first accepted wins: nothing else asked
    assert len(rt.calls) == 17


def test_remix_duration_is_the_remix_not_the_original(replay, tmp_path):
    http, _ = replay
    liebing = next(r for r in _sample_rows() if r.title == "Higher Things")
    assert liebing.version == "FJAAK Remix"
    (o,) = Enricher(http, tmp_path / "e.json").enrich([liebing])
    assert o.accepted and liebing.expected_duration_s == 289            # 4:49, the FJAAK Remix
    assert o.note_es == "iTunes: 4:49 (Chris Liebing - Higher Things (FJAAK Remix))."
    only_mb = next(r for r in _sample_rows() if r.title == "Higher Things")
    (o,) = Enricher(http, tmp_path / "mb.json", providers=[MusicBrainzProvider(http)]).enrich([only_mb])
    assert not o.accepted and only_mb.expected_duration_s is None       # MusicBrainz only has the original (4:58)
    assert "Solo aparece otra versión: 'Chris Liebing - Higher Things'" in o.note_es
    assert only_mb.enrich_source is None and only_mb.confidence == 0.7


def test_label_as_co_artist_is_corrected(replay, tmp_path):
    http, _ = replay
    raw = TrackRow(pos=4, title="The Red House", artists=["Roll Dann", "Laster Records"],
                   artist_display="Roll Dann, Laster Records", label="LASTER RECORDS", source="trackid_csv")
    (o,) = Enricher(http, tmp_path / "e.json").enrich([raw])
    assert o.accepted and "artist" in o.changed
    assert (raw.artist_display, raw.artists, raw.search_artist) == ("Roll Dann", ["Roll Dann"], "Roll Dann")
    assert "artista corregido con iTunes: antes 'Roll Dann, Laster Records'" in raw.notes
    assert raw.expected_duration_s == 340


def test_store_credit_completes_the_artist_but_keeps_the_search_artist(replay, tmp_path):
    http, _ = replay
    stipp = next(r for r in _sample_rows() if r.title == "Corrie")
    Enricher(http, tmp_path / "e.json").enrich([stipp])
    assert stipp.artist_display == "STIPP & Sandrien" and stipp.search_artist == "STIPP"
    grid = next(r for r in _sample_rows() if r.title == "No Money No Problems")
    (o,) = Enricher(http, tmp_path / "e2.json").enrich([grid])
    assert grid.artist_display == "OFF / GRID" and "artist" not in o.changed   # "Off Grid": same name


@pytest.mark.parametrize("label", ["KYSH", None])
def test_r5_a_label_credited_by_the_store_is_never_adopted(replay, tmp_path, label):
    """06 R5, his set: iTunes credits "GCOD & KYSH Records" (recorded answer). 1.0.0 named the file
    "19 - GCOD & KYSH Records - Incentive Systems.flac". With the trackid label "KYSH" or without any
    label (his YouTube list) it stays "GCOD"."""
    http, _ = replay
    row = TrackRow(pos=19, title="Incentive Systems", artists=["GCOD"], artist_display="GCOD", label=label)
    (o,) = Enricher(http, tmp_path / "e.json").enrich([row])
    assert o.accepted and o.provider == "itunes" and row.expected_duration_s == 308
    assert "GCOD & KYSH Records" in o.note_es                     # what the store says, for the record
    assert (row.artist_display, row.artists) == ("GCOD", ["GCOD"]) and "artist" not in o.changed
    ana = TrackRow(pos=22, title="Mind Control", artists=["Ana Rs"], artist_display="Ana Rs")
    (o,) = Enricher(http, tmp_path / "e2.json").enrich([ana])
    assert "Ana Rs & Demolate Records" in o.note_es and ana.artist_display == "Ana Rs"


class _Store:
    """One provider that answers with a fixed store credit (and maybe the store's own label)."""
    name = "deezer"

    def __init__(self, artist: str, label: str | None = None):
        self.c = Candidate("deezer", artist, "Track", None, 300, TrackIds(deezer="1"), None, label)

    def search(self, artist, title):
        return [self.c]


@pytest.mark.parametrize("store,label,expected", [
    ("Artista & Sello Ejemplo Recordings", None, "Artista"),             # label-shaped: Recordings
    ("Artista & Ejemplo Rec.", None, "Artista"),                         # "Rec."
    ("Artista & Casa Ejemplo Label", None, "Artista"),
    ("Artista & Ejemplo Records Ltd", None, "Artista"),
    ("Artista & Ejemplo", "Ejemplo", "Artista"),                         # the store's own label field
    ("Artista & Otra Persona", None, "Artista & Otra Persona"),          # a real co-artist (E.24)
    ("Artista & Ejemplo Music", None, "Artista & Ejemplo Music"),        # "Music" also ends artist names
])
def test_r5_label_shapes_and_the_stores_own_label(tmp_path, store, label, expected):
    row = TrackRow(pos=1, title="Track", artists=["Artista"], artist_display="Artista")
    Enricher(HttpClient(lambda r: None), tmp_path / "e.json", providers=[_Store(store, label)]).enrich([row])
    assert row.artist_display == expected and row.search_artist == "Artista"


def test_r5_the_first_store_artist_always_stays(tmp_path):
    """A credit that starts with a label-shaped name is not the row's artist: nothing changes."""
    row = TrackRow(pos=1, title="Track", artists=["Artista"], artist_display="Artista")
    (o,) = Enricher(HttpClient(lambda r: None), tmp_path / "e.json",
                    providers=[_Store("Ejemplo Records & Artista")]).enrich([row])
    assert o.accepted and row.artist_display == "Artista" and "artist" not in o.changed


def test_candidate_label_round_trips_and_old_cache_entries_load():
    c = Candidate("itunes", "A", "T", None, 100, TrackIds(itunes="9"), "Album", "Sello")
    assert Candidate.from_dict(c.to_dict()) == c
    old = {k: v for k, v in c.to_dict().items() if k != "label"}           # a 1.0.0 cache entry
    assert Candidate.from_dict(old).label is None


def test_review_row_confirmed_becomes_downloadable(replay, tmp_path):
    http, _ = replay
    row = TrackRow(pos=1, title="Gunslingers", artists=["Klint"], artist_display="Klint", status=RowStatus.REVISAR,
                   download=False, confidence=0.4, notes=["3+ partes: revisar"])
    (o,) = Enricher(http, tmp_path / "e.json").enrich([row])
    assert (row.status, row.download, row.confidence) == (RowStatus.OK, True, 0.9)
    assert {"status", "download"} <= set(o.changed) and "confirmada con iTunes" in row.notes


def test_cache_hit_sends_no_request(replay, tmp_path):
    http, rt = replay
    cache = tmp_path / "cache" / "enrich.json"
    Enricher(http, cache).enrich(_sample_rows())
    n = len(rt.calls)
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data["schema"] == CACHE_SCHEMA
    assert cache_key("itunes", "Phara", "Grey Ribbon") in data["entries"]
    rows = _sample_rows()
    Enricher(http, cache).enrich(rows)                                   # a new window/session
    assert len(rt.calls) == n
    assert {r.title: r.expected_duration_s for r in rows if not r.is_id} == EXPECTED_S


def test_empty_results_are_asked_again_after_a_week(tmp_path):
    class Counting:
        name = "itunes"

        def __init__(self):
            self.n = 0

        def search(self, artist, title):
            self.n += 1
            return []

    prov, now = Counting(), [1_000_000.0]
    e = Enricher(HttpClient(lambda r: None), tmp_path / "e.json", providers=[prov], clock=lambda: now[0])
    row = TrackRow(pos=1, title="Here Again", artists=["Deas"], artist_display="Deas")
    e.enrich([row])
    e.enrich([row])
    assert prov.n == 1
    now[0] += EMPTY_RESULT_TTL_S + 1
    e.enrich([row])
    assert prov.n == 2


def test_provider_errors_are_notes_never_exceptions(tmp_path):
    def down(req):
        raise HttpError("sin conexión con itunes.apple.com (ConnectionError)")

    row = TrackRow(pos=1, title="Duff", artists=["Introversion"], artist_display="Introversion")
    (o,) = Enricher(HttpClient(down, sleep=lambda s: None), tmp_path / "e.json").enrich([row])
    assert not o.accepted and "iTunes no respondió" in o.note_es and "MusicBrainz no respondió" in o.note_es
    assert row.expected_duration_s is None and not (tmp_path / "e.json").exists()   # failures are not cached


def test_missing_fixture_fails_loudly(replay, tmp_path):
    http, _ = replay
    with pytest.raises(ReplayMiss):
        Enricher(http, tmp_path / "e.json").enrich([TrackRow(pos=1, title="No Grabada", artists=["Nadie"],
                                                             artist_display="Nadie")])


def test_skips_cancel_user_duration_and_corrupt_cache(replay, tmp_path):
    http, rt = replay
    cache = tmp_path / "e.json"
    cache.write_text("{no es json", encoding="utf-8")
    e = Enricher(http, cache)
    no_artist = TrackRow(pos=1, title="Gunslingers", artists=[], artist_display="", status=RowStatus.REVISAR)
    (o,) = e.enrich([no_artist])
    assert not o.accepted and "Falta el artista" in o.note_es and rt.calls == []
    cancel = threading.Event()
    cancel.set()
    assert e.enrich(_sample_rows(), cancel=cancel) == []
    mine = TrackRow(pos=1, title="Gunslingers", artists=["Klint"], artist_display="Klint", expected_duration_s=330)
    (o,) = e.enrich([mine])
    assert o.accepted and mine.expected_duration_s == 330 and "expected_duration_s" not in o.changed
    assert json.loads(cache.read_text(encoding="utf-8"))["schema"] == CACHE_SCHEMA   # corrupt cache rebuilt
