"""Small HTTP client: app User-Agent, per-host spacing, swappable transport (live or replay).

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

- requests_transport(): the live transport used by the app (requests, timeout, proxies from env).
- ReplayTransport: tests read recorded responses from tests/fixtures/http/<host>/<key>.json
  and never touch the network (tests/conftest.py also blocks sockets).
- HttpClient spaces requests per host. MusicBrainz asks for at most 1 request per second and a
  User-Agent with the app name, version and URL (config.user_agent()); iTunes allows about
  20 calls per minute. The gap is measured from the END of the previous request.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urlparse

from tracklister import config

DEFAULT_MIN_INTERVAL_S: dict[str, float] = {
    "musicbrainz.org": config.MUSICBRAINZ_MIN_INTERVAL_S,
    "itunes.apple.com": 3.0,
    "api.deezer.com": 0.2,
}
FIXTURE_SCHEMA = "tracklister.httpfixture/1"


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    params: tuple[tuple[str, str], ...] = ()
    headers: tuple[tuple[str, str], ...] = ()

    @property
    def host(self) -> str:
        return urlparse(self.url).hostname or ""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]          # lower-case names
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8-sig"))

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


Transport = Callable[[HttpRequest], HttpResponse]


class HttpError(Exception):
    """Network failure (status None) or a non-2xx answer."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ReplayMiss(RuntimeError):
    """A test asked for a request that has no recorded fixture."""


def fixture_key(req: HttpRequest) -> str:
    """sha1 of method + URL + sorted query parameters, first 16 hex digits."""
    raw = f"{req.method.upper()} {req.url}?{urlencode(sorted(req.params))}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def fixture_path(root: Path, req: HttpRequest) -> Path:
    return Path(root) / (req.host or "sin-host") / f"{fixture_key(req)}.json"


def fixture_doc(req: HttpRequest, status: int, headers: dict[str, str], body: bytes) -> dict:
    """On-disk fixture: the request (no headers) and the response, JSON bodies kept readable."""
    resp: dict[str, Any] = {"status": status, "headers": headers}
    try:
        resp["json"] = json.loads(body.decode("utf-8-sig")) if body else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        resp["text"] = body.decode("utf-8", errors="replace")
    return {"schema": FIXTURE_SCHEMA,
            "request": {"method": req.method.upper(), "url": req.url, "params": [list(p) for p in req.params]},
            "response": resp}


class ReplayTransport:
    """Tests: answer from tests/fixtures/http/<host>/<fixture_key>.json; a missing file raises."""

    def __init__(self, fixtures_dir: Path):
        self.root = Path(fixtures_dir)
        self.calls: list[HttpRequest] = []

    def __call__(self, req: HttpRequest) -> HttpResponse:
        self.calls.append(req)
        p = fixture_path(self.root, req)
        if not p.is_file():
            raise ReplayMiss(f"sin fixture para {req.method} {req.url} {list(req.params)} ({p})")
        doc = json.loads(p.read_text(encoding="utf-8"))
        resp = doc["response"]
        if "text" in resp:
            body = resp["text"].encode("utf-8")
        elif resp.get("json") is not None:
            body = json.dumps(resp["json"], ensure_ascii=False).encode("utf-8")
        else:
            body = b""
        headers = {k.lower(): str(v) for k, v in (resp.get("headers") or {}).items()}
        return HttpResponse(int(resp["status"]), headers, body)


def requests_transport(timeout_s: float = 15) -> Transport:
    """Live transport for the app."""
    import requests  # lazy: tests never need it

    session = requests.Session()

    def send(req: HttpRequest) -> HttpResponse:
        try:
            r = session.request(req.method, req.url, params=list(req.params), headers=dict(req.headers),
                                timeout=timeout_s)
        except requests.RequestException as e:
            raise HttpError(f"sin conexión con {req.host} ({type(e).__name__})") from e
        return HttpResponse(r.status_code, {k.lower(): v for k, v in r.headers.items()}, r.content)

    return send


class HttpClient:
    def __init__(self, transport: Transport, *, user_agent: str | None = None,
                 min_interval_s: dict[str, float] | None = None, clock=time.monotonic, sleep=time.sleep):
        self.transport = transport
        self.user_agent = user_agent or config.user_agent()
        self.min_interval_s = {**DEFAULT_MIN_INTERVAL_S, **(min_interval_s or {})}
        if "musicbrainz.org" in self.min_interval_s:
            self.min_interval_s["musicbrainz.org"] = max(self.min_interval_s["musicbrainz.org"],
                                                         config.MUSICBRAINZ_MIN_INTERVAL_S)
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def interval_for(self, host: str) -> float:
        host = host.lower()
        return max((s for d, s in self.min_interval_s.items() if host == d or host.endswith("." + d)), default=0.0)

    def _lock_for(self, host: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(host, threading.Lock())

    def get(self, url: str, params: dict[str, str] | None = None,
            headers: dict[str, str] | None = None) -> HttpResponse:
        req = HttpRequest("GET", url, tuple((str(k), str(v)) for k, v in (params or {}).items()),
                          tuple({"User-Agent": self.user_agent, "Accept": "application/json",
                                 **(headers or {})}.items()))
        host = req.host
        with self._lock_for(host):
            interval, last = self.interval_for(host), self._last.get(host)
            if interval > 0 and last is not None:
                wait = last + interval - self._clock()
                if wait > 0:
                    self._sleep(wait)
            try:
                return self.transport(req)
            finally:
                self._last[host] = self._clock()

    def get_json(self, url: str, params: dict[str, str] | None = None) -> Any:
        resp = self.get(url, params)
        host = urlparse(url).hostname or url
        if not 200 <= resp.status < 300:
            raise HttpError(f"{host} respondió HTTP {resp.status}", resp.status)
        try:
            return resp.json()
        except (UnicodeDecodeError, ValueError) as e:
            raise HttpError(f"{host} no devolvió JSON", resp.status) from e
