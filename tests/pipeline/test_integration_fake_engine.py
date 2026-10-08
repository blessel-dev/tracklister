"""End to end with the FAKE engine: every scenario of the brief's offline integration list."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import mutagen
import soundfile as sf

from tests.fakes.scenarios import SCENARIO_PRESET, build_scenario
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
from tracklister.pipeline.session import SetSession

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
    assert any("Otra version" in x for x in r.reasons)


def test_radio_edit_too_short(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("radio_edit")
    h.run(s, runner)
    r = _res(s, 1)
    assert r.state == ResultState.DUDOSO and r.doubt == DoubtKind.VERSION and r.file.startswith("_dudosos/")
    assert any("Duracion" in x for x in r.reasons)


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
    assert _res(s2, 1).state == ResultState.FALLIDA and "ninguna descarga termino" in _res(s2, 1).reasons[0]
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


def test_ban_stops_the_run(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("ban")
    events, asked = h.run(s, runner, approve=lambda rows: {r.uid for r in rows})
    assert _res(s, 1).state == ResultState.VERIFICADO
    assert _res(s, 2).state == ResultState.FALLIDA and _res(s, 3).state == ResultState.FALLIDA
    assert any(e.kind == "error" and "Soulseek corto la sesion" in e.message_es for e in events)
    assert asked == [] and len(s.doc.passes) == 1


def test_mp3_vbr_and_256_do_not_meet_format(tmp_path):
    h = Harness(tmp_path)
    for scen, flag in (("mp3_vbr", "mp3_vbr"), ("mp3_256", "mp3_bajo_bitrate")):
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
