"""Output parsing against the REAL engines' mock-mode outputs (tests/fixtures/engine/mock-run).

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tracklister.engine.cli import EngineJob
from tracklister.engine.csvwriter import ManifestItem
from tracklister.engine.outputs import (
    collect_outputs, match_snum, parse_index, parse_playlist_failures, parse_progress_line,
)
from tracklister.engine.presets import build_preset
from tracklister.engine.spec import EngineDialect

MOCK = Path(__file__).parents[1] / "fixtures" / "engine" / "mock-run"
D3, D2 = EngineDialect.SOCKSEEK3, EngineDialect.SLDL2


def _manifest(eid):
    return [ManifestItem.from_dict(d) for d in json.loads((MOCK / eid / "manifest.json").read_text(encoding="utf-8"))]


def test_progress_lines_sockseek3_real_output():
    lines = (MOCK / "sockseek-3.0.5" / "stdout.txt").read_text(encoding="utf-8").splitlines()
    evs = [parse_progress_line(D3, x) for x in lines]
    kinds = [e.kind for e in evs if e and e.kind != "log"]
    assert kinds.count("searching") == 7 and kinds.count("succeeded") == 5 and kinds.count("not_found") == 2
    m = _manifest("sockseek-3.0.5")
    succ = [e for e in evs if e and e.kind == "succeeded"]
    assert sorted(match_snum(e.subject, m) for e in succ) == [1, 2, 4, 5, 6]
    nf = [e for e in evs if e and e.kind == "not_found"]
    assert sorted(match_snum(e.subject, m) for e in nf) == [3, 7]


def test_progress_lines_sldl2_real_output():
    lines = (MOCK / "sldl-2.6.0" / "stdout.txt").read_text(encoding="utf-8").splitlines()
    evs = [e for e in (parse_progress_line(D2, x) for x in lines) if e]
    m = _manifest("sldl-2.6.0")
    s = [e for e in evs if e.kind == "searching"]
    assert [match_snum(e.subject, m) for e in s] == [1, 2, 3, 4, 5, 6, 7]
    assert [match_snum(e.subject, m) for e in evs if e.kind == "not_found"] == [3, 7]
    assert sum(1 for e in evs if e.kind == "downloading") == 5


@pytest.mark.parametrize("line,kind", [
    ("[cli] Completed: 5 succeeded, 2 failed.", "log"),
    ("[soulseek] Soulseek server kicked this client, probably because the same account logged in "
     "elsewhere. Stopping this run.", "ban"),
    ("[009] SongJob: searching: Server - Ban", "searching"),
    ("[004] SongJob: timed out: A - B: peer\\x.flac", "failed"),
    ("[004] SongJob: failed [All downloads failed]: A - B", "failed"),
    ("[004] SongJob: failed [No matching results]: A - B", "not_found"),
])
def test_progress_line_kinds_v3(line, kind):
    assert parse_progress_line(D3, line).kind == kind


def test_progress_line_kinds_v2():
    assert parse_progress_line(D2, "TimedOut:      peer\\..\\x.flac [1s]").kind == "failed"
    assert parse_progress_line(D2, "Succeeded:     peer\\..\\x.flac [1s]").kind == "succeeded"
    assert parse_progress_line(D2, "") is None


@pytest.mark.parametrize("eid,dialect,reason", [("sockseek-3.0.5", D3, "NoSearchResults"),
                                                 ("sldl-2.6.0", D2, "NoSuitableFileFound")])
def test_parse_real_index_and_playlist(eid, dialect, reason):
    rows = parse_index(dialect, MOCK / eid / "index.csv")
    assert len(rows) == 7
    ok = [r for r in rows if r["state"] == 1]
    assert {r["filepath"].replace("\\", "/") for r in ok} >= {"in/1/Fjaak - Spirit.flac", "in/4/Same Name.flac",
                                                               "in/5/Same Name.flac"}
    bad = [r for r in rows if r["state"] == 2]
    assert {r["reason_name"] for r in bad} == {reason}
    assert any(r["artist"] == 'Quote "Q" Artist' for r in bad)
    fails = parse_playlist_failures(MOCK / eid / "playlist.m3u")
    assert fails["nobody known - nonexistent track"] == reason


@pytest.mark.parametrize("eid,dialect", [("sockseek-3.0.5", D3), ("sldl-2.6.0", D2)])
def test_collect_outputs_rebuilt_from_real_tree(tmp_path, eid, dialect):
    work = tmp_path / "p01"
    for line in (MOCK / eid / "tree.txt").read_text(encoding="utf-8").splitlines():
        rel = line.rsplit("  ", 1)[0]
        if rel.startswith("in/"):
            f = work / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"x" * 10)
    (work / "in" / "6" / "leftover.flac.incomplete").write_bytes(b"x")
    for name in ("index.csv", "playlist.m3u", "stdout.txt"):
        shutil.copy(MOCK / eid / name, work / name)
    job = EngineJob(work, build_preset("lossless").passes[0], True, 49998)
    out = collect_outputs(job, _manifest(eid), dialect)
    assert out[1].engine_state == "downloaded" and out[1].file.name == "Fjaak - Spirit.flac"
    assert out[1].peer == "local"
    assert out[6].file.name == "Comma, Artist - Say, Hi.wav"       # .incomplete ignored
    assert out[3].engine_state == "not_found" and out[7].engine_state == "not_found"
    assert out[4].file.parent.name == "4" and out[5].file.parent.name == "5"
    if dialect == D3:
        assert out[2].source_path_tail == "Techno\\Chris Liebing - Higher Things (FJAAK Remix).flac"


def test_collect_outputs_without_any_engine_files(tmp_path):
    job = EngineJob(tmp_path, build_preset("lossless").passes[0], False, 49998)
    m = [ManifestItem(1, "u1", 1, "A", "T", None)]
    assert collect_outputs(job, m, D3)[1].engine_state == "unknown"
