"""Version-aware choice of the provider result (port of fuentes/enrich_probe.py pick)."""
from __future__ import annotations

from tracklister.core.model import TrackRow
from tracklister.enrich.pick import pick_best
from tracklister.enrich.providers import Candidate


def _row(artist: str, title: str, version: str | None = None, artists=None) -> TrackRow:
    return TrackRow(pos=1, title=title, version=version, artist_display=artist,
                    artists=artists if artists is not None else [a.strip() for a in artist.split("&")])


def _c(artist: str, title: str, version: str | None, dur: int | None, provider: str = "itunes") -> Candidate:
    return Candidate(provider, artist, title, version, dur)


def test_remix_wanted_original_only_is_rejected():
    row = _row("Chris Liebing", "Higher Things", "FJAAK Remix")
    p = pick_best(row, [_c("Chris Liebing", "Higher Things", None, 298, "musicbrainz")])
    assert not p.accepted and not p.version_ok and p.artist_score == 100 and p.title_score == 100
    assert p.reason_es.startswith("otra versión") and "FJAAK Remix" in p.reason_es
    p = pick_best(row, [_c("Chris Liebing", "Higher Things", None, 298),
                        _c("Chris Liebing", "Higher Things", "FJAAK Remix", 289)])
    assert p.accepted and p.candidate.duration_s == 289


def test_original_wanted_remix_rejected_and_original_mix_preferred_over_extended():
    row = _row("Plug Trax", "Zoned Out")
    assert not pick_best(row, [_c("Plug Trax", "Zoned Out", "Someone Remix", 330)]).accepted
    p = pick_best(row, [_c("Plug Trax", "Zoned Out", "Extended Mix", 420), _c("Plug Trax", "Zoned Out", "Original Mix", 295)])
    assert p.accepted and p.candidate.version == "Original Mix"
    p = pick_best(_row("Plug Trax", "Zoned Out", "Extended Mix"),
                  [_c("Plug Trax", "Zoned Out", "Original Mix", 295), _c("Plug Trax", "Zoned Out", "Extended Mix", 420)])
    assert p.candidate.duration_s == 420


def test_radio_edit_needs_a_radio_edit():
    row = _row("Blasha & Allatt", "Dust 1")
    assert not pick_best(row, [_c("Blasha & Allatt", "Dust 1", "Radio Edit", 180)]).accepted
    assert pick_best(_row("A", "B", "Radio Edit"), [_c("A", "B", "Radio Edit", 180)]).accepted


def test_label_written_as_artist_still_matches():
    row = _row("Roll Dann, Laster Records", "The Red House", artists=["Roll Dann", "Laster Records"])
    p = pick_best(row, [_c("Roll Dann", "The Red House", None, 339, "deezer")])
    assert p.accepted and p.artist_score == 100


def test_thresholds():
    row = _row("ANFS", "Caballero")
    p = pick_best(row, [_c("Nicolas Grandfils", "Les trois caballeros", None, 305, "deezer")])
    assert not p.accepted and p.reason_es.startswith("no coincide")
    assert pick_best(row, [_c("Anfs", "Caballero", None, 338)]).accepted          # case/accents do not count
    assert not pick_best(row, [_c("ANFS", "Caballeros del Zodiaco", None, 300)]).accepted
    empty = pick_best(row, [])
    assert empty.candidate is None and not empty.accepted and empty.reason_es == "sin resultados"
