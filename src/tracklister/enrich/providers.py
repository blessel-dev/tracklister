"""Free metadata sources for the expected duration and the exact version: iTunes, Deezer, MusicBrainz.

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

Only the artist and the base title are sent (02 section 3.E); no key, no login. Each provider
returns Candidates with the title split into base + version by core.textnorm, so pick.py can
apply the version rule. A malformed answer raises ValueError; network errors raise HttpError.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tracklister.core.model import TrackIds
from tracklister.core.textnorm import nfc, split_artists, split_title_version
from tracklister.net.http import HttpClient, HttpError

ITUNES_URL = "https://itunes.apple.com/search"
DEEZER_URL = "https://api.deezer.com/search"
MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2/recording"


@dataclass(frozen=True)
class Candidate:
    provider: str                 # "itunes" | "deezer" | "musicbrainz"
    artist: str
    title: str                    # base title
    version: str | None           # None = original
    duration_s: int | None
    ids: TrackIds = field(default_factory=TrackIds)
    album: str | None = None

    @property
    def title_with_version(self) -> str:
        return f"{self.title} ({self.version})" if self.version else self.title

    def to_dict(self) -> dict:
        return {"provider": self.provider, "artist": self.artist, "title": self.title, "version": self.version,
                "duration_s": self.duration_s, "ids": self.ids.to_dict(), "album": self.album}

    @classmethod
    def from_dict(cls, d: dict) -> "Candidate":
        return cls(provider=str(d["provider"]), artist=str(d.get("artist") or ""), title=str(d.get("title") or ""),
                   version=d.get("version"), duration_s=d.get("duration_s"), ids=TrackIds.from_dict(d.get("ids")),
                   album=d.get("album"))


def base_title(title: str) -> str:
    base, _ = split_title_version(title)
    return base or nfc(title)


def make_candidate(provider: str, artist: str, full_title: str, duration_s, ids: TrackIds,
                   album: str | None) -> Candidate:
    base, version = split_title_version(full_title)
    dur = int(round(float(duration_s))) if duration_s else None
    return Candidate(provider, nfc(artist), base or nfc(full_title), version, dur or None, ids, album or None)


def _seconds_from_ms(ms) -> float | None:
    return float(ms) / 1000.0 if ms else None


def _lucene_phrase(s: str) -> str:
    return nfc(s).replace("\\", "\\\\").replace('"', '\\"')


class ItunesProvider:
    name = "itunes"

    def __init__(self, http: HttpClient, limit: int = 15):
        self.http, self.limit = http, limit

    def params(self, artist: str, title: str) -> dict[str, str]:
        return {"term": f"{nfc(artist)} {base_title(title)}", "media": "music", "entity": "song",
                "limit": str(self.limit)}

    def search(self, artist: str, title: str) -> list[Candidate]:
        js = self.http.get_json(ITUNES_URL, self.params(artist, title))
        try:
            out = []
            for d in js.get("results") or []:
                if d.get("kind", "song") != "song" or not d.get("trackName"):
                    continue
                ids = TrackIds(itunes=str(d["trackId"]) if d.get("trackId") else None)
                out.append(make_candidate(self.name, d.get("artistName") or "", d["trackName"],
                                          _seconds_from_ms(d.get("trackTimeMillis")), ids, d.get("collectionName")))
            return out
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            raise ValueError(f"respuesta inesperada de iTunes: {e}") from e


class DeezerProvider:
    name = "deezer"

    def __init__(self, http: HttpClient, limit: int = 10):
        self.http, self.limit = http, limit

    def queries(self, artist: str, title: str) -> list[str]:
        a, t = nfc(artist).replace('"', ""), base_title(title).replace('"', "")
        return [f'artist:"{a}" track:"{t}"', f"{a} {t}"]

    def search(self, artist: str, title: str) -> list[Candidate]:
        for q in self.queries(artist, title):
            js = self.http.get_json(DEEZER_URL, {"q": q, "limit": str(self.limit)})
            if isinstance(js, dict) and js.get("error"):
                err: Any = js["error"]
                raise HttpError(f"Deezer: {err.get('message') if isinstance(err, dict) else err}")
            try:
                out = []
                for d in js.get("data") or []:
                    full = d.get("title") or ""
                    ver = d.get("title_version") or ""
                    if ver and ver not in full:
                        full = f"{full} {ver}"
                    if not full:
                        continue
                    ids = TrackIds(deezer=str(d["id"]) if d.get("id") else None, isrc=d.get("isrc"))
                    out.append(make_candidate(self.name, (d.get("artist") or {}).get("name") or "", full,
                                              d.get("duration"), ids, (d.get("album") or {}).get("title")))
            except (AttributeError, KeyError, TypeError, ValueError) as e:
                raise ValueError(f"respuesta inesperada de Deezer: {e}") from e
            if out:
                return out
        return []


class MusicBrainzProvider:
    name = "musicbrainz"

    def __init__(self, http: HttpClient, limit: int = 10):
        self.http, self.limit = http, limit

    def params(self, artist: str, title: str) -> dict[str, str]:
        primary = (split_artists(artist) or [nfc(artist)])[0]
        q = f'recording:"{_lucene_phrase(base_title(title))}" AND artist:"{_lucene_phrase(primary)}"'
        return {"query": q, "fmt": "json", "limit": str(self.limit)}

    def search(self, artist: str, title: str) -> list[Candidate]:
        js = self.http.get_json(MUSICBRAINZ_URL, self.params(artist, title))
        try:
            out = []
            for r in js.get("recordings") or []:
                credit = "".join((ac.get("name") or "") + (ac.get("joinphrase") or "")
                                 for ac in r.get("artist-credit") or [])
                full = r.get("title") or ""
                if r.get("disambiguation"):
                    full = f"{full} ({r['disambiguation']})"
                if not full:
                    continue
                isrcs = r.get("isrcs") or []
                rels = r.get("releases") or [{}]
                ids = TrackIds(mbid=r.get("id"), isrc=isrcs[0] if isrcs else None)
                out.append(make_candidate(self.name, credit, full, _seconds_from_ms(r.get("length")), ids,
                                          rels[0].get("title")))
            return out
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            raise ValueError(f"respuesta inesperada de MusicBrainz: {e}") from e
