"""EngineRunner against the FAKE engine: outcomes, events, redaction, ban and cancel."""
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


def test_runner_cancel_kills_the_process(tmp_path):
    def slow(net):
        net["peers"] = {"peerA": {"slow": True, "slow_s": 60}}
    res, _, _, elapsed = _run(tmp_path, "correcto", cancel_after=1.5, net_patch=slow)
    assert res.cancelled and res.exit_code is None
    assert elapsed < 30
    assert res.outcomes[1].file is None


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
