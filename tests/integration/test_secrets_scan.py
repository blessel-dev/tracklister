"""Count-only secrets scan (tools/secrets_scan.py): the repo carries ZERO real credentials, and a
full fake run never writes the account to disk. No test prints a matched value: only counts.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
from pathlib import Path

import pytest

from tests.fakes.scenarios import build_scenario
from tests.integration.conftest import PASSWORD, USER, make_services
from tracklister.core.model import SourceRef
from tracklister.engine.credentials import Credentials

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("tracklister_secrets_scan", REPO / "tools" / "secrets_scan.py")
ss = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ss                 # dataclasses look their module up while the class is built
_spec.loader.exec_module(ss)

Q = chr(34)   # a double quote, so this file itself never contains a credential-shaped literal


def _counts_only(res) -> dict[str, int]:
    return {k: v for k, v in res.counts.items() if v}


def test_publishable_repo_has_zero_credentials():
    files = ss.publishable_files(REPO)
    assert len(files) > 300                                    # really the whole tree, not an empty list
    # A GitHub runner has no personal identity (build.py --no-identity-scan says the same): its account
    # is a generic word, and on macOS it is "runner", which the code itself uses (engine.runner).
    identity = () if os.environ.get("GITHUB_ACTIONS") == "true" else ss.local_identity_patterns()
    res = ss.scan(files, ss.PATTERNS + identity, root=REPO)
    assert res.files_scanned >= len(files) - 1
    assert _counts_only(res) == {}, ss.report_lines(res)       # counts and file names only


def test_the_scanner_finds_planted_credentials(tmp_path):
    """Positive control: each shape is detected (values built at run time, never written here)."""
    v = "Zq" + "8kW" + "pT3"
    planted = {
        "sldl.conf": f"username = Dj{v}\npass{''}word = {v}\n",
        "run.bat": "sldl.exe lista.csv --us" + "er Dj" + v + " --pa" + "ss " + v + " -p C:\\musica\n",
        "settings.json": "{" + Q + "pass" + "word" + Q + ": " + Q + v + Q + "}",
        "config.py": f"SOULSEEK_PASS{''}WORD = {Q}{v}{Q}\npass{''}word = {Q}{v}{Q}\n",
        "keys.txt": "AKIA" + "Q" * 16 + "\n" + "gh" + "p_" + "a" * 36 + "\n-----BEGIN " + "RSA PRIVATE KEY-----\n",
        "dummy.conf": "username = usuario-prueba\npassword = clave-prueba\n" + "--user *** --pass ***" + "\n",
    }
    for name, text in planted.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    res = ss.scan(ss.files_under([tmp_path]), ss.PATTERNS, root=tmp_path)
    got = _counts_only(res)
    assert got == {"conf_account_line": 2, "cli_account": 2, "json_secret": 1, "py_secret_literal": 2,
                   "aws_access_key": 1, "github_token": 1, "pem_private_key": 1}, sorted(got)
    assert "dummy.conf" not in {f for files in res.files.values() for f in files}


def test_a_full_fake_run_never_writes_the_account_to_disk(tmp_path):
    """Download (fake engine) + finalize + Diagnostico with download: then every file the app
    wrote (settings, library, work dirs, engine logs, pass.json, set.json, reports, the saved
    Diagnostico) is searched for the account in UTF-8, UTF-16 and latin-1. Expected: 0."""
    rows, net = build_scenario("todos_los_estados", tmp_path / "net")
    services = make_services(tmp_path, network=net)
    session = services.create_session("Todos", rows, [SourceRef("tabla", "todos.csv")])
    creds = Credentials(USER, PASSWORD)
    events = []
    session.run(services.make_runner(), creds, events.append, threading.Event(), lambda r: set())
    session.finalize(services.library())
    report, saved = services.run_diagnostic(rows, creds, download=True, max_rows=3)
    assert saved is not None and saved.is_file()
    assert USER not in report and PASSWORD not in report and "peer-1" in report
    assert "peerA" not in report and "lento" not in report
    texts = " ".join(e.message_es for e in events)
    assert USER not in texts and PASSWORD not in texts
    work = list(services.paths.work_dir.rglob("pass.json"))
    assert work and all("***" in json.loads(p.read_text(encoding="utf-8"))["argv_redacted"] for p in work)
    logs = list(services.paths.work_dir.rglob("engine.log")) + list(services.paths.work_dir.rglob("stdout.txt"))
    assert logs                                                # the engine really wrote its logs
    written = ss.files_under([services.paths.config_dir, services.paths.data_dir, tmp_path / "biblioteca"])
    assert len(written) > 10
    assert ss.count_literals(written, [USER, PASSWORD]) == 0


@pytest.mark.parametrize("value", ["usuario-prueba", "<usuario>", "***", "{user}", "%USERNAME%", "[censurado]"])
def test_dummies_and_placeholders_are_not_counted(value):
    assert ss.is_dummy(value)


def test_real_looking_values_are_counted():
    assert not ss.is_dummy("Zq8kWpT3") and not ss.is_dummy("dj-blessel-2026")


def test_the_computer_name_comes_from_the_host_name_where_computername_is_unset(monkeypatch, tmp_path):
    """macOS has no COMPUTERNAME: the scan still looks for this computer's name (invented values)."""
    import socket
    monkeypatch.delenv("COMPUTERNAME", raising=False)
    monkeypatch.setattr(socket, "gethostname", lambda: "Mac-de-Prueba.local")
    assert ss.computer_names() == {"Mac-de-Prueba.local", "Mac-de-Prueba"}
    (tmp_path / "nota.txt").write_text("hecho en mac-de-prueba, ver Mac-de-Prueba.local\n", encoding="utf-8")
    hosts = [p for p in ss.local_identity_patterns() if p.key == "computer_name"]
    assert len(hosts) == 2
    res = ss.scan([tmp_path / "nota.txt"], hosts, root=tmp_path)
    assert res.counts["computer_name"] == 3                    # the short name twice, the full name once
    monkeypatch.setenv("COMPUTERNAME", "PC-PRUEBA")            # Windows: COMPUTERNAME only, as before
    assert ss.computer_names() == {"PC-PRUEBA"}
    assert [p.key for p in ss.local_identity_patterns()].count("computer_name") == 1
