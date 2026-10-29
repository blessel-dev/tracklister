"""Choose the provider result that is really the row's track, version included.

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

Port of fuentes/enrich_probe.py `pick`: fuzzy artist (>= 80) and base title (>= 85), and the
version rule of core.textnorm.versions_compatible. Unlike the probe, a candidate with another
version is never accepted: MusicBrainz only had the original of "Chris Liebing - Higher Things"
(4:58) when the row asked for the FJAAK Remix (4:49). Nor is one whose title carries other numbers
("Minus 2" for "Minus 1", CL-02), as in the verification (R.2).
"""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from tracklister.core.model import TrackRow
from tracklister.core.textnorm import classify_version, norm_key, split_artists, versions_compatible
from tracklister.enrich.providers import Candidate
from tracklister.verify.identity import number_tokens

ARTIST_MIN = 80.0
TITLE_MIN = 85.0


@dataclass(frozen=True)
class Pick:
    candidate: Candidate | None
    artist_score: float
    title_score: float
    version_ok: bool
    accepted: bool
    reason_es: str = ""


def artist_score(row: TrackRow, cand_artist: str) -> float:
    got = norm_key(cand_artist)
    want = norm_key(row.artist_display or row.search_artist)
    if not got or not want:
        return 0.0
    best = float(fuzz.token_set_ratio(want, got))
    for part in row.artists or split_artists(row.artist_display):
        k = norm_key(part)
        if k:
            best = max(best, float(fuzz.ratio(k, got)))
    return best


def title_score(row: TrackRow, cand: Candidate) -> float:
    a, b = norm_key(row.title), norm_key(cand.title)
    return float(fuzz.ratio(a, b)) if a and b else 0.0


def pick_best(row: TrackRow, cands: list[Candidate]) -> Pick:
    if not cands:
        return Pick(None, 0.0, 0.0, False, False, "sin resultados")
    wanted_kind = classify_version(row.version)
    best: tuple | None = None
    for c in cands:
        sa, st = artist_score(row, c.artist), title_score(row, c)
        ok, why = versions_compatible(row.version, c.version)
        total = 0.5 * sa + 0.5 * st + (10 if ok else -25)
        total += 5 if classify_version(c.version) == wanted_kind else 0   # Original over Extended, etc.
        if best is None or total > best[0]:
            best = (total, c, sa, st, ok, why)
    _, c, sa, st, ok, why = best
    # other numbers are another track, as in the verification (R.2): «Minus 1» is not «Minus 2», although
    # fuzz.ratio gives 85.7 (barrido CL-02, the numbers half; the artist rule is unchanged)
    same_numbers = number_tokens(norm_key(row.title)) == number_tokens(norm_key(c.title))
    accepted = sa >= ARTIST_MIN and st >= TITLE_MIN and ok and same_numbers
    if accepted:
        reason = f"coincide ({why})"
    elif sa >= ARTIST_MIN and st >= TITLE_MIN and ok:
        reason = "no coincide (otro número)"
    elif sa >= ARTIST_MIN and st >= TITLE_MIN:
        reason = f"otra versión: {why}"
    else:
        reason = f"no coincide (artista {sa:.0f}, título {st:.0f})"
    return Pick(c, round(sa, 1), round(st, 1), ok, accepted, reason)
