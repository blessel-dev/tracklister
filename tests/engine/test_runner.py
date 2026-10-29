"""EngineRunner against the FAKE engine: outcomes, events, redaction, ban and cancel.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time

import pytest

from tests.fakes.scenarios import build_scenario
from tracklister.engine.cli import EngineJob
from tracklister.engine.credentials import Credentials
from tracklister.engine.csvwriter import write_engine_csv
from tracklister.engine.presets import build_preset
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.runner import EngineRunner
from tracklister.engine.spec import EngineDialect, fake_engine_spec

CREDS = Credentials("usuario-prueba", "clave-prueba")


def _run(tmp_path, scenario, dialect=EngineDialect.SOCKSEEK3, cancel_after=None, net_patch=None):
    rows, net = build_scenario(scenario, tmp_path / "net")
    if net_patch:
        import json
        data = json.loads(net.read_text(encoding="utf-8"))
        net_patch(data)
        net.write_text(json.dumps(data), encoding="utf-8")
    work = tmp_path / "work" / "p01"
    manifest = write_engine_csv([r for r in rows if r.download], work / "input.csv")
    job = EngineJob(work, build_preset("lossless").passes[0], True, 49998)
    runner = EngineRunner(fake_engine_spec(dialect), SearchBudget(tmp_path / "budget.json"),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    events = []
    cancel = threading.Event()
    if cancel_after is not None:
        threading.Timer(cancel_after, cancel.set).start()
    t0 = time.monotonic()
    res = runner.run(job, manifest, CREDS, events.append, cancel)
    return res, events, manifest, time.monotonic() - t0


def test_runner_correcto(tmp_path):
    res, events, manifest, _ = _run(tmp_path, "correcto")
    assert res.exit_code == 0 and not res.cancelled and not res.banned
    assert {k: v.engine_state for k, v in res.outcomes.items()} == {1: "downloaded", 2: "downloaded"}
    assert res.outcomes[1].peer == "peerA" and res.outcomes[1].source_path_tail == "Live 2026\\Fjaak - Spirit.flac"
    assert [e.snum for e in events if e.kind == "searching"] == [1, 2]
    assert [e.snum for e in events if e.kind == "succeeded"] == [1, 2]
    # own username is printed by the engine but never reaches events, stdout.txt or engine.log
    blob = "\n".join(e.text for e in events) + res.stdout_path.read_text(encoding="utf-8") + \
        res.log_path.read_text(encoding="utf-8")
    assert "usuario-prueba" not in blob and "clave-prueba" not in blob and "[censurado]" in blob
    assert "usuario-prueba" not in " ".join(res.argv_redacted) and "clave-prueba" not in " ".join(res.argv_redacted)


def test_runner_sin_resultados_and_timeout(tmp_path):
    res, events, _, _ = _run(tmp_path / "a", "sin_resultados")
    assert res.exit_code == 1 and res.outcomes[1].engine_state == "not_found"
    assert res.outcomes[1].reason == "NoSearchResults"
    assert [e.kind for e in events if e.snum == 1 and e.kind != "progress"] == ["searching", "not_found"]
    # 1.0.1, R11: each line also moves the row's progress phase
    assert [e.phase for e in events if e.snum == 1 and e.kind == "progress"] == ["buscando", "sin_resultados"]
    res2, _, _, _ = _run(tmp_path / "b", "peer_timeout")
    assert res2.outcomes[1].engine_state == "failed" and res2.outcomes[1].reason == "AllDownloadsFailed"


def test_runner_sldl2(tmp_path):
    res, events, _, _ = _run(tmp_path, "sin_resultados", EngineDialect.SLDL2)
    assert res.exit_code == 0 and res.outcomes[1].engine_state == "not_found"
    assert res.outcomes[1].reason == "NoSuitableFileFound"


def test_runner_ban(tmp_path):
    res, events, _, _ = _run(tmp_path, "ban")
    assert res.banned and res.exit_code == 1
    assert res.outcomes[1].engine_state == "downloaded"
    assert res.outcomes[2].engine_state == "unknown" and res.outcomes[3].engine_state == "unknown"
    assert any(e.kind == "ban" for e in events)


def test_runner_login_failure_gives_a_clear_reason(tmp_path):
    for dialect in (EngineDialect.SOCKSEEK3, EngineDialect.SLDL2):
        res, _, _, _ = _run(tmp_path / str(dialect), "login_falla", dialect)
        assert res.fatal_es and "usuario y tu contraseña" in res.fatal_es
        assert all(o.engine_state == "unknown" for o in res.outcomes.values())
        assert "usuario-prueba" not in res.stdout_path.read_text(encoding="utf-8")


def test_fatal_patterns_ignore_track_names():
    from tracklister.engine.outputs import fatal_reason_es
    assert fatal_reason_es("  Login Failed - Address Already In Use (30s)") is None
    assert fatal_reason_es("[soulseek] Soulseek login failed: x") is not None
    assert "puerto" in fatal_reason_es("Only one usage of each socket address is normally permitted")


class _Proc:
    """Just enough of a Popen for _kill_group: a pid, and a wait() that returns or times out."""

    def __init__(self, exits: bool):
        self.pid, self.exits, self.waited = 4242, exits, []

    def wait(self, timeout=None):
        self.waited.append(timeout)
        if not self.exits:
            raise subprocess.TimeoutExpired("engine", timeout)
        return 0


def test_kill_group_sends_sigterm_and_waits():
    from tracklister.engine import runner as runner_mod
    sent = []
    proc = _Proc(exits=True)
    runner_mod._kill_group(proc, lambda pid, sig: sent.append((pid, sig)))
    assert sent == [(4242, signal.SIGTERM)] and proc.waited == [runner_mod.KILL_GRACE_S] == [3.0]


def test_kill_group_sends_sigkill_when_the_engine_does_not_stop():
    from tracklister.engine import runner as runner_mod
    sent = []
    runner_mod._kill_group(_Proc(exits=False), lambda pid, sig: sent.append((pid, sig)))
    assert sent == [(4242, signal.SIGTERM), (4242, runner_mod.SIGKILL)]
    assert runner_mod.SIGKILL == getattr(signal, "SIGKILL", 9)


@pytest.mark.parametrize("error", [ProcessLookupError, PermissionError])
def test_kill_group_leaves_a_group_that_is_gone_or_not_ours(error):
    from tracklister.engine import runner as runner_mod
    sent = []

    def killpg(pid, sig):
        sent.append(sig)
        raise error()
    proc = _Proc(exits=False)
    runner_mod._kill_group(proc, killpg)                    # never raises
    assert sent == [signal.SIGTERM] and proc.waited == []
    sent.clear()

    def term_ok_kill_fails(pid, sig):
        sent.append(sig)
        if sig != signal.SIGTERM:
            raise error()
    runner_mod._kill_group(_Proc(exits=False), term_ok_kill_fails)
    assert sent == [signal.SIGTERM, runner_mod.SIGKILL]


def test_popen_gives_the_engine_its_own_session_on_posix_only(tmp_path, monkeypatch):
    """Windows keeps exactly the Popen call of 1.0 (CREATE_NO_WINDOW); POSIX adds start_new_session."""
    from tracklister.engine import runner as runner_mod
    from tracklister.engine.runner import EngineError
    seen = {}

    def fake_popen(argv, **kw):
        seen.update(kw)
        raise OSError("no engine here")
    rows, net = build_scenario("correcto", tmp_path / "net")
    work = tmp_path / "w"
    manifest = write_engine_csv(rows, work / "input.csv")
    runner = EngineRunner(fake_engine_spec(), SearchBudget(tmp_path / "b.json"))
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    with pytest.raises(EngineError):
        runner.run(EngineJob(work, build_preset("lossless").passes[0], True, 49998), manifest, CREDS,
                   lambda e: None, threading.Event())
    assert seen["creationflags"] == runner_mod.CREATE_NO_WINDOW and seen["shell"] is False
    if os.name == "posix":
        assert seen["start_new_session"] is True
    else:
        assert "start_new_session" not in seen


def test_runner_cancel_kills_the_process(tmp_path):
    def slow(net):
        net["peers"] = {"peerA": {"slow": True, "slow_s": 60}}
    res, _, _, elapsed = _run(tmp_path, "correcto", cancel_after=1.5, net_patch=slow)
    assert res.cancelled and res.exit_code is None
    assert elapsed < 30
    assert res.outcomes[1].file is None


def test_r7_n7_json_all_is_read_before_redaction_and_kept_in_memory_only(tmp_path):
    """Audit r4-3 N7: with the password 'true' and the username 'file', the redacted line is no longer JSON
    ('"HasFreeUploadSlot":[censurado]', '"[censurado]":{...}'). The runner parses the raw line in memory;
    stdout.txt and engine.log stay redacted."""
    rows, net = build_scenario("correcto", tmp_path / "net")
    creds = Credentials("file", "true")
    work = tmp_path / "w"
    item = write_engine_csv(rows[:1], work / "input.csv")
    job = EngineJob(work, build_preset("lossless").passes[0], True, 49998, print_json_all=True,
                    input_override="artist=Fjaak, title=Spirit, length=30")
    runner = EngineRunner(fake_engine_spec(), SearchBudget(tmp_path / "b.json"),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    res = runner.run(job, item, creds, lambda e: None, threading.Event())
    assert [c["File"]["Filename"] for c in res.json_all] == ["@@musica\\Fjaak\\Live 2026\\Fjaak - Spirit.flac"]
    on_disk = (res.stdout_path.read_text(encoding="utf-8") + res.log_path.read_text(encoding="utf-8")).lower()
    assert "true" not in on_disk and "file" not in on_disk and "[censurado]" in on_disk
    # a normal pass keeps nothing in memory
    plain = runner.run(EngineJob(tmp_path / "w2", build_preset("lossless").passes[0], True, 49998),
                       write_engine_csv(rows[:1], tmp_path / "w2" / "input.csv"), CREDS, lambda e: None,
                       threading.Event())
    assert plain.json_all is None


KICKED_FOLDER_FILE = "@@x\\Soulseek Downloads\\Kicked Inside\\Fjaak - Spirit.flac"


def _kicked_folder_net(tmp_path):
    """One result whose path says «Soulseek» and «Kicked» (a common 'Soulseek Downloads' share folder)."""
    import json
    from tests.fakes.scenarios import file
    net = tmp_path / "net-kicked.json"
    net.write_text(json.dumps({"schema": "tracklister.fakenet/1", "search_delay_ms": 0, "ban_after_searches": None,
                               "peers": {}, "files": [file("peerA", KICKED_FOLDER_FILE, "Fjaak", "Spirit", 30)]}),
                   encoding="utf-8")
    return net


def test_the_json_results_line_is_neither_an_event_nor_a_ban(tmp_path):
    """Barrido AG-02: with --print json-all the engine prints all the results of a search as ONE JSON line
    (ENGINE-FACTS 4). It went through the ban check, so one result in a '…\\Soulseek Downloads\\Kicked Inside\\…'
    folder made the run look kicked. The line, up to hundreds of KB with other users' names and folders, was also
    sent as a log event (the Diagnóstico shows those in its status label). Now it is only kept as the results,
    and written redacted to stdout.txt as before."""
    from tests.fakes.scenarios import row
    net = _kicked_folder_net(tmp_path)
    work = tmp_path / "w"
    item = write_engine_csv([row(1, "Fjaak", "Spirit", dur=30)], work / "input.csv")
    job = EngineJob(work, build_preset("lossless").passes[0], True, 49998, print_json_all=True,
                    input_override="artist=Fjaak, title=Spirit, length=30")
    runner = EngineRunner(fake_engine_spec(), SearchBudget(tmp_path / "b.json"),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    events = []
    res = runner.run(job, item, CREDS, events.append, threading.Event())
    assert not res.banned and res.fatal_es is None
    assert [c["File"]["Filename"] for c in res.json_all] == [KICKED_FOLDER_FILE]
    assert not [e for e in events if (e.text or "").lstrip().startswith("[{")]
    assert "Kicked Inside" in res.stdout_path.read_text(encoding="utf-8")


def test_r4_desperate_reserves_seven_searches_per_item(tmp_path):
    """1.0.1, R4: --desperate makes up to 7 searches per item; all of them go in the app-wide budget."""
    from tracklister.core.jsonio import read_json
    from tracklister.engine.runner import DESPERATE_SEARCHES_PER_ITEM, searches_for
    rows, net = build_scenario("correcto", tmp_path / "net")
    fmt = build_preset("lossless").passes[0]
    for desperate, expected in ((False, 2), (True, 14)):
        work = tmp_path / f"w{int(desperate)}"
        manifest = write_engine_csv(rows, work / "input.csv")
        job = EngineJob(work, fmt, True, 49998, desperate=desperate)
        assert searches_for(job, manifest) == expected
        budget_file = tmp_path / f"b{int(desperate)}.json"
        runner = EngineRunner(fake_engine_spec(), SearchBudget(budget_file),
                              env={"TRACKLISTER_FAKE_NETWORK": str(net)})
        res = runner.run(job, manifest, CREDS, lambda e: None, threading.Event())
        assert len(read_json(budget_file)["events"]) == expected
        assert all(o.engine_state == "downloaded" for o in res.outcomes.values())
        assert ("--desperate" in res.argv_redacted) is desperate
    assert DESPERATE_SEARCHES_PER_ITEM == 7
    assert searches_for(EngineJob(tmp_path, fmt, False, 49998, desperate=True), []) == 7


@pytest.mark.parametrize("case", ["stdout_unwritable", "bad_line"])
def test_the_reader_keeps_draining_after_a_write_error_or_a_bad_line(tmp_path, monkeypatch, case):
    """Barrido AG-04 (V.6 N8): when stdout.txt could not be written (a full disk in the work folder) or one line
    raised while it was handled, the reader thread died. Nothing drained the pipe, the engine blocked on its next
    line and the pass only ended with «Cancelar». 60 rows that find nothing (more output than the pipe buffer)
    and a watchdog that cancels after 25 s."""
    from tests.fakes.scenarios import row
    from tracklister.engine import progress as progress_mod
    rows = [row(i, f"Nadie {i}", f"Tema Inexistente {i}", dur=30) for i in range(1, 61)]
    net = tmp_path / "net.json"
    net.write_text('{"schema": "tracklister.fakenet/1", "files": [], "peers": {}}', encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    manifest = write_engine_csv(rows, work / "input.csv")
    job = EngineJob(work, build_preset("lossless").passes[0], True, 49998, searches_per_time=1000,
                    searches_renew_s=1)
    if case == "stdout_unwritable":
        job.stdout_path.mkdir()                     # open(stdout.txt, "w") fails, as on a full disk
    else:
        def bad(self, ev, snum):
            raise ValueError("a bug in a line handler")
        monkeypatch.setattr(progress_mod.ProgressTracker, "on_event", bad)
    runner = EngineRunner(fake_engine_spec(), SearchBudget(tmp_path / "b.json", per_time=1000, window_s=1),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    cancel = threading.Event()
    watchdog = threading.Timer(25, cancel.set)
    watchdog.start()
    try:
        t0 = time.monotonic()
        res = runner.run(job, manifest, CREDS, lambda e: None, cancel)
        took = time.monotonic() - t0
    finally:
        watchdog.cancel()
    assert not res.cancelled and took < 20, (res.cancelled, round(took, 1))
    assert len(res.outcomes) == 60


def test_runner_waits_for_the_search_budget_and_can_be_cancelled(tmp_path):
    rows, net = build_scenario("correcto", tmp_path / "net")
    work = tmp_path / "w"
    manifest = write_engine_csv(rows, work / "input.csv")
    budget = SearchBudget(tmp_path / "b.json", per_time=2, window_s=220)
    budget.reserve(2)
    runner = EngineRunner(fake_engine_spec(), budget, env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    cancel = threading.Event()
    events = []
    threading.Timer(1.2, cancel.set).start()
    res = runner.run(EngineJob(work, build_preset("lossless").passes[0], True, 49998), manifest, CREDS,
                     events.append, cancel)
    assert res.cancelled and any("Esperando" in e.text for e in events)
    assert not (work / "stdout.txt").exists()
