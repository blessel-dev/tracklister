"""End to end with the FAKE engine: every scenario of the brief's offline integration list.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import mutagen
import pytest
import soundfile as sf

from tests.fakes.scenarios import SCENARIO_PRESET, build_scenario, file, row
from tracklister.core.jsonio import read_json
from tracklister.core.layout import set_doc_path
from tracklister.core.model import DoubtKind, DuplicateChoice, ResultState, SetDoc, SourceRef
from tracklister.core.paths import app_paths
from tracklister.core.settings import Settings
from tracklister.engine.credentials import Credentials
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.runner import EngineRunner
from tracklister.engine.spec import fake_engine_spec
from tracklister.library.index import LibraryIndex
from tracklister.organize.journal import Journal
from tracklister.pipeline.report import STRAY_TITLE_ES
from tracklister.pipeline.session import NOT_RETRIED_ES, SAME_FILE_ES, SetSession

CREDS = Credentials("usuario-prueba", "clave-prueba")


class Harness:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.paths = app_paths().ensure()
        self.lib_root = tmp_path / "biblioteca"
        self.library = LibraryIndex(self.paths.library_file)

    def session(self, scenario: str, name: str | None = None, preset: str | None = None, net_patch=None):
        rows, net = build_scenario(scenario, self.tmp / f"net-{scenario}-{name or ''}")
        if net_patch:
            data = json.loads(net.read_text(encoding="utf-8"))
            net_patch(data)
            net.write_text(json.dumps(data), encoding="utf-8")
        settings = Settings(preset_id=preset or SCENARIO_PRESET.get(scenario, "lossless"),
                            library_root=str(self.lib_root))
        s = SetSession.create(name or f"Set {scenario}", rows, [SourceRef("tabla", f"{scenario}.csv")], settings,
                              self.lib_root, self.paths)
        runner = EngineRunner(fake_engine_spec(), SearchBudget(self.paths.search_budget_file),
                              env={"TRACKLISTER_FAKE_NETWORK": str(net)})
        return s, runner

    def session_with(self, scenario: str, name: str, preset: str, extra_rows=(), extra_files=()):
        """A scenario plus more rows and files (one engine pass then holds several kinds of file)."""
        rows, net = build_scenario(scenario, self.tmp / f"net-{scenario}-{name}")
        data = json.loads(net.read_text(encoding="utf-8"))
        data["files"] += list(extra_files)
        net.write_text(json.dumps(data), encoding="utf-8")
        settings = Settings(preset_id=preset, library_root=str(self.lib_root))
        s = SetSession.create(name, rows + list(extra_rows), [SourceRef("tabla", f"{scenario}.csv")], settings,
                              self.lib_root, self.paths)
        runner = EngineRunner(fake_engine_spec(), SearchBudget(self.paths.search_budget_file),
                              env={"TRACKLISTER_FAKE_NETWORK": str(net)})
        return s, runner

    def run(self, s: SetSession, runner: EngineRunner, approve=None):
        events, asked = [], []

        def ask(rows):
            asked.append([r.uid for r in rows])
            return set(approve(rows)) if approve else set()
        s.run(runner, CREDS, events.append, threading.Event(), ask)
        return events, asked


def _res(s: SetSession, pos: int):
    row = next(r for r in s.doc.rows if r.pos == pos)
    return s.doc.results[row.uid]


def _files(d: Path):
    return sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file() and ".tracklister" not in p.parts)


def test_correcto_names_states_report_library(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("correcto")
    events, asked = h.run(s, runner)
    assert _res(s, 1).state == ResultState.VERIFICADO and _res(s, 2).state == ResultState.VERIFICADO
    assert _res(s, 1).file == "01 - Fjaak - Spirit.flac"
    assert _res(s, 2).file == "02 - Chris Liebing - Higher Things (FJAAK Remix).flac"
    assert _res(s, 1).peer == "peerA" and _res(s, 1).score == 100 and asked == []
    assert [e.kind for e in events][-1] == "finished"
    s.finalize(h.library)
    assert _files(s.set_dir) == ["01 - Fjaak - Spirit.flac", "02 - Chris Liebing - Higher Things (FJAAK Remix).flac",
                                 "Informe - Set correcto.txt", "Tracklist - Set correcto.txt"]
    rep = (s.set_dir / "Informe - Set correcto.txt").read_text(encoding="utf-8")
    assert "01. Fjaak - Spirit  [Verificado, confianza 100/100]" in rep and "verificado 2" in rep
    assert (s.set_dir / "Tracklist - Set correcto.txt").read_text(encoding="utf-8").startswith("01. Fjaak - Spirit")
    assert len(h.library.entries) == 2
    doc = SetDoc.from_dict(read_json(set_doc_path(s.set_dir)))
    assert doc.passes[0].name == "lossless" and doc.passes[0].engine == "fake:sockseek-3.0.5"
    pj = read_json(Path(doc.passes[0].work_dir) / "pass.json")
    assert pj["schema"] == "tracklister.pass/1" and [i["snum"] for i in pj["items"]] == [1, 2]
    assert "clave-prueba" not in json.dumps(pj) and "usuario-prueba" not in json.dumps(pj)
    assert not (Path(doc.passes[0].work_dir) / "in").exists()       # leftovers removed


def test_version_equivocada_goes_to_dudosos(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("version_equivocada")
    h.run(s, runner)
    r = _res(s, 1)
    assert r.state == ResultState.DUDOSO and r.doubt == DoubtKind.VERSION
    assert r.file == "_dudosos/01 - Fjaak - Spirit.flac" and (s.set_dir / r.file).exists()
    assert any("Otra versión" in x for x in r.reasons)


def test_radio_edit_too_short(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("radio_edit")
    h.run(s, runner)
    r = _res(s, 1)
    assert r.state == ResultState.DUDOSO and r.doubt == DoubtKind.VERSION and r.file.startswith("_dudosos/")
    assert any("Duración" in x for x in r.reasons)


def test_flac_transcodificado_stays_marked(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("flac_transcodificado")
    h.run(s, runner)
    r = _res(s, 1)
    assert r.state == ResultState.DUDOSO and r.doubt == DoubtKind.ESPECTRO
    assert r.file == "01 - DJ Dextro - Covil dos Abutres.flac" and "posible_falso_lossless" in r.flags
    assert "posible lossless falso" in s.report_text()


def test_truncado_and_sin_tags(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("truncado")
    h.run(s, runner)
    r = _res(s, 1)
    assert r.state == ResultState.DUDOSO and r.doubt == DoubtKind.DURACION and "truncado" in r.flags
    assert r.file.startswith("_dudosos/")
    s2, runner2 = h.session("sin_tags")
    h.run(s2, runner2)
    r2 = _res(s2, 1)
    assert r2.state == ResultState.VERIFICADO and "sin_tags" in r2.flags
    assert r2.file == "01 - Sigur R\u00f3s - Gla\u00f0ur.flac"


def test_sin_resultados_asks_lossy_once_and_peer_timeout(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("sin_resultados")
    events, asked = h.run(s, runner, approve=lambda rows: {r.uid for r in rows})
    r = _res(s, 1)
    assert r.state == ResultState.NO_ENCONTRADO and "formatos: mp3" in r.reasons[0]
    assert len(asked) == 1 and s.doc.lossy_approved == asked[0]
    assert [p.name for p in s.doc.passes] == ["lossless", "mp3_320"]
    s2, runner2 = h.session("peer_timeout")
    h.run(s2, runner2)
    assert _res(s2, 1).state == ResultState.FALLIDA and "ninguna descarga terminó" in _res(s2, 1).reasons[0]
    assert [p.name for p in s2.doc.passes] == ["lossless"]          # MP3 not approved -> no lossy pass


def test_retry_failed_uses_relaxed_pass(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("sin_resultados")
    h.run(s, runner)
    assert _res(s, 1).state == ResultState.NO_ENCONTRADO
    _, net = build_scenario("correcto", tmp_path / "n2")
    data = json.loads(net.read_text(encoding="utf-8"))
    data["files"].append({"peer": "peerZ", "path": "@@x\\Nadie\\Nadie Conocido - Tema Inexistente.flac",
                          "artist": "Nadie Conocido", "title": "Tema Inexistente", "duration_s": 30, "format": "flac",
                          "samplerate": 44100, "bitdepth": 16, "bitrate_kbps": None, "vbr": False, "audio": {}})
    net.write_text(json.dumps(data), encoding="utf-8")
    runner.env["TRACKLISTER_FAKE_NETWORK"] = str(net)
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    assert _res(s, 1).state == ResultState.VERIFICADO
    last = s.doc.passes[-1]
    assert last.name == "lossless-relajada"
    argv = read_json(Path(last.work_dir) / "pass.json")["argv_redacted"]
    assert "--strict-title" in argv and "--strict-artist" not in argv


def test_duplicado_entre_sets_reuse(tmp_path):
    h = Harness(tmp_path)
    a, ra = h.session("correcto", name="Set A")
    h.run(a, ra)
    a.finalize(h.library)
    b, rb = h.session("duplicado_entre_sets", name="Set B")
    hits = b.find_duplicates(h.library)
    assert [x.row.pos for x in hits] == [1] and hits[0].entries[0].set_name == "Set A"
    b.apply_duplicate_choice(hits[0].row.uid, DuplicateChoice.REUSE, hits[0].entries[0])
    assert _res(b, 1).state == ResultState.YA_EN_BIBLIOTECA and _res(b, 1).file == "01 - Fjaak - Spirit.flac"
    assert (b.set_dir / "01 - Fjaak - Spirit.flac").read_bytes() == (a.set_dir / "01 - Fjaak - Spirit.flac").read_bytes()
    h.run(b, rb)
    assert _res(b, 1).state == ResultState.YA_EN_BIBLIOTECA and _res(b, 2).state == ResultState.VERIFICADO
    assert len(b.doc.passes) == 1 and b.doc.passes[0].uids == [next(r.uid for r in b.doc.rows if r.pos == 2)]
    assert b.doc.duplicate_choices[hits[0].row.uid] == "reuse"


def test_rerun_is_idempotent(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("rerun", name="Mismo set")
    h.run(s, runner)
    s.finalize(h.library)
    before = {f: (s.set_dir / f).read_bytes() for f in _files(s.set_dir) if f.endswith(".flac")}
    s2, runner2 = h.session("rerun", name="Mismo set")       # same tracklist imported again (new uids)
    assert s2.set_dir == s.set_dir and len(s2.doc.passes) == 1
    h.run(s2, runner2)
    s2.finalize(h.library)
    assert len(s2.doc.passes) == 1                           # nothing downloaded again
    assert {f: (s2.set_dir / f).read_bytes() for f in _files(s2.set_dir) if f.endswith(".flac")} == before
    assert all(r.state == ResultState.VERIFICADO for r in s2.doc.results.values())


def test_nombres_raros(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("nombres_raros")
    h.run(s, runner)
    assert _res(s, 1).file == "01 - AC DC - What Live Raw.flac"
    assert _res(s, 2).file == "02 - \u00d1u Sound - Canci\u00f3n del Ni\u00f1o.flac"
    assert _res(s, 3).file == "03 - CON - AUX.flac"
    assert len(_res(s, 4).file) <= 180 and _res(s, 4).file.startswith("04 - Larga - Una Cancion")
    assert all(_res(s, i).state == ResultState.VERIFICADO for i in (1, 2, 3, 4))


def test_login_failure_marks_rows_and_stops(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("login_falla")
    events, asked = h.run(s, runner, approve=lambda rows: {r.uid for r in rows})
    assert all(_res(s, i).state == ResultState.FALLIDA for i in (1, 2))
    assert "usuario y tu contraseña" in _res(s, 1).reasons[0]
    assert any(e.kind == "error" and "Ajustes" in e.message_es for e in events)
    assert len(s.doc.passes) == 1 and asked == []


def test_ban_stops_the_run(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("ban")
    events, asked = h.run(s, runner, approve=lambda rows: {r.uid for r in rows})
    assert _res(s, 1).state == ResultState.VERIFICADO
    assert _res(s, 2).state == ResultState.FALLIDA and _res(s, 3).state == ResultState.FALLIDA
    assert any(e.kind == "error" and "Soulseek cortó la sesión" in e.message_es for e in events)
    assert asked == [] and len(s.doc.passes) == 1


def test_mp3_vbr_and_256_do_not_meet_format(tmp_path):
    h = Harness(tmp_path)
    for scen, flag in (("mp3_vbr", "mp3_vbr"), ("mp3_vbr_sin_cabecera", "mp3_vbr"), ("mp3_256", "mp3_bajo_bitrate")):
        s, runner = h.session(scen)
        h.run(s, runner)
        r = _res(s, 1)
        assert r.state == ResultState.NO_CUMPLE_FORMATO and flag in r.flags and r.file is None
        assert not list(s.set_dir.glob("*.mp3"))


def test_cdj_flac_96k_converted_original_kept(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("cdj_flac_96k")
    h.run(s, runner)
    r = _res(s, 1)
    assert r.state == ResultState.VERIFICADO and r.file == "01 - Fjaak - Spirit.aiff"
    assert r.original_file == "_originales/01 - Fjaak - Spirit.flac" and (s.set_dir / r.original_file).exists()
    assert "convertido_aiff" in r.flags and "reducido_48k_24b" in r.flags
    info = sf.info(str(s.set_dir / r.file))
    assert info.samplerate == 48000 and info.subtype == "PCM_24" and (r.samplerate, r.bitdepth) == (48000, 24)
    assert (s.set_dir / r.file).read_bytes()[8:12] == b"AIFF"
    tags = mutagen.File(str(s.set_dir / r.file)).tags
    assert str(tags["TPE1"]) == "Fjaak" and tags.getall("APIC")
    assert [p.name for p in s.doc.passes] == ["aiff_wav", "flac_a_aiff"]


def test_todos_los_estados(tmp_path):
    h = Harness(tmp_path)
    a, ra = h.session("correcto", name="Anterior")
    h.run(a, ra)
    a.finalize(h.library)
    s, runner = h.session("todos_los_estados", name="Todos")
    hits = {x.row.pos: x for x in s.find_duplicates(h.library)}
    assert set(hits) == {1, 6}
    s.apply_duplicate_choice(hits[1].row.uid, DuplicateChoice.DOWNLOAD, None)
    s.apply_duplicate_choice(hits[6].row.uid, DuplicateChoice.REUSE, hits[6].entries[0])
    h.run(s, runner)
    got = {pos: _res(s, pos).state for pos in range(1, 8)}
    assert got == {1: ResultState.VERIFICADO, 2: ResultState.DUDOSO, 3: ResultState.NO_ENCONTRADO,
                   4: ResultState.NO_CUMPLE_FORMATO, 5: ResultState.FALLIDA, 6: ResultState.YA_EN_BIBLIOTECA,
                   7: ResultState.OMITIDA}
    assert "extension_distinta" in _res(s, 4).flags
    rep = s.report_text()
    for word in ("Verificado", "Dudoso", "No encontrado", "No cumple formato", "Fallida", "Ya en biblioteca", "Omitida"):
        assert word in rep


def test_cancel_then_resume(tmp_path):
    h = Harness(tmp_path)

    def slow(net):
        net["peers"] = {"peerB": {"slow": True, "slow_s": 60}}
    s, runner = h.session("correcto", net_patch=slow)
    cancel = threading.Event()
    threading.Timer(4.0, cancel.set).start()
    s.run(runner, CREDS, lambda e: None, cancel, lambda rows: set())
    assert _res(s, 2).state == ResultState.PENDIENTE
    assert {r.state for r in s.doc.results.values()} <= {ResultState.PENDIENTE, ResultState.VERIFICADO}
    runner.env["TRACKLISTER_FAKE_NETWORK"] = str(build_scenario("correcto", tmp_path / "fast")[1])
    s.run(runner, CREDS, lambda e: None, threading.Event(), lambda rows: set())
    assert _res(s, 1).state == ResultState.VERIFICADO and _res(s, 2).state == ResultState.VERIFICADO


# ---- external audit, round 1 (veredicto-r2.json) --------------------------------------------------

def _no_row_left_running_and_journal_closed(s: SetSession) -> None:
    doc = SetDoc.from_dict(read_json(set_doc_path(s.set_dir)))
    assert ResultState.EN_CURSO not in {r.state for r in doc.results.values()}
    assert all(b["committed"] for b in Journal(s.set_dir).batches())
    assert not list(s.set_dir.rglob("*.part"))


def test_b1_cdj_truncated_flac_goes_to_dudosos_as_it_is_and_the_run_goes_on(tmp_path):
    """B1: under CDJ antiguos a truncated FLAC used to be converted and crash the whole run. Now it goes
    unconverted to _dudosos; the other file of that pass is converted and placed; the MP3 pass runs."""
    h = Harness(tmp_path)
    s, runner = h.session_with(
        "truncado", "CDJ truncado", "cdj_antiguos",
        extra_rows=[row(2, "Fjaak", "Spirit", dur=30), row(3, "Kobosil", "Aggression", dur=28)],
        extra_files=[file("peerB", "@@y\\Fjaak\\Fjaak - Spirit.flac", "Fjaak", "Spirit", 30),
                     file("peerC", "@@z\\Kobosil\\Kobosil - Aggression.mp3", "Kobosil", "Aggression", 28,
                          fmt="mp3")])
    events, asked = h.run(s, runner, approve=lambda rows: {r.uid for r in rows})
    r1, r2, r3 = _res(s, 1), _res(s, 2), _res(s, 3)
    assert r1.state == ResultState.DUDOSO and r1.doubt == DoubtKind.DURACION
    assert "truncado" in r1.flags and "sin_convertir" in r1.flags and "convertido_aiff" not in r1.flags
    assert r1.file == "_dudosos/01 - Roll Dann - Mercy.flac" and r1.original_file is None
    assert (s.set_dir / r1.file).read_bytes()[:4] == b"fLaC"                   # the original FLAC, untouched
    assert sorted(p.name for p in (s.set_dir / "_dudosos").iterdir()) == ["01 - Roll Dann - Mercy.flac"]
    assert r2.state == ResultState.VERIFICADO and r2.file == "02 - Fjaak - Spirit.aiff"
    assert sorted(p.name for p in (s.set_dir / "_originales").iterdir()) == ["02 - Fjaak - Spirit.flac"]
    assert r3.state == ResultState.VERIFICADO and r3.file == "03 - Kobosil - Aggression.mp3"
    assert [p.name for p in s.doc.passes] == ["aiff_wav", "flac_a_aiff", "mp3_320"]   # later passes ran
    assert asked and set(asked[0]) == {r1.uid, r3.uid}
    assert events[-1].kind == "finished" and not any(e.kind == "error" for e in events)
    _no_row_left_running_and_journal_closed(s)


def test_b1_cdj_flac_that_cannot_be_converted_does_not_meet_format(tmp_path):
    """A FLAC damaged near the end decodes (no 'truncado' doubt) but libsndfile cannot convert it."""
    def damaged(net):
        net["files"][0]["audio"]["truncate_to_s"] = 29.5
    h = Harness(tmp_path)
    s, runner = h.session("truncado", name="CDJ dañado", preset="cdj_antiguos", net_patch=damaged)
    events, _ = h.run(s, runner)
    r = _res(s, 1)
    assert r.state == ResultState.NO_CUMPLE_FORMATO and "conversion_fallida" in r.flags and r.file is None
    assert r.reasons[0].startswith("No se pudo convertir a AIFF para CDJ antiguos (LibsndfileError)")
    assert not [p for p in s.set_dir.rglob("*") if p.is_file() and ".tracklister" not in p.parts]
    assert events[-1].kind == "finished" and not any(e.kind == "error" for e in events)
    _no_row_left_running_and_journal_closed(s)


def test_b1_a_file_that_cannot_be_placed_fails_only_its_row(tmp_path, monkeypatch):
    import tracklister.pipeline.session as session_mod
    real = session_mod.place_verified

    def flaky(set_dir, row_, src, verdict, width, journal, bid):
        if row_.pos == 1:
            raise PermissionError(13, "Acceso denegado")
        return real(set_dir, row_, src, verdict, width, journal, bid)
    monkeypatch.setattr(session_mod, "place_verified", flaky)
    h = Harness(tmp_path)
    s, runner = h.session("correcto")
    events, _ = h.run(s, runner)
    r1, r2 = _res(s, 1), _res(s, 2)
    assert r1.state == ResultState.FALLIDA and r1.file is None
    assert r1.reasons == ["No se pudo mover o guardar el archivo descargado (Acceso denegado). Pulsa «Reintentar "
                          "fallos» para volver a intentarlo."]
    assert r2.state == ResultState.VERIFICADO and (s.set_dir / r2.file).is_file()
    assert events[-1].kind == "finished"
    _no_row_left_running_and_journal_closed(s)


def test_b1_an_unexpected_error_never_leaves_rows_en_curso(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("correcto")

    def boom(ev):
        if ev.kind == "row_state" and ev.done:        # right after the first file was placed
            raise RuntimeError("fallo de la interfaz")
    with pytest.raises(RuntimeError):
        s.run(runner, CREDS, boom, threading.Event(), lambda rows: set())
    _no_row_left_running_and_journal_closed(s)
    assert _res(s, 1).state == ResultState.VERIFICADO and _res(s, 2).state == ResultState.PENDIENTE


def test_n1_retry_bans_the_peer_of_the_rejected_file(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("version_equivocada")
    h.run(s, runner)
    r = _res(s, 1)
    assert r.state == ResultState.DUDOSO and r.doubt == DoubtKind.VERSION
    assert r.peer == "peerA" and r.rejected_peers == ["peerA"]
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    last = s.doc.passes[-1]
    argv = read_json(Path(last.work_dir) / "pass.json")["argv_redacted"]
    assert argv[argv.index("--banned-users") + 1] == "peerA" and "--strict-artist" not in argv
    assert last.name == "lossless-relajada"
    r = _res(s, 1)
    assert r.state == ResultState.VERIFICADO and r.peer == "peerB" and r.file == "01 - Fjaak - Spirit.flac"
    assert (s.set_dir / "_dudosos" / "01 - Fjaak - Spirit.flac").is_file()      # the remix is kept, not deleted
    s.finalize(h.library)
    rep = (s.set_dir / "Informe - Set version_equivocada.txt").read_text(encoding="utf-8")
    assert STRAY_TITLE_ES in rep and "    _dudosos/01 - Fjaak - Spirit.flac" in rep


@pytest.mark.parametrize("peer", [None, "peer,con coma"])
def test_n1_retry_skips_a_rejected_file_whose_peer_cannot_be_banned(tmp_path, peer):
    h = Harness(tmp_path)
    s, runner = h.session("version_equivocada")
    h.run(s, runner)
    r = _res(s, 1)
    r.peer, r.rejected_peers = peer, []
    s.save()
    before = len(s.doc.passes)
    events = []
    for _ in range(2):
        s.retry_failed(runner, CREDS, events.append, threading.Event())
    r = _res(s, 1)
    assert len(s.doc.passes) == before                      # not sent again: the same file would come back
    assert r.state == ResultState.DUDOSO and r.doubt == DoubtKind.VERSION and r.file.startswith("_dudosos/")
    assert r.reasons.count(NOT_RETRIED_ES) == 1 and "_dudosos" in NOT_RETRIED_ES and "a mano" not in NOT_RETRIED_ES
    assert events[-1].kind == "finished"


def test_n1_retry_says_when_the_same_file_comes_back(tmp_path):
    def twin(net):
        net["files"][1] = dict(net["files"][0], peer="peerC")     # the same remix, shared by another user
    h = Harness(tmp_path)
    s, runner = h.session("version_equivocada", net_patch=twin)
    h.run(s, runner)
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    r = _res(s, 1)
    assert r.state == ResultState.DUDOSO and r.peer == "peerC" and r.rejected_peers == ["peerA", "peerC"]
    assert r.reasons[-1] == SAME_FILE_ES
    assert sorted(p.name for p in (s.set_dir / "_dudosos").iterdir()) == ["01 - Fjaak - Spirit.flac"]   # no "(2)"
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    argv = read_json(Path(s.doc.passes[-1].work_dir) / "pass.json")["argv_redacted"]
    assert argv[argv.index("--banned-users") + 1] == "peerA,peerC"
    assert _res(s, 1).reasons[-1].endswith("no apareció nada mejor.")


def test_n5_row_deleted_before_a_rerun_is_listed_and_kept(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("rerun", name="Set recortado")
    h.run(s, runner)
    s.finalize(h.library)
    rows, _ = build_scenario("rerun", tmp_path / "otra-vez")
    settings = Settings(preset_id="lossless", library_root=str(h.lib_root))
    s2 = SetSession.create("Set recortado", rows[:1], [], settings, h.lib_root, h.paths)   # row 2 deleted
    h.run(s2, runner)
    s2.finalize(h.library)
    rep = (s2.set_dir / "Informe - Set recortado.txt").read_text(encoding="utf-8")
    stray = rep.split(STRAY_TITLE_ES)[1].split("\n\n")[0]
    assert stray.strip().splitlines() == ["02 - Chris Liebing - Higher Things (FJAAK Remix).flac"]
    assert (s2.set_dir / "02 - Chris Liebing - Higher Things (FJAAK Remix).flac").is_file()   # never deleted
    assert len(s2.doc.passes) == 1


def test_n8_reused_file_keeps_its_fake_lossless_mark(tmp_path):
    h = Harness(tmp_path)
    a, ra = h.session("flac_transcodificado", name="Set A")
    h.run(a, ra)
    a.finalize(h.library)
    assert [e.flags for e in h.library.entries] == [["posible_falso_lossless"]]
    b, rb = h.session("flac_transcodificado", name="Set B")
    hits = b.find_duplicates(h.library)
    assert len(hits) == 1
    b.apply_duplicate_choice(hits[0].row.uid, DuplicateChoice.REUSE, hits[0].entries[0])
    r = _res(b, 1)
    assert r.state == ResultState.YA_EN_BIBLIOTECA and r.flags == ["reutilizado", "posible_falso_lossless"]
    assert any("Set A" in x and "posible lossless falso" in x for x in r.reasons)
    rep = b.report_text()
    assert "! Marca: posible lossless falso" in rep and "Marca que trae del set 'Set A'" in rep
    h.run(b, rb)
    b.finalize(h.library)
    from_b = [e for e in h.library.entries if e.set_name == "Set B"]
    assert len(from_b) == 1 and from_b[0].flags == ["posible_falso_lossless"]       # a set C keeps it too
