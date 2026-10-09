"""HTTP client: replay fixtures, User-Agent, per-host spacing (fake clock), errors, live transport on loopback."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tracklister import config
from tracklister.net.http import (HttpClient, HttpError, HttpRequest, HttpResponse, ReplayMiss, ReplayTransport,
                                  fixture_key, fixture_path, requests_transport)

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "http"
MB = "https://musicbrainz.org/ws/2/recording"


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s


class Recorder:
    """Transport that answers 200 {} and records (time, request); each call takes `cost` seconds."""

    def __init__(self, clock: FakeClock, cost: float = 0.3, status: int = 200, body: bytes = b"{}"):
        self.clock, self.cost, self.status, self.body = clock, cost, status, body
        self.calls: list[tuple[float, HttpRequest]] = []

    def __call__(self, req: HttpRequest) -> HttpResponse:
        self.calls.append((self.clock.t, req))
        self.clock.t += self.cost
        return HttpResponse(self.status, {"content-type": "application/json"}, self.body)


def test_fixture_key_ignores_param_order():
    a = HttpRequest("GET", MB, (("query", "x"), ("fmt", "json")))
    b = HttpRequest("get", MB, (("fmt", "json"), ("query", "x")))
    assert fixture_key(a) == fixture_key(b) and len(fixture_key(a)) == 16
    assert fixture_key(a) != fixture_key(HttpRequest("GET", MB, (("query", "y"), ("fmt", "json"))))
    assert fixture_path(FIX, a).parent == FIX / "musicbrainz.org"


def test_replay_transport_reads_recorded_answers_and_misses_loudly():
    rt = ReplayTransport(FIX)
    http = HttpClient(rt, sleep=lambda s: None)
    js = http.get_json(MB, {"query": 'recording:"Higher Things" AND artist:"Chris Liebing"', "fmt": "json",
                            "limit": "10"})
    assert js["recordings"][0]["title"] == "Higher Things" and js["recordings"][0]["length"] == 297810
    assert len(rt.calls) == 1
    with pytest.raises(ReplayMiss):
        http.get_json(MB, {"query": "nada", "fmt": "json", "limit": "10"})


def test_user_agent_names_the_app_version_and_url():
    clock = FakeClock()
    rec = Recorder(clock)
    HttpClient(rec, clock=clock, sleep=clock.sleep).get_json(MB, {"query": "q"})
    headers = dict(rec.calls[0][1].headers)
    assert headers["User-Agent"] == config.user_agent()
    assert headers["User-Agent"].startswith(f"Tracklister/{config.APP_VERSION} ( https://github.com/")
    assert headers["Accept"] == "application/json"
    assert rec.calls[0][1].params == (("query", "q"),)


def test_musicbrainz_gets_at_most_one_request_per_second():
    clock = FakeClock()
    rec = Recorder(clock, cost=0.3)
    http = HttpClient(rec, clock=clock, sleep=clock.sleep)
    for _ in range(4):
        http.get_json(MB, {"query": "q"})
    starts = [t for t, _ in rec.calls]
    assert all(b - a >= config.MUSICBRAINZ_MIN_INTERVAL_S for a, b in zip(starts, starts[1:]))
    assert all(b - (a + 0.3) >= 1.0 - 1e-9 for a, b in zip(starts, starts[1:]))   # gap after the answer
    assert len(clock.sleeps) == 3


def test_spacing_is_per_host_and_cannot_be_lowered_for_musicbrainz():
    clock = FakeClock()
    rec = Recorder(clock, cost=0.0)
    http = HttpClient(rec, clock=clock, sleep=clock.sleep, min_interval_s={"musicbrainz.org": 0.1})
    assert http.interval_for("musicbrainz.org") == config.MUSICBRAINZ_MIN_INTERVAL_S
    assert http.interval_for("beta.musicbrainz.org") == config.MUSICBRAINZ_MIN_INTERVAL_S
    assert http.interval_for("itunes.apple.com") == 3.0
    http.get_json(MB)
    http.get_json("https://api.github.com/repos/x/y/releases/latest")    # other host: no wait
    assert clock.sleeps == []
    http.get_json("https://itunes.apple.com/search", {"term": "a"})
    http.get_json("https://itunes.apple.com/search", {"term": "b"})
    assert clock.sleeps == [3.0]


def test_get_json_errors():
    clock = FakeClock()
    with pytest.raises(HttpError) as e:
        HttpClient(Recorder(clock, status=503), clock=clock, sleep=clock.sleep).get_json(MB)
    assert e.value.status == 503 and "503" in str(e.value)
    with pytest.raises(HttpError, match="no devolvió JSON"):
        HttpClient(Recorder(clock, body=b"<html>"), clock=clock, sleep=clock.sleep).get_json(MB)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = json.dumps({"path": self.path, "ua": self.headers.get("User-Agent")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("ETag", 'W/"x"')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_requests_transport_on_loopback(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/search"
        resp = HttpClient(requests_transport(timeout_s=5)).get(url, {"term": "Exos Glaður"})
        assert resp.status == 200 and resp.header("ETag") == 'W/"x"'
        js = resp.json()
        assert js["path"] == "/search?term=Exos+Gla%C3%B0ur" and js["ua"] == config.user_agent()
        with pytest.raises(HttpError, match="sin conexión"):
            requests_transport(timeout_s=2)(HttpRequest("GET", "http://127.0.0.1:1/x"))
    finally:
        server.shutdown()
        server.server_close()
