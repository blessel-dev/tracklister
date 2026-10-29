"""'Completar datos': expected duration, store ids and confirmation for each row of the table.

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

Order iTunes -> Deezer -> MusicBrainz (02 section 3.E: 10/10, 8/10, 7/10 on the sample); the
first accepted result with a duration wins. Results are cached in
%LOCALAPPDATA%\\Tracklister\\cache\\enrich.json, so a second run sends no request. A provider
that fails only adds a note: enrich() never raises for network or data problems (02 section 4,
principle 2). Rows are updated in place; the returned outcomes say what changed.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rapidfuzz import fuzz

from tracklister.core.jsonio import read_json, write_json
from tracklister.core.model import RowStatus, TrackRow
from tracklister.core.textnorm import norm_key, split_artists
from tracklister.enrich.pick import Pick, pick_best
from tracklister.enrich.providers import Candidate, DeezerProvider, ItunesProvider, MusicBrainzProvider
from tracklister.inputs.clean import is_label_credit, label_keys
from tracklister.net.http import HttpClient, ReplayMiss

CACHE_SCHEMA = "tracklister.enrichcache/1"
EMPTY_RESULT_TTL_S = 7 * 24 * 3600          # "no results" is asked again after a week
PROVIDER_ES = {"itunes": "iTunes", "deezer": "Deezer", "musicbrainz": "MusicBrainz"}
SPELLING_PROVIDERS = ("itunes", "deezer")    # store catalogues: trusted to fix the artist spelling
CONFIDENCE_ENRICHED = 0.9


@dataclass(frozen=True)
class EnrichOutcome:
    uid: str
    provider: str | None
    accepted: bool
    changed: tuple[str, ...]
    note_es: str


def fmt_duration(s: int | None) -> str:
    return "?" if not s else f"{s // 60}:{s % 60:02d}"


def cache_key(provider: str, artist: str, title: str) -> str:
    return f"{provider}|{norm_key(artist)}|{norm_key(title)}"


class Enricher:
    def __init__(self, http: HttpClient, cache_path: Path, providers=None, *, clock: Callable[[], float] = time.time):
        self.providers = list(providers) if providers is not None else [
            ItunesProvider(http), DeezerProvider(http), MusicBrainzProvider(http)]
        self.cache_path = Path(cache_path)
        self._clock = clock
        self._cache: dict | None = None
        self._dirty = False

    # ---- cache ---------------------------------------------------------------------------------
    def _load(self) -> dict:
        if self._cache is None:
            try:
                data = read_json(self.cache_path, default=None)
            except ValueError:
                data = None                      # a corrupt cache is rebuilt, never fatal
            if not isinstance(data, dict) or data.get("schema") != CACHE_SCHEMA or \
                    not isinstance(data.get("entries"), dict):
                data = {"schema": CACHE_SCHEMA, "entries": {}}
            self._cache = data
        return self._cache

    def _save(self) -> None:
        if self._dirty and self._cache is not None:
            try:
                write_json(self.cache_path, self._cache)
            except OSError:
                pass                             # the cache is an optimisation only
            self._dirty = False

    def _search(self, provider, artist: str, title: str) -> list[Candidate]:
        entries = self._load()["entries"]
        key = cache_key(provider.name, artist, title)
        hit = entries.get(key)
        now = self._clock()
        if isinstance(hit, dict) and (hit.get("candidates") or now - float(hit.get("fetched_at", 0)) < EMPTY_RESULT_TTL_S):
            return [Candidate.from_dict(d) for d in hit.get("candidates") or []]
        cands = provider.search(artist, title)
        entries[key] = {"fetched_at": now, "candidates": [c.to_dict() for c in cands]}
        self._dirty = True
        return cands

    # ---- rows ----------------------------------------------------------------------------------
    def enrich(self, rows: list[TrackRow], *, on_progress: Callable[[int, int], None] | None = None,
               cancel: threading.Event | None = None) -> list[EnrichOutcome]:
        out: list[EnrichOutcome] = []
        try:
            for i, row in enumerate(rows, 1):
                if cancel is not None and cancel.is_set():
                    break
                out.append(self.enrich_row(row))
                if on_progress is not None:
                    on_progress(i, len(rows))
        finally:
            self._save()
        return out

    def enrich_row(self, row: TrackRow) -> EnrichOutcome:
        if row.is_id:
            return EnrichOutcome(row.uid, None, False, (), "Fila ID: no se busca.")
        artist = row.artist_display or row.search_artist
        if not artist.strip() or not row.title.strip():
            return EnrichOutcome(row.uid, None, False, (), "Falta el artista o el título: no se puede buscar.")
        errors: list[str] = []
        other_version: Pick | None = None
        chosen: tuple[str, Pick] | None = None
        for prov in self.providers:
            try:
                cands = self._search(prov, artist, row.title)
            except ReplayMiss:
                raise                            # tests: a missing fixture must fail loudly
            except Exception as e:  # network, quota, odd JSON: a note, never an exception
                errors.append(f"{PROVIDER_ES.get(prov.name, prov.name)} no respondió ({e})")
                continue
            pick = pick_best(row, cands)
            if pick.accepted:
                if pick.candidate.duration_s:
                    chosen = (prov.name, pick)
                    break
                chosen = chosen or (prov.name, pick)
            elif pick.candidate is not None and not pick.version_ok and other_version is None \
                    and pick.artist_score >= 80 and pick.title_score >= 85:
                other_version = pick
        if chosen is None:
            note = "Sin coincidencia segura en " + ", ".join(PROVIDER_ES.get(p.name, p.name) for p in self.providers)
            if other_version is not None:
                c = other_version.candidate
                note += f". Solo aparece otra versión: '{c.artist} - {c.title_with_version}'"
            if errors:
                note += ". " + "; ".join(errors)
            return EnrichOutcome(row.uid, None, False, (), note + ".")
        provider, pick = chosen
        changed, extra = self._apply(row, provider, pick.candidate)
        c = pick.candidate
        note = f"{PROVIDER_ES.get(provider, provider)}: {fmt_duration(c.duration_s)} ({c.artist} - {c.title_with_version})"
        if extra:
            note += ". " + ". ".join(extra)
        if errors:
            note += ". " + "; ".join(errors)
        return EnrichOutcome(row.uid, provider, True, tuple(changed), note + ".")

    @staticmethod
    def _apply(row: TrackRow, provider: str, c: Candidate) -> tuple[list[str], list[str]]:
        changed: list[str] = []
        extra: list[str] = []
        user_duration = row.expected_duration_s is not None and row.enrich_source is None
        if c.duration_s and not user_duration and row.expected_duration_s != c.duration_s:
            row.expected_duration_s = c.duration_s
            changed.append("expected_duration_s")
        ids_changed = False
        for f in ("isrc", "itunes", "deezer", "mbid"):
            v = getattr(c.ids, f)
            if v and not getattr(row.ids, f):
                setattr(row.ids, f, v)
                ids_changed = True
        if ids_changed:
            changed.append("ids")
        # a row with the user's own duration (E.23) never becomes «completed by the store»: otherwise the next
        # enrichment would take its duration for the store's and replace it (barrido AG-01)
        if not user_duration and row.enrich_source != provider:
            row.enrich_source = provider
            changed.append("enrich_source")
        if row.confidence < CONFIDENCE_ENRICHED:
            row.confidence = CONFIDENCE_ENRICHED
            changed.append("confidence")
        if provider in SPELLING_PROVIDERS and c.artist:
            # the store's credit, minus its labels: iTunes itself credits "Roll Dann & Laster Records", and
            # "GCOD & KYSH Records" / "Ana Rs & Demolate Records" (06 R5). A co-artist is a label when it is
            # the row's or the store's label (any source), or when it looks like one ("X Records"). The
            # first store artist always stays: it is the one that must match the row.
            label = label_keys(row.label) | label_keys(c.label)
            new = [a for i, a in enumerate(split_artists(c.artist)) if i == 0 or not is_label_credit(a, label)]
            mine = row.artists or split_artists(row.artist_display)
            mine_keys = [norm_key(a) for a in mine]
            if new and [norm_key(a) for a in new] != mine_keys \
                    and any(fuzz.ratio(norm_key(new[0]), m) >= 90 for m in mine_keys):
                old = row.artist_display
                row.artists = new
                row.artist_display = c.artist if len(new) == len(split_artists(c.artist)) else " & ".join(new)
                row.notes.append(f"artista corregido con {PROVIDER_ES[provider]}: antes '{old}'")
                changed.append("artist")
                extra.append(f"Artista corregido (antes '{old}')")
        if row.status == RowStatus.REVISAR:
            row.status, row.download = RowStatus.OK, True
            row.notes.append(f"confirmada con {PROVIDER_ES.get(provider, provider)}")
            changed += ["status", "download"]
            extra.append("Fila confirmada y marcada para descargar")
        return changed, extra
