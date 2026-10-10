"""1.0.1 R11, engine side: the phase and the bytes of each row from the plain lines and the incomplete files.

SPDX-License-Identifier: GPL-3.0-or-later

No network: synthetic lines in the formats of ENGINE-FACTS.md section 1, files written by the test, and
the fake engine in its slow mode ("write_s") for the end-to-end runs of both dialects.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from tests.fakes.scenarios import file as mkfile, row
from tracklister.engine.cli import EngineJob
from tracklister.engine.credentials import Credentials
from tracklister.engine.csvwriter import ManifestItem, write_engine_csv
from tracklister.engine.outputs import parse_progress_line
from tracklister.engine.presets import build_preset
from tracklister.engine.progress import (
    PHASE_ANOTHER_COPY, PHASE_DOWNLOADED, PHASE_DOWNLOADING, PHASE_FAILED, PHASE_NOT_FOUND, PHASE_QUEUED,
    PHASE_SEARCHING, POLL_S, ProgressTracker, remote_name,
)
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.runner import EngineRunner
from tracklister.engine.spec import EngineDialect, fake_engine_spec

D3, D2 = EngineDialect.SOCKSEEK3, EngineDialect.SLDL2
CREDS = Credentials("usuario-prueba", "clave-prueba")


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _manifest():
    return [ManifestItem(1, "u1", 1, "Fjaak", "Spirit", 30), ManifestItem(2, "u2", 2, "Red Rooms", "Trip", 305)]


def _feed(tr: ProgressTracker, dialect, line: str, snum):
    return tr.on_event(parse_progress_line(dialect, line), snum)


def test_r11_phases_from_the_sockseek_lines(tmp_path):
    tr = ProgressTracker(D3, tmp_path / "in", _manifest(), clock=Clock())
    assert [e.phase for e in _feed(tr, D3, "[003] SongJob: searching: Fjaak - Spirit", 1)] == [PHASE_SEARCHING]
    assert [e.phase for e in _feed(tr, D3, "[003] SongJob: queued (r): Fjaak - Spirit: peerA\\..\\a\\b\\x.flac", 1)] \
        == [PHASE_QUEUED]
    ev = _feed(tr, D3, "[003] SongJob: downloading: Fjaak - Spirit: peerA\\..\\Music\\Fjaak\\Fjaak - Spirit.flac", 1)
    assert [(e.phase, e.bytes_done, e.bytes_total) for e in ev] == [(PHASE_DOWNLOADING, 0, None)]
    assert ev[0].snum == 1 and ev[0].kind == "progress" and ev[0].text == ""        # no peer name in the event
    # the engine gives up this copy and starts another one: the bar starts again
    ev = _feed(tr, D3, "[003] SongJob: downloading: Fjaak - Spirit: peerB\\..\\Otra\\Fjaak - Spirit (1).flac", 1)
    assert [(e.phase, e.bytes_done) for e in ev] == [(PHASE_ANOTHER_COPY, 0)]
    assert [e.phase for e in _feed(tr, D3, "[003] SongJob: succeeded: Fjaak - Spirit: peerB\\..\\x.flac", 1)] \
        == [PHASE_DOWNLOADED]
    assert [e.phase for e in _feed(tr, D3, "[004] SongJob: failed [No search results]: Red Rooms - Trip", 2)] \
        == [PHASE_NOT_FOUND]
    assert [e.phase for e in _feed(tr, D3, "[004] SongJob: failed [All downloads failed]: Red Rooms - Trip", 2)] \
        == [PHASE_FAILED]
    # the same state again is not sent twice; other lines mean nothing here
    assert _feed(tr, D3, "[004] SongJob: failed [All downloads failed]: Red Rooms - Trip", 2) == []
    assert _feed(tr, D3, "[cli] Completed: 1 succeeded, 1 failed.", None) == []


def test_r11_bytes_come_from_the_growing_incomplete_file(tmp_path):
    clock = Clock()
    out = tmp_path / "in"
    tr = ProgressTracker(D3, out, _manifest(), clock=clock)
    _feed(tr, D3, "[003] SongJob: searching: Fjaak - Spirit", 1)
    _feed(tr, D3, "[003] SongJob: downloading: Fjaak - Spirit: peerA\\..\\Music\\Fjaak\\Fjaak - Spirit.flac", 1)
    stage = out / ".sockseek-staging" / "0f3a" / "Fjaak - Spirit.flac.incomplete"
    stage.parent.mkdir(parents=True)
    stage.write_bytes(b"x" * 1000)
    got = tr.poll()
    assert [(e.snum, e.phase, e.bytes_done, e.bytes_total) for e in got] == [(1, PHASE_DOWNLOADING, 1000, None)]
    stage.write_bytes(b"x" * 5000)
    assert tr.poll() == []                                   # at most every POLL_S
    clock.t += POLL_S
    assert [e.bytes_done for e in tr.poll()] == [5000]
    clock.t += POLL_S
    assert tr.poll() == []                                   # nothing new: nothing sent


def test_v101_1_n2_a_long_incomplete_path_is_measured_with_the_long_path_prefix(tmp_path, monkeypatch):
    """Audit v101-1 N2: the tracker listed and stat'ed in/<snum>/<name>.incomplete without the \\\\?\\ prefix.
    On a PC with LongPathsEnabled=0 a long remote name has no bar, and tests/integration/test_long_paths.py
    failed now and then (the poll only runs while a row downloads). Now it goes through the prefix, like
    outputs._files_in: the bytes are seen and no unprefixed long path is tried."""
    from tests.fakes.maxpath import simulate_max_path
    from tracklister.organize.naming import win_long

    clock = Clock()
    out = tmp_path / ("w" * 120) / "in"
    long_name = "Fjaak - Spirit (" + "Extended " * 14 + "Mix).flac"
    tr = ProgressTracker(D2, out, _manifest(), clock=clock)
    _feed(tr, D2, "Searching: Fjaak - Spirit (30s)", 1)
    ev = _feed(tr, D2, f"Initialize: peerA\\..\\{long_name} [30s/44.1kHz/4.0MB]", None)
    assert [(e.snum, e.phase) for e in ev] == [(1, PHASE_DOWNLOADING)]
    part = out / "1" / (long_name + ".incomplete")
    assert len(str(part)) > 260
    os.makedirs(win_long(part.parent), exist_ok=True)
    with open(win_long(part), "wb") as f:
        f.write(b"x" * 4096)
    refused = simulate_max_path(monkeypatch)
    assert [(e.snum, e.bytes_done) for e in tr.poll()] == [(1, 4096)]
    assert refused == []


def test_r11_two_rows_with_the_same_file_name_get_no_bytes(tmp_path):
    clock = Clock()
    out = tmp_path / "in"
    tr = ProgressTracker(D3, out, _manifest(), clock=clock)
    _feed(tr, D3, "[003] SongJob: downloading: Fjaak - Spirit: peerA\\..\\a\\Same Name.flac", 1)
    _feed(tr, D3, "[004] SongJob: downloading: Red Rooms - Trip: peerB\\..\\b\\Same Name.flac", 2)
    for job in ("j1", "j2"):
        p = out / ".sockseek-staging" / job / "Same Name.flac.incomplete"
        p.parent.mkdir(parents=True)
        p.write_bytes(b"y" * 10)
    assert tr.poll() == []                                   # never a bar from another row's file


def test_r11_sldl_initialize_line_gives_the_total_and_goes_to_its_row_by_title(tmp_path):
    clock = Clock()
    out = tmp_path / "in"
    tr = ProgressTracker(D2, out, _manifest(), clock=clock)
    _feed(tr, D2, "Searching: Fjaak - Spirit (30s)", 1)
    _feed(tr, D2, "Searching: Red Rooms - Trip (305s)", 2)
    ev = _feed(tr, D2, "Initialize: peerB\\..\\Red Rooms - Trip (Original Mix).flac [305s/44.1kHz/41.0MB]", None)
    assert [(e.snum, e.phase, e.bytes_total) for e in ev] == [(2, PHASE_DOWNLOADING, int(41.0 * 1024 * 1024))]
    part = out / "Red Rooms - Trip (Original Mix).flac.incomplete"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"z" * 2048)
    assert [(e.snum, e.bytes_done) for e in tr.poll()] == [(2, 2048)]
    ev = _feed(tr, D2, "Succeeded:     peerB\\..\\Red Rooms - Trip (Original Mix).flac [305s/44.1kHz/41.0MB]", None)
    assert [(e.snum, e.phase, e.bytes_done) for e in ev] == [(2, PHASE_DOWNLOADED, int(41.0 * 1024 * 1024))]
    # a file whose name fits no searching row (or two of them) goes nowhere
    assert _feed(tr, D2, "Initialize: peerC\\..\\Otra Cosa.flac [10s/1.0MB]", None) == []


def test_r11_remote_name():
    assert remote_name("peerA\\..\\Music\\Fjaak\\Fjaak - Spirit.flac") == "Fjaak - Spirit.flac"
    assert remote_name("peerB\\..\\x.flac [305s/44.1kHz/41.0MB]") == "x.flac"
    assert remote_name("sin ruta") is None


def _slow_run(tmp_path: Path, dialect: EngineDialect):
    net = {"schema": "tracklister.fakenet/1", "search_delay_ms": 0, "ban_after_searches": None, "peers": {},
           "write_s": 2.4, "files": [mkfile("peerA", "@@x\\Fjaak\\Fjaak - Spirit.flac", "Fjaak", "Spirit", 20)]}
    tmp_path.mkdir(parents=True, exist_ok=True)
    netp = tmp_path / "net.json"
    netp.write_text(json.dumps(net), encoding="utf-8")
    work = tmp_path / "w"
    manifest = write_engine_csv([row(1, "Fjaak", "Spirit", dur=20)], work / "input.csv")
    job = EngineJob(work, build_preset("lossless").passes[0], True, 49998)
    runner = EngineRunner(fake_engine_spec(dialect), SearchBudget(tmp_path / "budget.json"),
                          env={"TRACKLISTER_FAKE_NETWORK": str(netp)})
    events = []
    res = runner.run(job, manifest, CREDS, events.append, threading.Event())
    return res, [e for e in events if e.kind == "progress"]


def test_r11_fake_engine_slow_mode_sldl_shows_a_percentage(tmp_path):
    res, prog = _slow_run(tmp_path, D2)
    assert res.outcomes[1].file is not None
    phases = [e.phase for e in prog]
    assert phases[0] == PHASE_SEARCHING and phases[-1] == PHASE_DOWNLOADED
    downloading = [e for e in prog if e.phase == PHASE_DOWNLOADING]
    done = [e.bytes_done for e in downloading]
    assert len(downloading) >= 3 and done == sorted(done) and done[0] == 0 and done[-1] > 0
    assert all(e.bytes_total and e.bytes_total > 0 for e in downloading)       # 2.x says the size
    size = os.path.getsize(res.outcomes[1].file)
    assert abs(downloading[0].bytes_total - size) <= 0.06 * 1024 * 1024        # one decimal of MB


def test_r11_fake_engine_slow_mode_sockseek_shows_the_megabytes(tmp_path):
    res, prog = _slow_run(tmp_path, D3)
    assert res.outcomes[1].file is not None
    downloading = [e for e in prog if e.phase == PHASE_DOWNLOADING]
    done = [e.bytes_done for e in downloading]
    assert len(downloading) >= 3 and done == sorted(done) and done[-1] > 0
    assert all(e.bytes_total is None for e in downloading)                    # 3.x plain lines carry no size
    assert prog[-1].phase == PHASE_DOWNLOADED
