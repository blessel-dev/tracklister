"""EngineRunner against the FAKE engine: outcomes, events, redaction, ban and cancel.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import threading
import time

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
    assert [e.kind for e in events if e.snum == 1] == ["searching", "not_found"]
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


def test_runner_cancel_kills_the_process(tmp_path):
    def slow(net):
        net["peers"] = {"peerA": {"slow": True, "slow_s": 60}}
    res, _, _, elapsed = _run(tmp_path, "correcto", cancel_after=1.5, net_patch=slow)
    assert res.cancelled and res.exit_code is None
    assert elapsed < 30
    assert res.outcomes[1].file is None


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
