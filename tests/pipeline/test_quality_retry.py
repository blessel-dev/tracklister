"""1.0.1 R6: the quality mark is apart from identity doubts, and «Reintentar fallos» looks for a better copy.

SPDX-License-Identifier: GPL-3.0-or-later

Fake engine only (no network). A file marked «probable MP3 convertido» stays in the set with its number; a
retry bans the user that sent it, and only a copy without the mark (or with a clearly higher cut) replaces
it; the marked file then goes to _dudosos and is never deleted (plan D7).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from tests.fakes.scenarios import build_scenario, file, row
from tracklister.core.jsonio import read_json
from tracklister.core.model import ResultState, SetDoc, SourceRef
from tracklister.core.paths import app_paths
from tracklister.core.settings import Settings
from tracklister.engine.credentials import Credentials
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.runner import EngineRunner
from tracklister.engine.spec import fake_engine_spec
from tracklister.library.index import LibraryIndex
from tracklister.organize.journal import Journal
from tracklister.pipeline.session import (
    NOT_RETRIED_QUALITY_ES, REPLACED_MARKED_ES, SetSession, set_has_files,
)

CREDS = Credentials("usuario-prueba", "clave-prueba")
MARKED = "@@x\\Border One\\Border One - Spectral Tension.flac"
NAME = "01 - Border One - Spectral Tension.flac"


def _session(tmp_path: Path, scenario: str, name: str, net_extra=()):
    rows, net = build_scenario(scenario, tmp_path / f"net-{name}")
    data = json.loads(net.read_text(encoding="utf-8"))
    data["files"] += list(net_extra)
    net.write_text(json.dumps(data), encoding="utf-8")
    paths = app_paths().ensure()
    settings = Settings(preset_id="lossless", library_root=str(tmp_path / "biblioteca"))
    s = SetSession.create(name, rows, [SourceRef("tabla", "t.csv")], settings, tmp_path / "biblioteca", paths)
    runner = EngineRunner(fake_engine_spec(), SearchBudget(paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    return s, runner


def _network(tmp_path: Path, name: str, files: list[dict]) -> str:
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps({"schema": "tracklister.fakenet/1", "search_delay_ms": 0, "ban_after_searches": None,
                             "peers": {}, "files": files}), encoding="utf-8")
    return str(p)


def _res(s: SetSession, pos: int = 1):
    return s.doc.results[next(r.uid for r in s.doc.rows if r.pos == pos)]


def _marked_set(tmp_path, name="Marcado"):
    s, runner = _session(tmp_path, "calidad_marcada", name)
    s.run(runner, CREDS, lambda e: None, threading.Event(), lambda rows: set())
    r = _res(s)
    assert r.state == ResultState.REVISAR_CALIDAD and r.doubt is None and r.file == NAME and r.peer == "peerMarca"
    return s, runner


def _marked_file():
    return file("peerMarca", MARKED, "Border One", "Spectral Tension", 30, audio={"lowpass_hz": 16500})


def test_v101_a_normal_run_never_downloads_a_marked_file_again(tmp_path):
    s, runner = _marked_set(tmp_path)
    before = (s.set_dir / NAME).read_bytes()
    passes = len(s.doc.passes)
    s.run(runner, CREDS, lambda e: None, threading.Event(), lambda rows: set())
    assert len(s.doc.passes) == passes and (s.set_dir / NAME).read_bytes() == before
    assert _res(s).state == ResultState.REVISAR_CALIDAD


def test_v101_retry_bans_the_peer_and_a_clean_copy_replaces_the_marked_file(tmp_path):
    s, runner = _marked_set(tmp_path)
    old = (s.set_dir / NAME).read_bytes()
    clean = file("peerLimpio", "@@y\\Border One\\Border One - Spectral Tension.flac", "Border One",
                 "Spectral Tension", 30, audio={"seed": 7})
    runner.env["TRACKLISTER_FAKE_NETWORK"] = _network(tmp_path, "limpio", [_marked_file(), clean])
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    argv = read_json(Path(s.doc.passes[-1].work_dir) / "pass.json")["argv_redacted"]
    assert argv[argv.index("--banned-users") + 1] == "peerMarca" and s.doc.passes[-1].name == "lossless-relajada"
    r = _res(s)
    assert r.state == ResultState.VERIFICADO and r.peer == "peerLimpio" and r.file == NAME
    assert REPLACED_MARKED_ES in r.reasons and "probable_mp3_convertido" not in r.flags
    assert (s.set_dir / NAME).read_bytes() != old
    assert (s.set_dir / "_dudosos" / NAME).read_bytes() == old              # never deleted
    assert "peerMarca" in r.rejected_peers
    assert Journal(s.set_dir).batches()[-1]["committed"]
    s.finalize(LibraryIndex(app_paths().library_file))
    rep = (s.set_dir / "Informe - Marcado.txt").read_text(encoding="utf-8")
    assert "Resumen: verificado 1" in rep and "revisar calidad" not in rep.split("\n")[5]


def test_place_failure_keeps_the_marked_file_linked(tmp_path, monkeypatch):
    """CL-22: a clean copy arrived, the marked file went to _dudosos, and then placing the copy failed (a full
    disk, a locked file). The row kept «Verificado · revisar calidad» with no file: no «Archivo:» in the report,
    not in the library, «Pendiente» on the next load, and the marked file a stray in _dudosos. Now the marked
    file goes back to its name in the set and the row keeps it, with the reason of the error."""
    import errno

    import tracklister.pipeline.session as session_mod
    s, runner = _marked_set(tmp_path)
    old = (s.set_dir / NAME).read_bytes()
    clean = file("peerLimpio", "@@y\\Border One\\Border One - Spectral Tension.flac", "Border One",
                 "Spectral Tension", 30, audio={"seed": 7})
    runner.env["TRACKLISTER_FAKE_NETWORK"] = _network(tmp_path, "limpio", [_marked_file(), clean])

    def full_disk(*args, **kw):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(session_mod, "place_verified", full_disk)
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    r = _res(s)
    assert (r.state, r.file) == (ResultState.REVISAR_CALIDAD, NAME), r.reasons
    assert (s.set_dir / NAME).read_bytes() == old
    dudosos = s.set_dir / "_dudosos"
    assert not dudosos.exists() or list(dudosos.iterdir()) == []
    assert r.reasons[-1] == ("No se pudo mover o guardar el archivo descargado (No space left on device). Pulsa "
                             "«Reintentar fallos» para volver a intentarlo.")
    again = SetSession.load(s.set_dir, s.settings, app_paths())           # the next load keeps it too
    assert (_res(again).state, _res(again).file) == (ResultState.REVISAR_CALIDAD, NAME)


def test_v101_a_copy_that_is_not_better_leaves_everything_as_it_was(tmp_path):
    s, runner = _marked_set(tmp_path)
    old = (s.set_dir / NAME).read_bytes()
    worse = file("peerOtro", "@@y\\Border One\\Border One - Spectral Tension.flac", "Border One",
                 "Spectral Tension", 30, audio={"lowpass_hz": 16000, "seed": 3})
    runner.env["TRACKLISTER_FAKE_NETWORK"] = _network(tmp_path, "peor", [_marked_file(), worse])
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    r = _res(s)
    assert r.state == ResultState.REVISAR_CALIDAD and r.peer == "peerMarca" and r.file == NAME
    assert (s.set_dir / NAME).read_bytes() == old and not (s.set_dir / "_dudosos").exists()
    assert any("no apareció una copia mejor" in x for x in r.reasons)
    assert "peerOtro" in r.rejected_peers                                   # not asked again for this track
    assert not (Path(s.doc.passes[-1].work_dir) / "in").exists()            # the copy went with the work folder
    # the next retry bans both users
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    argv = read_json(Path(s.doc.passes[-1].work_dir) / "pass.json")["argv_redacted"]
    assert set(argv[argv.index("--banned-users") + 1].split(",")) == {"peerMarca", "peerOtro"}


def test_v101_a_still_marked_copy_with_a_clearly_higher_cut_replaces_it(tmp_path):
    s, runner = _marked_set(tmp_path)
    higher = file("peerMejor", "@@y\\Border One\\Border One - Spectral Tension.flac", "Border One",
                  "Spectral Tension", 30, audio={"lowpass_hz": 18000, "seed": 5})
    runner.env["TRACKLISTER_FAKE_NETWORK"] = _network(tmp_path, "mejor", [_marked_file(), higher])
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    r = _res(s)
    assert r.state == ResultState.REVISAR_CALIDAD and r.peer == "peerMejor" and REPLACED_MARKED_ES in r.reasons
    assert r.spectral_cutoff_hz >= 17500 and (s.set_dir / "_dudosos" / NAME).is_file()


def test_v101_another_song_never_replaces_the_marked_file(tmp_path):
    s, runner = _marked_set(tmp_path)
    old = (s.set_dir / NAME).read_bytes()
    other = file("peerOtro", "@@y\\Border One\\Border One - Spectral Tension Two.flac", "Border One",
                 "Spectral Tension Two", 30)
    runner.env["TRACKLISTER_FAKE_NETWORK"] = _network(tmp_path, "otra", [_marked_file(), other])
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    r = _res(s)
    assert r.state == ResultState.REVISAR_CALIDAD and (s.set_dir / NAME).read_bytes() == old
    assert not (s.set_dir / "_dudosos").exists() and "peerOtro" in r.rejected_peers


@pytest.mark.parametrize("peer", [None, "peer,con coma"])
def test_v101_a_marked_file_of_an_unknown_peer_is_not_retried_and_says_why(tmp_path, peer):
    s, runner = _marked_set(tmp_path)
    r = _res(s)
    r.peer = peer
    s.save()
    passes = len(s.doc.passes)
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    assert len(s.doc.passes) == passes and _res(s).state == ResultState.REVISAR_CALIDAD
    assert NOT_RETRIED_QUALITY_ES in _res(s).reasons and _res(s).file == NAME


def test_v101_the_summary_counts_quality_apart_from_dudoso(tmp_path):
    s, runner = _session(tmp_path, "todos_los_estados_101", "Todos 101")
    s.run(runner, CREDS, lambda e: None, threading.Event(), lambda rows: set())
    got = {r.pos: _res(s, r.pos).state for r in s.doc.rows}
    assert got[8] == ResultState.REVISAR_CALIDAD and got[2] == ResultState.DUDOSO
    rep = s.report_text()
    summary = rep.split("\n")[5]
    assert summary == ("Resumen: verificado 2, verificado \u00b7 revisar calidad 1, dudoso 1, no encontrado 1, "
                       "no cumple formato 1, fallida 1, omitida 1")
    assert "08. Border One - Spectral Tension  [Verificado \u00b7 revisar calidad, confianza 100/100]" in rep
    assert "scúchalo" not in rep


def test_v101_set_has_files(tmp_path):
    s, _ = _session(tmp_path, "calidad_marcada", "Vacio")
    assert not set_has_files(s.set_dir)                     # saved, nothing downloaded yet
    assert not set_has_files(tmp_path / "no existe")
    s2, runner = _marked_set(tmp_path, "Con archivos")
    assert set_has_files(s2.set_dir)
    (s2.set_dir / NAME).unlink()
    assert not set_has_files(s2.set_dir)
    assert SetDoc.from_dict(read_json(s2.set_dir / ".tracklister" / "set.json")).results    # untouched
