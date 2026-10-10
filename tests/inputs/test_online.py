"""YouTube/SoundCloud links end to end through import_source, with a fake yt-dlp run."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.inputs.test_ytdlp import FakeRun, full_info
from tracklister.core.model import RowStatus
from tracklister.inputs.detect import InputKind
from tracklister.inputs.importer import import_source
from tracklister.inputs.online import external_tracklist_links, import_from_url
from tracklister.inputs.ytdlp import YtDlp

FJAAK = "https://www.youtube.com/watch?v=mD9ELt_Pvp4"


def _ytdlp(tmp_path: Path, info: dict | None, code: int = 0, err: bytes = b"") -> YtDlp:
    exe = tmp_path / "yt-dlp.exe"
    exe.write_bytes(b"MZ")
    out = json.dumps(info).encode("ascii") if info is not None else b""
    return YtDlp(exe, tmp_path / "cache", run=FakeRun({"--dump-single-json": (code, out, err)}))


def test_fjaak_link_gives_the_tracklist_comment(tmp_path):
    res = import_source(FJAAK, ytdlp=_ytdlp(tmp_path, full_info()))
    assert res.kind == InputKind.YOUTUBE
    assert len(res.rows) == 22 and res.chosen == 0
    assert [r.pos for r in res.rows] == list(range(1, 23))
    assert sum(r.is_id for r in res.rows) == 4 and not any(r.download for r in res.rows if r.is_id)
    assert all(r.source == "youtube_comment:@oyente-0879" and r.source_url == FJAAK for r in res.rows)
    first = res.candidates[0]
    assert first.label_es == "Comentario de @oyente-0879 · 22 pistas con tiempos · 13 likes"
    assert (first.n_rows, first.has_times, first.likes) == (22, True, 13)
    assert first.rows is res.rows and first.source_ref is res.sources[0]
    assert [c.source for c in res.candidates[1:3]] == ["youtube_comment:@oyente-0877",
                                                         "youtube_comment:@oyente-0906"]
    alt = res.candidates[1]                     # no times of its own: merged from @oyente-0879's comment
    assert alt.label_es == "Comentario de @oyente-0877 · 17 pistas con tiempos · 90 likes"
    assert alt.n_rows == 17 and alt.has_times
    assert sum("ts de @oyente-0879" in r.notes for r in alt.rows) >= 15
    (src,) = res.sources
    assert (src.kind, src.ref, src.detail) == ("youtube", FJAAK, "youtube_comment:@oyente-0879 (22 pistas)")
    assert res.suggested_name == "FJAAK | Techno DJ Set | SECTION. | May 2026"
    assert res.message_es.startswith("YouTube: Comentario de @oyente-0879")
    assert "alternativas en el desplegable" in res.message_es
    blasha = res.rows[1]
    assert (blasha.artists, blasha.title, blasha.ts_start, blasha.ts_end) == (["Blasha", "Allatt"],
                                                                             "8AM in Salford", 19, 158)


def test_switching_candidate_gives_ready_rows(tmp_path):
    res = import_source(FJAAK, ytdlp=_ytdlp(tmp_path, full_info()))
    alt = res.candidates[1]
    assert len(alt.rows) == 17 and all(r.source == alt.source for r in alt.rows)
    assert alt.source_ref.detail == "youtube_comment:@oyente-0877 (17 pistas)"
    assert [r.pos for r in alt.rows] == list(range(1, 18))


def test_video_without_tracklist_offers_the_linked_page(tmp_path):
    res = import_source("https://www.youtube.com/watch?v=6Wi11ljHVb4", ytdlp=_ytdlp(tmp_path, full_info("6Wi11ljHVb4")))
    assert res.rows == [] and res.chosen is None and res.sources == []
    assert res.links == ["https://mixmag.net/feature/the-cover-mix-fjaak-dj-berlin-techno"]
    assert "La descripción enlaza una tracklist" in res.message_es


def test_soundcloud_description(tmp_path):
    url = "https://soundcloud.com/plotsklap/tekka-ttk-techno-mix-hatz-remixes-sneak-preview"
    res = import_source(url, ytdlp=_ytdlp(tmp_path, full_info("soundcloud_451181991")))
    assert res.kind == InputKind.SOUNDCLOUD and len(res.rows) == 4
    assert res.rows[1].label == "SDL records" and res.rows[1].source == "soundcloud_description"
    assert res.candidates[0].label_es == "Descripción · 4 pistas sin tiempos"
    assert res.message_es.startswith("SoundCloud: Descripción")


def test_ytdlp_failure_is_a_message(tmp_path):
    res = import_from_url(FJAAK, _ytdlp(tmp_path, None, code=1, err=b"ERROR: HTTP Error 429: Too Many Requests"))
    assert res.rows == [] and res.kind == InputKind.YOUTUBE
    assert res.message_es == "No se pudieron leer los comentarios de YouTube: actualiza yt-dlp en Ajustes."


def test_ytdlp_missing_exe(tmp_path):
    y = YtDlp(tmp_path / "missing.exe", tmp_path, run=FakeRun())
    res = import_source(FJAAK, ytdlp=y)
    assert res.rows == [] and "yt-dlp no está disponible" in res.message_es


def test_review_rows_from_comments_are_unchecked(tmp_path):
    res = import_source("https://www.youtube.com/watch?v=FckHz08Z7PM", ytdlp=_ytdlp(tmp_path, full_info("FckHz08Z7PM")))
    assert len(res.rows) == 80
    review = [r for r in res.rows if r.status == RowStatus.REVISAR]
    assert {r.title for r in review} >= {"industrializer jam 3 & dj zank", "rob hood grey move"}
    assert not any(r.download for r in review)


@pytest.mark.parametrize("desc,links", [
    ("Read the tracklist here: https://mixmag.net/x.", ["https://mixmag.net/x"]),
    ("Tracklist -> https://www.1001tracklists.com/tracklist/abc/x.html", ["https://www.1001tracklists.com/tracklist/abc/x.html"]),
    ("Mi web https://example.com y mi trackid https://trackid.net/audiostreams/x", ["https://trackid.net/audiostreams/x"]),
    ("Follow me https://instagram.com/x", []),
    (None, []),
])
def test_external_tracklist_links(desc, links):
    assert external_tracklist_links(desc) == links
