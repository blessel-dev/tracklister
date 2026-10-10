"""Record the enrichment HTTP fixtures once: iTunes, Deezer and MusicBrainz for the sample set.

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

    .venv\\Scripts\\python.exe tools\\record_http_fixtures.py --yes
    .venv\\Scripts\\python.exe tools\\record_http_fixtures.py --rows <tracklist.csv|.txt> [--rows ...] --yes

Sends a few dozen polite public GET requests (the 17 tracks of the sample trackid.net CSV plus
the uncleaned "Roll Dann, Laster Records" query): only artist + title, the app User-Agent,
>= 1.2 s between any two requests, no credentials, nothing else. It never talks to Soulseek.
The answers are trimmed to the fields the providers read and saved under
tests/fixtures/http/<host>/<sha1 key>.json, where tests replay them with ReplayTransport.

--rows (1.0.1): imports each tracklist file with the app's own importer and runs the app's own
Enricher over its rows, so exactly the requests "Completar datos" sends are recorded (the first
provider that gives an accepted duration ends a row). A request that already has a fixture is
answered from it and sends nothing. Same spacing and User-Agent (DECISIONES E.21).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tracklister.enrich.enricher import Enricher, fmt_duration  # noqa: E402
from tracklister.enrich.providers import DeezerProvider, ItunesProvider, MusicBrainzProvider  # noqa: E402
from tracklister.inputs.importer import import_source  # noqa: E402
from tracklister.net.http import (HttpClient, HttpRequest, HttpResponse, ReplayTransport,  # noqa: E402
                                  fixture_doc, fixture_path, requests_transport)

SAMPLE = ROOT / "tests" / "fixtures" / "inputs" / "fjaak-techno-dj-set-section-may-2026.csv"
OUT = ROOT / "tests" / "fixtures" / "http"
GAP_S = 1.2
EXTRA_QUERIES = [("Roll Dann, Laster Records", "The Red House (Original)")]   # trackid's raw artist

ITUNES_KEYS = ("wrapperType", "kind", "trackId", "artistName", "trackName", "collectionName",
               "trackTimeMillis", "releaseDate", "primaryGenreName", "country")
DEEZER_KEYS = ("id", "type", "title", "title_short", "title_version", "duration", "rank", "isrc")
MB_KEYS = ("id", "score", "title", "length", "disambiguation", "video", "first-release-date", "isrcs")


def _trim_itunes(js: dict) -> dict:
    res = [{k: d.get(k) for k in ITUNES_KEYS if k in d} for d in js.get("results") or []]
    return {"resultCount": len(res), "results": res}


def _trim_deezer(js: dict) -> dict:
    if js.get("error"):
        return js
    data = []
    for d in js.get("data") or []:
        e = {k: d.get(k) for k in DEEZER_KEYS if k in d}
        e["artist"] = {k: (d.get("artist") or {}).get(k) for k in ("id", "name")}
        e["album"] = {k: (d.get("album") or {}).get(k) for k in ("id", "title")}
        data.append(e)
    return {"data": data, "total": js.get("total", len(data))}


def _trim_mb(js: dict) -> dict:
    recs = []
    for r in js.get("recordings") or []:
        e = {k: r.get(k) for k in MB_KEYS if k in r}
        e["artist-credit"] = [{"name": ac.get("name"), "joinphrase": ac.get("joinphrase", ""),
                               "artist": {k: (ac.get("artist") or {}).get(k) for k in ("id", "name")}}
                              for ac in r.get("artist-credit") or []]
        e["releases"] = [{k: rel.get(k) for k in ("id", "title", "status")} for rel in (r.get("releases") or [])[:3]]
        recs.append(e)
    return {"created": js.get("created"), "count": js.get("count"), "offset": js.get("offset"), "recordings": recs}


TRIM = {"itunes.apple.com": _trim_itunes, "api.deezer.com": _trim_deezer, "musicbrainz.org": _trim_mb}


class RecordingTransport:
    """Live GET, then save the trimmed answer as a replay fixture. With reuse=True a request that
    already has a fixture is answered from it, without any network access."""

    def __init__(self, out: Path, *, reuse: bool = False):
        self.out = out
        self.live = requests_transport(timeout_s=30)
        self.replay = ReplayTransport(out) if reuse else None
        self.last = 0.0
        self.saved: list[Path] = []
        self.reused = 0

    def __call__(self, req: HttpRequest) -> HttpResponse:
        if self.replay is not None and fixture_path(self.out, req).is_file():
            self.reused += 1
            return self.replay(req)
        wait = self.last + GAP_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            resp = self.live(req)
        finally:
            self.last = time.monotonic()
        body = resp.body
        if 200 <= resp.status < 300 and req.host in TRIM:
            body = json.dumps(TRIM[req.host](json.loads(body.decode("utf-8-sig"))), ensure_ascii=False).encode()
        headers = {"content-type": resp.headers.get("content-type", "application/json")}
        doc = fixture_doc(req, resp.status, headers, body)
        p = fixture_path(self.out, req)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        self.saved.append(p)
        print(f"  {resp.status} {req.host} {dict(req.params)} -> {p.relative_to(ROOT)}")
        return HttpResponse(resp.status, resp.headers, body)


def queries() -> list[tuple[str, str]]:
    res = import_source(SAMPLE)
    out = [(r.artist_display, r.title_with_version) for r in res.rows if not r.is_id]
    return out + EXTRA_QUERIES


def client(transport) -> HttpClient:
    """The app's client (its User-Agent), spaced at least as E.21 asks, and never faster than GAP_S."""
    return HttpClient(transport, min_interval_s={"itunes.apple.com": 3.0, "api.deezer.com": GAP_S,
                                                 "musicbrainz.org": GAP_S})


def record_rows(files: list[Path], out: Path, *, merge: bool = False) -> int:
    """--rows: the app's importer and Enricher over each file; prints what each row got. With --merge,
    the later files are also combined into the first one ("Añadir otra fuente del mismo set") and the
    combined table is completed again, as the window does after combining."""
    from tracklister.inputs.merge import merge_sources

    transport = RecordingTransport(out, reuse=True)
    failures = 0

    def run(label: str, rows) -> None:
        nonlocal failures
        print(label)
        for row, o in zip(rows, enricher.enrich(rows)):
            if row.is_id:
                continue
            failures += "no respondió" in o.note_es
            print(f"  {row.pos:2d}. {row.artist_display} - {row.title_with_version}: "
                  f"{fmt_duration(row.expected_duration_s)} [{o.provider or '-'}] {o.note_es}")

    with tempfile.TemporaryDirectory() as tmp:
        enricher = Enricher(client(transport), Path(tmp) / "enrich.json")   # no cache from this PC
        first = None
        for f in files:
            res = import_source(f)
            run(f"{f.name}: {len(res.rows)} filas ({res.message_es})", res.rows)
            first = first if first is not None else res.rows
        if merge and len(files) > 1:
            rows = first
            for f in files[1:]:
                rows = merge_sources(rows, import_source(f).rows)
            run(f"Combinadas: {len(rows)} filas", rows)
    print(f"{len(transport.saved)} fixtures nuevos, {transport.reused} reutilizados, en {out}; "
          f"{failures} filas con errores de red")
    return 0 if failures == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="really send the public GET requests")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--rows", type=Path, action="append", default=[],
                    help="a tracklist file (CSV, Excel or text): record what 'Completar datos' asks for it")
    ap.add_argument("--merge", action="store_true",
                    help="with several --rows: also combine them into the first and complete that table")
    args = ap.parse_args()
    if args.rows:
        missing = [str(p) for p in args.rows if not p.is_file()]
        if missing:
            print(f"No existe: {', '.join(missing)}")
            return 2
        if not args.yes:
            print(f"{len(args.rows)} archivo(s). Vuelve a ejecutar con --yes para enviar las peticiones.")
            return 2
        return record_rows(args.rows, args.out, merge=args.merge)
    qs = queries()
    if not args.yes:
        print(f"{len(qs)} pistas x 3 servicios. Vuelve a ejecutar con --yes para enviar las peticiones.")
        return 2
    transport = RecordingTransport(args.out)
    http = client(transport)
    providers = [ItunesProvider(http), DeezerProvider(http), MusicBrainzProvider(http)]
    failures = 0
    for artist, title in qs:
        print(f"{artist} - {title}")
        for p in providers:
            try:
                n = len(p.search(artist, title))
                print(f"    {p.name}: {n} resultados")
            except Exception as e:  # keep going; the failure is visible in the output
                failures += 1
                print(f"    {p.name}: ERROR {type(e).__name__}: {e}")
    print(f"{len(transport.saved)} fixtures guardados en {args.out}; {failures} errores")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
