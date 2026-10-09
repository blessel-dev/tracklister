"""Candidate choice on real YouTube/SoundCloud metadata (tests/fixtures/youtube).

The *.meta.json files are copies of fuentes/youtube/*.meta.json (yt-dlp output trimmed to the
fields of fuentes/yt_meta.py; the unused per-comment ids/timestamps were dropped). The expected
row tables in expected/<id>.json come from the prototype's fuentes/youtube/parse_<id>.json.
INTENDED_FIXES lists the rows where v1.0 deliberately parses better than the prototype.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracklister.inputs.tlselect import candidates_from_meta, choose

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "youtube"
REAL_SETS = ("mD9ELt_Pvp4", "z6CwInMQF4w", "cmUov7X5Pjc", "FckHz08Z7PM", "7CXp2EaRaIU")
ROW_KEYS = ("ts", "artist", "title", "version", "feat", "label", "is_id", "quality")

# 02 section 3.B: "1 mal (la version quedo en el titulo)" -> fixed by the "(feat. X) Y Dub" rule.
INTENDED_FIXES = {
    "7CXp2EaRaIU": {1: {"title": "Power Of Music", "version": "Bongoloverz Dub", "feat": "An-Tonic"}},
}


def _meta(name: str) -> dict:
    return json.loads((FIX / f"{name}.meta.json").read_text(encoding="utf-8"))


def _expected(vid: str) -> dict:
    return json.loads((FIX / "expected" / f"{vid}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("vid", REAL_SETS)
def test_real_set_chooses_same_candidate_and_rows(vid):
    exp = _expected(vid)
    best, ranked, merged = choose(_meta(vid))
    assert best is not None
    assert (best.source, best.author) == (exp["chosen"]["source"], exp["chosen"]["author"])
    assert len(best.rows) == exp["chosen"]["rows"]
    assert ranked[0] is best
    want = [dict(r) for r in exp["rows"]]
    for pos, fix in INTENDED_FIXES.get(vid, {}).items():
        want[pos - 1].update(fix)
    got = [{k: getattr(r, k) for k in ROW_KEYS} for r in merged]
    assert len(got) == len(want)
    for i, (g, w) in enumerate(zip(got, want), 1):
        assert g == w, f"{vid} fila {i}"


def test_fjaak_gives_22_rows_with_4_ids():
    best, ranked, merged = choose(_meta("mD9ELt_Pvp4"))
    assert best.author == "@travo1001"
    assert len(merged) == 22
    assert [i for i, r in enumerate(merged, 1) if r.is_id] == [1, 12, 17, 18]
    assert [r.pos for r in merged] == list(range(1, 23))


def test_fjaak_spam_list_from_another_video_is_rejected():
    _, ranked, _ = choose(_meta("mD9ELt_Pvp4"))
    spam = next(c for c in ranked if c.author == "@antonioaranda8030")
    assert spam.strong == 17
    assert "enlaza a otro video/mix" in spam.why
    assert spam.score < 0.2 * ranked[0].score


def test_funk_tribu_merges_times_from_second_comment():
    best, _, merged = choose(_meta("cmUov7X5Pjc"))
    assert best.author == "@funktribumusic" and "autor~DJ" in best.why
    assert all(r.ts is not None for r in merged)
    assert all("ts de @skibiditomboy" in r.notes for r in merged)


def test_video_without_tracklist_chooses_nothing():
    best, ranked, merged = choose(_meta("6Wi11ljHVb4"))
    assert best is None and merged == []
    assert all(c.strong < 3 for c in ranked)


def test_soundcloud_description_with_at_label():
    meta = _meta("soundcloud_451181991")
    best, _, merged = choose(meta)
    assert best.source == "description"
    assert [(r.artist, r.title, r.version, r.label) for r in merged] == [
        ("Matt Sassari", "Rock trick", None, None),
        ("Tek.Ka", "TTA techno", "Joey H\u00e4tz 150bpm remix", "SDL records"),
        ("Tek.Ka", "TTA techno", "Joey H\u00e4tz remix @150bpm", "SDL records"),
        ("Oscar Mulero", "Catharsis", None, None),
    ]


def test_candidates_from_meta_sources():
    meta = {"title": "X - Live", "channel": "Chan", "duration": 600, "description": "",
            "chapters": [{"start_time": 0, "title": "A - One"}, {"start_time": 65.5, "title": "B - Two"}],
            "comments": [{"author": "@u", "text": "1:00 C - Three", "like_count": None, "is_pinned": True}]}
    cands = candidates_from_meta(meta)
    assert [c.source for c in cands] == ["description", "chapters", "comment"]
    assert [r.ts for r in cands[1].rows] == [0, 65]
    assert cands[2].likes == 0 and cands[2].pinned and cands[2].rows[0].title == "Three"
