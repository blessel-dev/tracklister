"""Providers against recorded iTunes/Deezer/MusicBrainz answers (tests/fixtures/http, ReplayTransport)."""
from __future__ import annotations

from pathlib import Path

import pytest

from tracklister.core.model import TrackIds
from tracklister.enrich.providers import Candidate, DeezerProvider, ItunesProvider, MusicBrainzProvider
from tracklister.net.http import HttpClient, HttpError, HttpRequest, HttpResponse, ReplayTransport

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "http"


@pytest.fixture
def replay():
    rt = ReplayTransport(FIX)
    return HttpClient(rt, sleep=lambda s: None), rt


def test_itunes_sends_artist_and_base_title_only(replay):
    http, rt = replay
    cands = ItunesProvider(http).search("Chris Liebing", "Higher Things (FJAAK Remix)")
    (req,) = rt.calls
    assert req.url == "https://itunes.apple.com/search"
    assert dict(req.params) == {"term": "Chris Liebing Higher Things", "media": "music", "entity": "song",
                                "limit": "15"}
    remix = next(c for c in cands if c.version == "FJAAK Remix")
    assert (remix.provider, remix.artist, remix.title, remix.duration_s) == ("itunes", "Chris Liebing",
                                                                             "Higher Things", 289)
    assert remix.ids.itunes and remix.ids.itunes.isdigit()


def test_deezer_falls_back_to_a_plain_query(replay):
    http, rt = replay
    cands = DeezerProvider(http).search("Truncate", "Dust 1 (Kai Van Dongen Remix)")
    assert [dict(r.params)["q"] for r in rt.calls][0] == 'artist:"Truncate" track:"Dust 1"'
    remix = next(c for c in cands if c.version == "Kai Van Dongen Remix")
    assert (remix.artist, remix.title, remix.duration_s) == ("Truncate", "Dust 1", 289)
    assert remix.ids.deezer


def test_musicbrainz_query_length_and_ids(replay):
    http, rt = replay
    (c,) = MusicBrainzProvider(http).search("Chris Liebing", "Higher Things (FJAAK Remix)")
    assert dict(rt.calls[0].params) == {"query": 'recording:"Higher Things" AND artist:"Chris Liebing"',
                                        "fmt": "json", "limit": "10"}
    assert (c.title, c.version, c.duration_s, c.album) == ("Higher Things", None, 298, "Evolver")
    assert c.ids.mbid == "13245daf-a124-4fa6-bf58-c7897623cb33" and c.ids.isrc == "DEBE72600009"
    assert MusicBrainzProvider(http).params("Blasha & Allatt", "8AM in Salford")["query"] == \
        'recording:"8AM in Salford" AND artist:"Blasha"'
    assert MusicBrainzProvider(http).params('A "B"', 'T "x" y')["query"] == \
        'recording:"T \\"x\\" y" AND artist:"A \\"B\\""'


class _Fixed:
    def __init__(self, body: bytes, status: int = 200):
        self.body, self.status = body, status
        self.calls: list[HttpRequest] = []

    def __call__(self, req):
        self.calls.append(req)
        return HttpResponse(self.status, {}, self.body)


def test_deezer_quota_error_and_odd_answers():
    with pytest.raises(HttpError, match="Quota"):
        DeezerProvider(HttpClient(_Fixed(b'{"error": {"type": "Exception", "message": "Quota limit exceeded"}}'),
                                  sleep=lambda s: None)).search("A", "B")
    with pytest.raises(ValueError, match="iTunes"):
        ItunesProvider(HttpClient(_Fixed(b'{"results": [{"trackName": "x", "trackTimeMillis": "abc"}]}'),
                                  sleep=lambda s: None)).search("A", "B")
    empty = _Fixed(b'{"data": []}')
    assert DeezerProvider(HttpClient(empty, sleep=lambda s: None)).search("A", "B") == []
    assert len(empty.calls) == 2                                   # advanced query, then the plain one


def test_candidate_round_trip():
    c = Candidate("deezer", "Exos", "Glaður Og Reifur", None, 303, TrackIds(deezer="1"), "Album")
    assert Candidate.from_dict(c.to_dict()) == c
    assert c.title_with_version == "Glaður Og Reifur"
