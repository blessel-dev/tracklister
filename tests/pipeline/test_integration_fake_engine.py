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
from tracklister.pipeline.session import NOT_RETRIED_ES, NOT_RETRIED_FORMAT_ES, SAME_FILE_ES, SetSession

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
    """1.0.1 (R6): a 16 kHz brick wall is «Verificado · revisar calidad», counted apart from «Dudoso», with
    its number in the set; the advice never says «escúchalo»."""
    h = Harness(tmp_path)
    s, runner = h.session("flac_transcodificado")
    h.run(s, runner)
    r = _res(s, 1)
    assert r.state == ResultState.REVISAR_CALIDAD and r.doubt is None and r.score == 100
    assert r.file == "01 - DJ Dextro - Covil dos Abutres.flac" and "probable_mp3_convertido" in r.flags
    assert r.spectral_cutoff_hz is not None and r.spectral_cutoff_hz < 16500
    rep = s.report_text()
    assert "[Verificado \u00b7 revisar calidad, confianza 100/100]" in rep
    assert "Resumen: verificado \u00b7 revisar calidad 1" in rep and "dudoso" not in rep.split("\n")[5]
    assert "! Marca: probable MP3 convertido" in rep and "scúchalo" not in rep


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


def test_a_reused_file_that_was_deleted_is_downloaded_again(tmp_path):
    """Barrido CL-07 (T.4 N1): a row reused from the library («Usar el que ya tengo») whose file was deleted went
    back to PENDIENTE with «se vuelve a buscar», but «Descargar» skipped it: the set still remembered the reuse
    choice. The choice is now forgotten when its file is gone (if a copy is left, the question comes back)."""
    h = Harness(tmp_path)
    a, ra = h.session("correcto", name="Set A")
    h.run(a, ra)
    a.finalize(h.library)
    b, rb = h.session("duplicado_entre_sets", name="Set B")
    hits = b.find_duplicates(h.library)
    uid = hits[0].row.uid
    b.apply_duplicate_choice(uid, DuplicateChoice.REUSE, hits[0].entries[0])
    h.run(b, rb)
    b.finalize(h.library)
    assert _res(b, 1).state == ResultState.YA_EN_BIBLIOTECA
    (b.set_dir / _res(b, 1).file).unlink()
    (a.set_dir / "01 - Fjaak - Spirit.flac").unlink()            # no copy left in the library either
    again = SetSession.load(b.set_dir, Settings(library_root=str(h.lib_root)), h.paths)
    assert _res(again, 1).state == ResultState.PENDIENTE
    _, net = build_scenario("duplicado_entre_sets", tmp_path / "net-again")
    runner = EngineRunner(fake_engine_spec(), SearchBudget(h.paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    h.run(again, runner)
    assert again.doc.passes and uid in again.doc.passes[-1].uids
    assert _res(again, 1).state == ResultState.VERIFICADO


@pytest.mark.parametrize("mode", ["retry", "continue"])
def test_a_reused_file_deleted_during_the_session_is_retried(tmp_path, mode):
    """Barrido audit AU-3-02: the same as above, but the file (and the library copy) is deleted with the set still
    open in Descarga. «Reintentar fallos» and «Continuar descarga» (SetSession.run) kept the row «Ya en
    biblioteca» with a file that was gone, and never searched it: only reopening the set noticed it. Every run
    now looks for the missing files first."""
    h = Harness(tmp_path)
    a, ra = h.session("correcto", name="Set A")
    h.run(a, ra)
    a.finalize(h.library)
    b, rb = h.session("duplicado_entre_sets", name="Set B")
    hits = b.find_duplicates(h.library)
    uid = hits[0].row.uid
    b.apply_duplicate_choice(uid, DuplicateChoice.REUSE, hits[0].entries[0])
    h.run(b, rb)
    b.finalize(h.library)
    assert _res(b, 1).state == ResultState.YA_EN_BIBLIOTECA
    (b.set_dir / _res(b, 1).file).unlink()                      # deleted with the set open: the same session
    (a.set_dir / "01 - Fjaak - Spirit.flac").unlink()           # no copy left in the library either
    _, net = build_scenario("duplicado_entre_sets", tmp_path / "net-again")
    runner = EngineRunner(fake_engine_spec(), SearchBudget(h.paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    passes = len(b.doc.passes)
    if mode == "retry":
        b.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    else:
        h.run(b, runner)
    assert [p for p in b.doc.passes[passes:] if uid in p.uids], [p.name for p in b.doc.passes[passes:]]
    assert _res(b, 1).state == ResultState.VERIFICADO and (b.set_dir / _res(b, 1).file).is_file()


def test_an_unreachable_set_folder_keeps_its_good_rows(tmp_path):
    """Tanda audit AT-1-01: since AU-3-02 a run first looks for the files deleted with the set open. When the set
    folder could not be reached as a run started (the USB stick or disk of the library pulled out, a network drive
    that does not answer), every good row became «Pendiente», and with the stick back the next «Continuar
    descarga» searched and downloaded the whole set again (a copy that is not the same byte for byte lands as
    «… (2)»). A folder that is not there says nothing about its files: the rows stay as they were."""
    h = Harness(tmp_path)
    s, runner = h.session("correcto")
    h.run(s, runner)
    s.finalize(h.library)
    good = {uid: (res.state, res.file) for uid, res in s.doc.results.items()}
    assert {state for state, _ in good.values()} == {ResultState.VERIFICADO}
    before, passes = _files(s.set_dir), len(s.doc.passes)
    away = h.lib_root.with_name("biblioteca-fuera")
    h.lib_root.rename(away)                         # the stick is pulled out: nothing can be read or created there
    h.lib_root.write_text("", encoding="utf-8")
    with pytest.raises(OSError):                    # «Reintentar fallos»: set.json cannot be saved there
        s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    assert {uid: (res.state, res.file) for uid, res in s.doc.results.items()} == good
    h.lib_root.unlink()
    away.rename(h.lib_root)                         # the stick is back, with the set still open in Descarga
    _, net = build_scenario("correcto", tmp_path / "net-again")
    h.run(s, EngineRunner(fake_engine_spec(), SearchBudget(h.paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)}))      # «Continuar descarga»
    assert not [p.name for p in s.doc.passes[passes:] if set(p.uids) & set(good)]
    assert {uid: (res.state, res.file) for uid, res in s.doc.results.items()} == good
    assert _files(s.set_dir) == before              # nothing new in the set folder


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
    assert r.rejected_peers == ["peerA"]                # round 2, B3: 'Reintentar fallos' bans that copy
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
    assert [e.flags for e in h.library.entries] == [["probable_mp3_convertido"]]     # 1.0.1 mark (R6)
    b, rb = h.session("flac_transcodificado", name="Set B")
    hits = b.find_duplicates(h.library)
    assert len(hits) == 1
    b.apply_duplicate_choice(hits[0].row.uid, DuplicateChoice.REUSE, hits[0].entries[0])
    r = _res(b, 1)
    assert r.state == ResultState.YA_EN_BIBLIOTECA and r.flags == ["reutilizado", "probable_mp3_convertido"]
    assert any("Set A" in x and "probable MP3 convertido" in x for x in r.reasons)
    rep = b.report_text()
    assert "! Marca: probable MP3 convertido" in rep and "Marca que trae del set 'Set A'" in rep
    assert "scúchalo" not in rep
    h.run(b, rb)
    b.finalize(h.library)
    from_b = [e for e in h.library.entries if e.set_name == "Set B"]
    assert len(from_b) == 1 and from_b[0].flags == ["probable_mp3_convertido"]      # a set C keeps it too


# ---- external audit, round 2 (claude-audit-raw-r2.txt) ---------------------------------------------

def _finalized(h: Harness, scenario: str, name: str, preset: str | None = None, net_patch=None) -> SetSession:
    s, runner = h.session(scenario, name=name, preset=preset, net_patch=net_patch)
    h.run(s, runner)
    s.finalize(h.library)
    return s


def test_a_damaged_library_is_rebuilt_not_replaced(tmp_path):
    """Barrido AG-03: an empty or half-written library.json (a power cut right after a save) loaded as an empty
    library, and the next finalize saved it with ONLY that set: the earlier sets stopped being offered as «Ya
    en biblioteca», with no warning. Now the damaged file is kept as library-danado.json and the index is rebuilt
    from the library folder before the set is added."""
    h = Harness(tmp_path)
    _finalized(h, "correcto", "Set A")
    h.paths.library_file.write_text("", encoding="utf-8")
    _finalized(h, "nombres_raros", "Set B")
    fresh = LibraryIndex(h.paths.library_file)
    fresh.load()
    assert {e.set_name for e in fresh.entries} == {"Set A", "Set B"}
    assert (h.paths.library_file.parent / "library-danado.json").is_file()
    c, _ = h.session("duplicado_entre_sets", name="Set C")
    hits = c.find_duplicates(fresh)
    assert [x.row.pos for x in hits] == [1] and hits[0].entries[0].set_name == "Set A"


def test_a_damaged_journal_never_blocks_the_set(tmp_path):
    """Barrido AG-06 (V.6 N13): an empty or cut journal.json made opening the set raise «JSON corrupto en
    journal.json…», so «Descargar», «Reintentar fallos» and «Abrir un set anterior…» failed although the music
    and set.json were fine. The damaged journal is set aside and a new one starts; the set runs as usual."""
    from tracklister.core.layout import journal_path
    h = Harness(tmp_path)
    a = _finalized(h, "correcto", "Set A")
    journal_path(a.set_dir).write_text("", encoding="utf-8")
    (a.set_dir / "01 - Fjaak - Spirit.flac").unlink()          # so the run has something to place again
    again = SetSession.load(a.set_dir, Settings(library_root=str(h.lib_root)), h.paths)
    assert (journal_path(a.set_dir).parent / "journal-danado.json").is_file()
    _, net = build_scenario("correcto", tmp_path / "net-again")
    runner = EngineRunner(fake_engine_spec(), SearchBudget(h.paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    h.run(again, runner)
    assert [_res(again, p).state for p in (1, 2)] == [ResultState.VERIFICADO] * 2
    assert (a.set_dir / "01 - Fjaak - Spirit.flac").is_file()
    assert [b["label_es"] for b in Journal(a.set_dir).batches()][-1].startswith("Pasada")


def _cbr_320(net):
    net["files"][0].update(vbr=False, real_kbps=320)


def test_r2_b1_library_files_are_offered_only_when_the_set_preset_accepts_them(tmp_path):
    h = Harness(tmp_path)
    _finalized(h, "correcto", "Set A")                                     # Lossless: FLACs in the library
    m, _ = h.session("duplicado_entre_sets", name="Set MP3", preset="solo_mp3_320")
    assert m.find_duplicates(h.library) == []                    # a FLAC never goes into a "Solo MP3 320" set
    mp3 = _finalized(h, "mp3_vbr", "Set MP3 anterior", net_patch=_cbr_320)   # Fjaak - Spirit as an MP3 CBR 320
    assert _res(mp3, 1).state == ResultState.VERIFICADO
    lossless, _ = h.session("duplicado_entre_sets", name="Set Lossless", preset="lossless")
    hits = lossless.find_duplicates(h.library)
    assert [(x.row.pos, [e.format for e in x.entries]) for x in hits] == [(1, ["flac"])]   # never the MP3...
    lossless.doc.lossy_approved.append(hits[0].row.uid)          # ...unless MP3 was approved for it in this set
    assert sorted(e.format for e in lossless.find_duplicates(h.library)[0].entries) == ["flac", "mp3"]
    m2, _ = h.session("duplicado_entre_sets", name="Set MP3 2", preset="solo_mp3_320")
    assert [[e.format for e in x.entries] for x in m2.find_duplicates(h.library)] == [["mp3"]]


def test_r2_b1_cdj_reuse_converts_the_library_flac_to_aiff(tmp_path):
    """B1: under "CDJ antiguos" a FLAC of the library becomes AIFF, exactly like a downloaded one: the
    copy of the original goes to _originales, the library file itself is never touched."""
    h = Harness(tmp_path)
    a = _finalized(h, "correcto", "Set A")
    lib_flac = a.set_dir / "01 - Fjaak - Spirit.flac"
    before = lib_flac.read_bytes()
    c, rc = h.session("duplicado_entre_sets", name="Set CDJ", preset="cdj_antiguos")
    hits = c.find_duplicates(h.library)
    assert [x.row.pos for x in hits] == [1]
    c.apply_duplicate_choice(hits[0].row.uid, DuplicateChoice.REUSE, hits[0].entries[0])
    r = _res(c, 1)
    assert r.state == ResultState.YA_EN_BIBLIOTECA and r.file == "01 - Fjaak - Spirit.aiff"
    assert r.original_file == "_originales/01 - Fjaak - Spirit.flac"
    assert (c.set_dir / r.original_file).read_bytes() == before and lib_flac.read_bytes() == before
    aiff = c.set_dir / r.file
    assert aiff.read_bytes()[8:12] == b"AIFF"                               # AIFF PCM, never AIFF-C
    info = sf.info(str(aiff))
    assert (info.samplerate, info.subtype) == (44100, "PCM_16")
    assert (r.format, r.samplerate, r.bitdepth) == ("aiff", 44100, 16)
    assert str(mutagen.File(str(aiff)).tags["TPE1"]) == "Fjaak"
    assert r.flags == ["reutilizado", "convertido_aiff"] and any("Convertido a AIFF" in x for x in r.reasons)
    assert not (h.paths.work_dir / c.doc.set_id[:8] / "reuse").exists()        # no leftovers
    h.run(c, rc)                                                    # the other track downloads as usual
    assert _res(c, 1).state == ResultState.YA_EN_BIBLIOTECA
    assert _res(c, 2).state == ResultState.VERIFICADO and _res(c, 2).file == "02 - Kobosil - Aggression.aiff"
    c.finalize(h.library)
    assert {e.pos: e.format for e in h.library.entries if e.set_name == "Set CDJ"} == {1: "aiff", 2: "aiff"}
    rep = (c.set_dir / "Informe - Set CDJ.txt").read_text(encoding="utf-8")
    assert "Original: _originales/01 - Fjaak - Spirit.flac" in rep and STRAY_TITLE_ES not in rep


def test_r2_b1_a_library_file_that_cannot_be_converted_is_downloaded_again(tmp_path):
    h = Harness(tmp_path)
    a = _finalized(h, "correcto", "Set A")
    lib_flac = a.set_dir / "01 - Fjaak - Spirit.flac"
    data = lib_flac.read_bytes()
    lib_flac.write_bytes(data[: int(len(data) * 29.5 / 30)])               # damaged near the end
    c, rc = h.session("duplicado_entre_sets", name="Set CDJ", preset="cdj_antiguos")
    hits = c.find_duplicates(h.library)
    c.apply_duplicate_choice(hits[0].row.uid, DuplicateChoice.REUSE, hits[0].entries[0])
    r = _res(c, 1)
    assert r.state == ResultState.PENDIENTE and c.doc.duplicate_choices[r.uid] == "download"
    assert r.reasons[0].startswith("No se pudo convertir a AIFF para CDJ antiguos el archivo de tu biblioteca")
    assert not (c.set_dir / "_originales").exists() and not list(c.set_dir.glob("*.aif*"))
    h.run(c, rc)
    assert _res(c, 1).state == ResultState.VERIFICADO and _res(c, 1).file == "01 - Fjaak - Spirit.aiff"


def test_r2_b3_retry_bans_the_peer_of_a_file_that_did_not_meet_the_format(tmp_path):
    """B3: an MP3 VBR (Solo MP3 320) is "no cumple formato". 'Reintentar fallos' bans its peer, so the
    CBR 320 of another user comes instead of the same VBR again."""
    def plus_cbr(net):
        net["files"].append(file("peerB", "@@y\\Fjaak\\Fjaak - Spirit.mp3", "Fjaak", "Spirit", 30, fmt="mp3",
                                 real_kbps=320))
    h = Harness(tmp_path)
    s, runner = h.session("mp3_vbr", net_patch=plus_cbr)
    h.run(s, runner)
    r = _res(s, 1)
    assert r.state == ResultState.NO_CUMPLE_FORMATO and "mp3_vbr" in r.flags
    assert r.peer == "peerA" and r.rejected_peers == ["peerA"]
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    argv = read_json(Path(s.doc.passes[-1].work_dir) / "pass.json")["argv_redacted"]
    assert argv[argv.index("--banned-users") + 1] == "peerA" and "--strict-artist" not in argv
    r = _res(s, 1)
    assert r.state == ResultState.VERIFICADO and r.peer == "peerB" and r.file == "01 - Fjaak - Spirit.mp3"


def test_r2_b3_the_ban_stays_when_nothing_better_appears(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("mp3_vbr")
    h.run(s, runner)
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    r = _res(s, 1)
    assert r.state == ResultState.NO_ENCONTRADO and r.rejected_peers == ["peerA"]
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())     # still banned: never the same VBR
    argv = read_json(Path(s.doc.passes[-1].work_dir) / "pass.json")["argv_redacted"]
    assert argv[argv.index("--banned-users") + 1] == "peerA"
    assert _res(s, 1).state == ResultState.NO_ENCONTRADO and not list(s.set_dir.glob("*.mp3"))


@pytest.mark.parametrize("peer", [None, "peer,con coma"])
def test_r2_b3_out_of_format_with_an_unknown_peer_is_not_retried_and_says_why(tmp_path, peer):
    h = Harness(tmp_path)
    s, runner = h.session("mp3_vbr")
    h.run(s, runner)
    r = _res(s, 1)
    r.peer, r.rejected_peers = peer, []
    s.save()
    before = len(s.doc.passes)
    events = []
    for _ in range(2):
        s.retry_failed(runner, CREDS, events.append, threading.Event())
    r = _res(s, 1)
    assert len(s.doc.passes) == before and r.state == ResultState.NO_CUMPLE_FORMATO
    assert r.reasons.count(NOT_RETRIED_FORMAT_ES) == 1 and NOT_RETRIED_ES not in r.reasons
    assert "_dudosos" not in NOT_RETRIED_FORMAT_ES and "no cumplía el formato" in NOT_RETRIED_FORMAT_ES
    assert [e.message_es for e in events if e.kind == "row_state"] == [NOT_RETRIED_FORMAT_ES]
    assert events[-1].kind == "finished"


# ---- external audit, round 3 (claude-audit-raw-r3-1.txt) ---------------------------------------------

def _network(h: Harness, name: str, files: list[dict]) -> Path:
    _, net = build_scenario("sin_resultados", h.tmp / f"net-{name}")
    data = json.loads(net.read_text(encoding="utf-8"))
    data["files"] = files
    net.write_text(json.dumps(data), encoding="utf-8")
    return net


def _set_with(h: Harness, name: str, rows, net: Path, preset: str = "lossless"):
    settings = Settings(preset_id=preset, library_root=str(h.lib_root))
    s = SetSession.create(name, rows, [SourceRef("tabla", f"{name}.csv")], settings, h.lib_root, h.paths)
    runner = EngineRunner(fake_engine_spec(), SearchBudget(h.paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    return s, runner


@pytest.mark.parametrize("want,got,folder", [("Adam Beyer", "Adam Port", "Beyer, Adam"),
                                             ("Chris Liebing", "Chris Lake", "Liebing, Chris"),
                                             ("Len Faki", "Ken Faki", "Faki, Len")])
def test_r3_b1_a_namesake_from_the_relaxed_retry_goes_to_dudosos(tmp_path, want, got, folder):
    """B1: 'Reintentar fallos' drops --strict-artist, so a file by another artist with a similar name
    and the same title can come (here from a 'Surname, Name' folder, which the strict pass refuses).
    It used to be VERIFICADO (82-96); now it is another artist: _dudosos, and the next retry bans it."""
    from tests.fakes.scenarios import file as fake_file, row as fake_row
    h = Harness(tmp_path)
    namesake = fake_file("peerA", f"@@x\\{folder}\\{got} - Rush.flac", got, "Rush", 30)
    s, runner = _set_with(h, f"Set {want}", [fake_row(1, want, "Rush", dur=30)], _network(h, want, [namesake]))
    h.run(s, runner)
    assert _res(s, 1).state == ResultState.NO_ENCONTRADO                 # --strict-artist refused it
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    argv = read_json(Path(s.doc.passes[-1].work_dir) / "pass.json")["argv_redacted"]
    assert "--strict-artist" not in argv and s.doc.passes[-1].name == "lossless-relajada"
    r = _res(s, 1)
    assert r.state == ResultState.DUDOSO and r.doubt == DoubtKind.IDENTIDAD, r.reasons
    assert r.file == f"_dudosos/01 - {want} - Rush.flac" and r.score < 50
    assert any(x.startswith(f"Otro artista: '{got}' no es '{want}'") for x in r.reasons)
    assert r.rejected_peers == ["peerA"] and not list(s.set_dir.glob("*.flac"))
    # the right file appears: the next retry bans the namesake's user and gets it
    right = fake_file("peerB", f"@@y\\{want}\\{want} - Rush.flac", want, "Rush", 30)
    runner.env["TRACKLISTER_FAKE_NETWORK"] = str(_network(h, f"{want}-2", [namesake, right]))
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    argv = read_json(Path(s.doc.passes[-1].work_dir) / "pass.json")["argv_redacted"]
    assert argv[argv.index("--banned-users") + 1] == "peerA"
    r = _res(s, 1)
    assert r.state == ResultState.VERIFICADO and r.peer == "peerB" and r.file == f"01 - {want} - Rush.flac"
    s.finalize(h.library)
    # the namesake (still in _dudosos) never enters the library
    assert [Path(e.path).name for e in h.library.entries] == [f"01 - {want} - Rush.flac"]


@pytest.mark.parametrize("want,got", [("Chris Liebing", "CHRIS LIEBING"), ("DJ Rush", "Dj Rush"),
                                      ("\u00d8 [Phase]", "O [Phase]"), ("Blasha & Allatt", "Allatt & Blasha"),
                                      ("Roll Dann", "Roll Dann & Laster Records"),
                                      ("H\u00e9ctor Oaks", "Hector Oaks")])
def test_r3_b1_genuine_artist_variants_pass_in_the_relaxed_retry(tmp_path, want, got):
    from tests.fakes.scenarios import file as fake_file, row as fake_row
    h = Harness(tmp_path)
    net = _network(h, "v", [fake_file("peerA", f"@@x\\Musica\\{got} - Motor.flac", got, "Motor", 30)])
    s, runner = _set_with(h, "Variantes", [fake_row(1, want, "Motor", dur=30)], net)
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())       # a relaxed pass straight away
    assert [p.name for p in s.doc.passes] == ["lossless-relajada"]
    r = _res(s, 1)
    assert r.state == ResultState.VERIFICADO and r.score == 100, r.reasons


@pytest.mark.parametrize("preset", ["lossless", "cdj_antiguos"])
def test_r3_n2_a_library_file_that_cannot_be_copied_is_downloaded_and_the_run_goes_on(tmp_path, monkeypatch,
                                                                                      preset):
    """N2: an OSError while copying a library file into the set (here a full disk halfway through the
    copy) used to stop the whole run. Now only that row is affected: nothing half-copied stays, and it
    is downloaded instead; the other repeated track is reused as usual."""
    import shutil as shutil_mod
    h = Harness(tmp_path)
    _finalized(h, "duplicado_entre_sets", "Set A")                        # both tracks in the library
    b, rb = h.session("duplicado_entre_sets", name="Set B", preset=preset)
    real_copy2 = shutil_mod.copy2

    def full_disk(src, dst, *a, **kw):
        if Path(dst).parent.name == "Set B" and "Fjaak" in Path(dst).name:
            with open(dst, "wb") as f:
                f.write(b"medio archivo")
            raise OSError(28, "No queda espacio en el disco")
        return real_copy2(src, dst, *a, **kw)
    monkeypatch.setattr(shutil_mod, "copy2", full_disk)
    hits = b.find_duplicates(h.library)
    assert [x.row.pos for x in hits] == [1, 2]
    for hit in hits:                                                     # what the GUI worker does
        b.apply_duplicate_choice(hit.row.uid, DuplicateChoice.REUSE, hit.entries[0])
    monkeypatch.setattr(shutil_mod, "copy2", real_copy2)
    r1, r2 = _res(b, 1), _res(b, 2)
    assert r1.state == ResultState.PENDIENTE and b.doc.duplicate_choices[r1.uid] == "download"
    assert r1.reasons == ["No se pudo copiar a este set el archivo de tu biblioteca (No queda espacio en el "
                          "disco): se descarga de nuevo."]
    assert r2.state == ResultState.YA_EN_BIBLIOTECA and b.doc.duplicate_choices[r2.uid] == "reuse"
    ext = ".aiff" if preset == "cdj_antiguos" else ".flac"
    assert _files(b.set_dir) == sorted(["02 - Kobosil - Aggression" + ext] +
                                       (["_originales/02 - Kobosil - Aggression.flac"] if ext == ".aiff" else []))
    assert all(x["committed"] for x in Journal(b.set_dir).batches())
    events, _ = h.run(b, rb)
    assert events[-1].kind == "finished" and not any(e.kind == "error" for e in events)
    assert [p.uids for p in b.doc.passes if p.uids] and all(p.uids == [r1.uid] for p in b.doc.passes)
    assert _res(b, 1).state == ResultState.VERIFICADO and _res(b, 1).file == "01 - Fjaak - Spirit" + ext
    assert _res(b, 2).state == ResultState.YA_EN_BIBLIOTECA
    if ext == ".aiff":                                    # no stray "(2)": the half reuse was reverted
        assert sorted(p.name for p in (b.set_dir / "_originales").iterdir()) == [
            "01 - Fjaak - Spirit.flac", "02 - Kobosil - Aggression.flac"]
    _no_row_left_running_and_journal_closed(b)


def test_r2_n3_the_mp3_question_is_asked_once_per_set(tmp_path):
    h = Harness(tmp_path)
    s, runner = h.session("sin_resultados")
    _, asked = h.run(s, runner, approve=lambda rows: set())              # "No, dejarlas sin descargar"
    assert len(asked) == 1 and s.doc.lossy_asked == asked[0] and s.doc.lossy_approved == []
    _res(s, 1).state = ResultState.PENDIENTE          # e.g. cancelled: "Continuar descarga" runs it again
    s.save()
    _, asked = h.run(s, runner, approve=lambda rows: {r.uid for r in rows})
    assert asked == [] and [p.name for p in s.doc.passes] == ["lossless", "lossless"]   # it said no: no MP3
    s2, runner2 = h.session("sin_resultados", name="Otro set")
    _, asked = h.run(s2, runner2, approve=lambda rows: {r.uid for r in rows})          # yes
    assert len(asked) == 1
    _res(s2, 1).state = ResultState.PENDIENTE
    s2.save()
    _, asked = h.run(s2, runner2, approve=lambda rows: set())
    assert asked == [] and [p.name for p in s2.doc.passes] == ["lossless", "mp3_320", "lossless", "mp3_320"]


# ---- external audit, round 4 (claude-audit-raw-r4-1.txt) ---------------------------------------------

def test_r4_b5_the_library_drive_unplugged_before_placing_never_hangs_the_run(tmp_path, monkeypatch):
    """B5: the engine finished, and the USB or network disk of the library goes away before the files are
    placed. Journal.mkdir used to walk up from the set folder forever (the parent of 'Q:\\' is itself):
    the run hung and Cancelar could not stop it. Now each row of the pass fails with the reason, no row
    stays 'en curso', and the run ends."""
    import tracklister.organize.journal as journal_mod
    from tests.fakes.gone_drive import unplug_drive
    h = Harness(tmp_path)
    s, runner = h.session("correcto", name="Set USB")
    real_run = runner.run

    def run_then_unplug(*a, **kw):
        result = real_run(*a, **kw)
        unplug_drive(monkeypatch, journal_mod)            # the engine is done; then the disk goes away
        return result
    monkeypatch.setattr(runner, "run", run_then_unplug)
    events = []
    try:
        s.run(runner, CREDS, events.append, threading.Event(), lambda rows: set())
    except OSError:
        pass                                              # also acceptable: the run ends with the error
    states = [r.state for r in s.doc.results.values()]
    assert ResultState.EN_CURSO not in states and set(states) <= {ResultState.FALLIDA, ResultState.PENDIENTE}
    failed = [r for r in s.doc.results.values() if r.state == ResultState.FALLIDA]
    assert failed and all(journal_mod.DRIVE_GONE_ES in r.reasons[0] and r.file is None for r in failed)
    assert not any(r.state == ResultState.VERIFICADO for r in s.doc.results.values())


@pytest.mark.parametrize("preset", ["lossless", "cdj_antiguos"])
def test_r4_b6_a_ulaw_wav_does_not_meet_format_and_the_retry_bans_its_peer(tmp_path, preset):
    """B6: a WAV holding u-law (8-bit lossy) was VERIFICADO in Lossless and placed unconverted in CDJ
    antiguos. Now it is "no cumple formato", nothing is placed, and 'Reintentar fallos' bans its user."""
    from tests.fakes.scenarios import file as fake_file, row as fake_row
    h = Harness(tmp_path)
    ulaw = fake_file("peerA", "@@x\\Fjaak\\Fjaak - Spirit.wav", "Fjaak", "Spirit", 30, fmt="wav",
                     audio={"subtype": "ULAW"})
    s, runner = _set_with(h, f"Set ulaw {preset}", [fake_row(1, "Fjaak", "Spirit", dur=30)],
                          _network(h, f"ulaw-{preset}", [ulaw]), preset=preset)
    h.run(s, runner)
    r = _res(s, 1)
    if preset == "lossless":
        assert r.state == ResultState.NO_CUMPLE_FORMATO and "codec_con_perdida" in r.flags
        assert r.reasons[-1] == "WAV con un códec con pérdida (ULAW): no es lossless."
    else:          # CDJ antiguos: its next pass (FLAC to AIFF) finds nothing else
        assert r.state in (ResultState.NO_CUMPLE_FORMATO, ResultState.NO_ENCONTRADO)
    assert r.file is None and r.rejected_peers == ["peerA"] and not _files(s.set_dir)
    pcm = fake_file("peerB", "@@y\\Fjaak\\Fjaak - Spirit.wav", "Fjaak", "Spirit", 30, fmt="wav")
    runner.env["TRACKLISTER_FAKE_NETWORK"] = str(_network(h, f"ulaw-{preset}-2", [ulaw, pcm]))
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    argv = read_json(Path(s.doc.passes[-1].work_dir) / "pass.json")["argv_redacted"]
    assert argv[argv.index("--banned-users") + 1] == "peerA"
    r = _res(s, 1)
    assert r.state == ResultState.VERIFICADO and r.peer == "peerB" and r.file == "01 - Fjaak - Spirit.wav"


def test_r4_b4_a_file_open_in_another_program_never_hides_files_nor_downloads_them_again(tmp_path, monkeypatch):
    """B4: a row inserted at the top renumbers the set; one of its files is open in Ableton, so renaming it
    fails. sync_names used to leave the files it had already moved under __tracklister_tmp_* names and fail
    before saving: on reopening the set, those rows went back to PENDIENTE and were downloaded again. Now
    the folder keeps its names, the run ends with the Spanish message, and once the file is closed the next
    Descargar renames everything without asking the engine for those rows."""
    import shutil as shutil_mod
    from tests.fakes.scenarios import file as fake_file, row as fake_row
    from tracklister.organize.finalize import RenameError
    h = Harness(tmp_path)
    first = _finalized(h, "correcto", "Set B4")
    set_dir = first.set_dir
    kobosil = fake_file("peerC", "@@x\\Kobosil\\Kobosil - Aggression.flac", "Kobosil", "Aggression", 28)
    _, base = build_scenario("correcto", tmp_path / "base")
    net = _network(h, "b4", json.loads(base.read_text(encoding="utf-8"))["files"] + [kobosil])

    def table():          # the user inserted Kobosil above the two downloaded tracks
        return [fake_row(1, "Kobosil", "Aggression", dur=28), fake_row(2, "Fjaak", "Spirit", dur=30),
                fake_row(3, "Chris Liebing", "Higher Things", "FJAAK Remix", dur=32)]
    locked = "02 - Chris Liebing - Higher Things (FJAAK Remix).flac"
    real_move = shutil_mod.move

    def open_in_ableton(src, dst, *a, **kw):
        if Path(src).name == locked:
            raise PermissionError(13, "El proceso no tiene acceso al archivo porque está siendo utilizado por otro "
                                      "proceso", src)
        return real_move(src, dst, *a, **kw)
    monkeypatch.setattr(shutil_mod, "move", open_in_ableton)
    s, runner = _set_with(h, "Set B4", table(), net)
    h.run(s, runner)
    assert [p.uids for p in s.doc.passes][1:] == [[_res(s, 1).uid]]          # only the new row was downloaded
    with pytest.raises(OSError) as e:
        s.finalize(h.library)
    assert isinstance(e.value, RenameError) and f"'{locked}': está abierto en otro programa" in e.value.msg_es
    assert not list(set_dir.glob("__tracklister_tmp_*"))
    assert sorted(f for f in _files(set_dir) if f.endswith(".flac")) == [
        "01 - Fjaak - Spirit.flac", "01 - Kobosil - Aggression.flac", locked]
    again = SetSession.load(set_dir, Settings(preset_id="lossless", library_root=str(h.lib_root)), h.paths)
    assert all(r.state == ResultState.VERIFICADO and (set_dir / r.file).is_file() for r in again.doc.results.values())
    assert again.pending_rows() == []                       # nothing is downloaded again
    monkeypatch.setattr(shutil_mod, "move", real_move)      # the file is closed
    s2, runner2 = _set_with(h, "Set B4", table(), net)
    h.run(s2, runner2)
    s2.finalize(h.library)
    assert len(s2.doc.passes) == 2                          # no new pass: nothing asked to the engine
    assert sorted(f for f in _files(set_dir) if f.endswith(".flac")) == [
        "01 - Kobosil - Aggression.flac", "02 - Fjaak - Spirit.flac",
        "03 - Chris Liebing - Higher Things (FJAAK Remix).flac"]
    assert [_res(s2, i).file for i in (1, 2, 3)] == ["01 - Kobosil - Aggression.flac", "02 - Fjaak - Spirit.flac",
                                                     "03 - Chris Liebing - Higher Things (FJAAK Remix).flac"]
    _no_row_left_running_and_journal_closed(s2)


@pytest.mark.parametrize("got", ["Spirit (Kai Remix) (Extended Mix)", "Spirit (Live at Awakenings)"])
def test_r4_b3_a_remix_or_a_live_behind_another_group_goes_to_dudosos(tmp_path, got):
    """B3: --strict-title 'Spirit' lets these through. An original row without an expected duration used to
    take them as VERIFICADO (95). Now they go to _dudosos as another version; a row that asks for the Kai
    Remix still takes its extended mix."""
    from tests.fakes.scenarios import file as fake_file, row as fake_row
    h = Harness(tmp_path)
    net = _network(h, "b3", [fake_file("peerA", f"@@x\\Fjaak\\Fjaak - {got}.flac", "Fjaak", got, 30)])
    s, runner = _set_with(h, "Set B3", [fake_row(1, "Fjaak", "Spirit")], net)
    h.run(s, runner)
    r = _res(s, 1)
    assert r.state == ResultState.DUDOSO and r.doubt == DoubtKind.VERSION and r.score <= 49, r.reasons
    assert r.file == "_dudosos/01 - Fjaak - Spirit.flac" and r.rejected_peers == ["peerA"]
    if "Kai Remix" in got:
        s2, runner2 = _set_with(h, "Set B3 remix", [fake_row(1, "Fjaak", "Spirit", "Kai Remix")], net)
        h.run(s2, runner2)
        assert _res(s2, 1).state == ResultState.VERIFICADO
        assert _res(s2, 1).file == "01 - Fjaak - Spirit (Kai Remix).flac"


def test_r4_b2_a_title_with_a_word_more_goes_to_dudosos_and_the_retry_bans_its_peer(tmp_path):
    """B2: --strict-title 'Feel It' lets 'Amelie Lens - Feel It All.flac' through (also in the relaxed retry);
    without an expected duration it was VERIFICADO 85. Now it is another track: _dudosos, «Otro título»,
    and 'Reintentar fallos' bans its user and gets the right file."""
    from tests.fakes.scenarios import file as fake_file, row as fake_row
    h = Harness(tmp_path)
    all_ = fake_file("peerA", "@@x\\Amelie Lens\\Amelie Lens - Feel It All.flac", "Amelie Lens", "Feel It All", 30)
    s, runner = _set_with(h, "Set B2", [fake_row(1, "Amelie Lens", "Feel It")], _network(h, "b2", [all_]))
    h.run(s, runner)
    r = _res(s, 1)
    assert r.state == ResultState.DUDOSO and r.doubt == DoubtKind.IDENTIDAD and r.score <= 49, r.reasons
    assert r.file == "_dudosos/01 - Amelie Lens - Feel It.flac" and r.rejected_peers == ["peerA"]
    assert any(x.startswith("Otro título: 'Feel It All'") for x in r.reasons)
    right = fake_file("peerB", "@@y\\Amelie Lens\\Amelie Lens - Feel It.flac", "Amelie Lens", "Feel It", 30)
    runner.env["TRACKLISTER_FAKE_NETWORK"] = str(_network(h, "b2-2", [all_, right]))
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    argv = read_json(Path(s.doc.passes[-1].work_dir) / "pass.json")["argv_redacted"]
    assert argv[argv.index("--banned-users") + 1] == "peerA"
    r = _res(s, 1)
    assert r.state == ResultState.VERIFICADO and r.peer == "peerB" and r.file == "01 - Amelie Lens - Feel It.flac"


def _table_copy(rows):
    """What Nuevo set hands to a new download (gui/pages/new_set.py _copy_rows): the same uids."""
    from tracklister.core.model import TrackRow
    return [TrackRow.from_dict(r.to_dict()) for r in rows]


def _tag_title(p: Path) -> str:
    return str(mutagen.File(str(p)).tags["title"][0])


@pytest.mark.parametrize("field,value,new_file", [
    ("title", "Some Chords", "01 - deadmau5 - Some Chords.flac"),
    ("version", "Kai Remix", "01 - deadmau5 - Strobe (Kai Remix).flac")])
def test_r4_b1_a_row_corrected_in_the_table_is_downloaded_and_never_takes_the_old_file(tmp_path, field, value,
                                                                                         new_file):
    """B1: after a download the user corrects a row in the Nuevo set table (trackid said 'Strobe', it was
    'Some Chords'; or it was the Kai Remix) and presses Descargar again with the same set name. The edited
    row kept its uid, so the old VERIFICADO result survived, nothing was downloaded, and finalize renamed
    the Strobe audio to the new title (and the library stored it under that key). Now the row gets a new
    uid, is downloaded as the corrected track, and the old file keeps its name, listed as a stray file."""
    from tests.fakes.scenarios import file as fake_file, row as fake_row
    h = Harness(tmp_path)
    net = _network(h, f"b1-{field}", [
        fake_file("peerA", "@@x\\deadmau5\\deadmau5 - Strobe.flac", "deadmau5", "Strobe", 30),
        fake_file("peerB", "@@y\\deadmau5\\deadmau5 - Some Chords.flac", "deadmau5", "Some Chords", 30),
        fake_file("peerC", "@@z\\deadmau5\\deadmau5 - Strobe (Kai Remix).flac", "deadmau5", "Strobe (Kai Remix)", 30),
        fake_file("peerD", "@@w\\Fjaak\\Fjaak - Spirit.flac", "Fjaak", "Spirit", 30)])
    s, runner = _set_with(h, "Set B1", [fake_row(1, "deadmau5", "Strobe", dur=30),
                                       fake_row(2, "Fjaak", "Spirit", dur=30)], net)
    h.run(s, runner)
    s.finalize(h.library)
    old_uid, keep_uid = _res(s, 1).uid, _res(s, 2).uid
    assert _res(s, 1).file == "01 - deadmau5 - Strobe.flac" and _res(s, 1).state == ResultState.VERIFICADO
    strobe = (s.set_dir / "01 - deadmau5 - Strobe.flac").read_bytes()
    table = _table_copy(s.doc.rows)
    setattr(table[0], field, value)
    s2, runner2 = _set_with(h, "Set B1", table, net)
    r1 = next(r for r in s2.doc.rows if r.pos == 1)
    assert r1.uid != old_uid and s2.doc.results[r1.uid].state == ResultState.PENDIENTE
    assert next(r for r in s2.doc.rows if r.pos == 2).uid == keep_uid           # the untouched row inherits
    assert [r.uid for r in s2.pending_rows()] == [r1.uid]
    h.run(s2, runner2)
    s2.finalize(h.library)
    assert s2.doc.passes[-1].uids == [r1.uid]
    res = _res(s2, 1)
    assert res.state == ResultState.VERIFICADO and res.file == new_file, res.reasons
    assert _tag_title(s2.set_dir / new_file) == ("Some Chords" if field == "title" else "Strobe (Kai Remix)")
    assert (s2.set_dir / new_file).read_bytes() != strobe
    assert (s2.set_dir / "01 - deadmau5 - Strobe.flac").read_bytes() == strobe          # never renamed
    rep = (s2.set_dir / "Informe - Set B1.txt").read_text(encoding="utf-8")
    assert STRAY_TITLE_ES in rep and "    01 - deadmau5 - Strobe.flac" in rep
    entries = {Path(e.path).name: e.key for e in h.library.entries if e.set_name == "Set B1"}
    assert "01 - deadmau5 - Strobe.flac" not in entries and new_file in entries
    assert _res(s2, 2).state == ResultState.VERIFICADO and _res(s2, 2).file == "02 - Fjaak - Spirit.flac"


def test_r4_b1_two_edited_rows_that_would_share_a_uid_never_collide(tmp_path):
    """B1 (3): row 1 'Spirit' becomes 'Spectrum' and row 2 'Raw' becomes 'Spirit'. Row 2 inherits Spirit's
    result (its file gets its number), row 1 is downloaded, and no two rows share a uid: sync_names used to
    plan two renames of one file (FileNotFoundError, a __tracklister_tmp_* left behind)."""
    from tests.fakes.scenarios import file as fake_file, row as fake_row
    h = Harness(tmp_path)
    net = _network(h, "b1-swap", [fake_file("peerA", "@@x\\Fjaak\\Fjaak - Spirit.flac", "Fjaak", "Spirit", 30),
                                  fake_file("peerA", "@@x\\Fjaak\\Fjaak - Raw.flac", "Fjaak", "Raw", 30),
                                  fake_file("peerB", "@@y\\Fjaak\\Fjaak - Spectrum.flac", "Fjaak", "Spectrum", 30)])
    s, runner = _set_with(h, "Set swap", [fake_row(1, "Fjaak", "Spirit", dur=30), fake_row(2, "Fjaak", "Raw", dur=30)],
                          net)
    h.run(s, runner)
    s.finalize(h.library)
    spirit_uid = _res(s, 1).uid
    spirit = (s.set_dir / "01 - Fjaak - Spirit.flac").read_bytes()
    table = _table_copy(s.doc.rows)
    table[0].title, table[1].title = "Spectrum", "Spirit"
    s2, runner2 = _set_with(h, "Set swap", table, net)
    uids = [r.uid for r in s2.doc.rows]
    assert len(set(uids)) == 2 and uids[1] == spirit_uid and set(s2.doc.results) == set(uids)
    assert s2.doc.results[uids[0]].state == ResultState.PENDIENTE
    h.run(s2, runner2)
    s2.finalize(h.library)
    assert _res(s2, 1).state == ResultState.VERIFICADO and _res(s2, 1).file == "01 - Fjaak - Spectrum.flac"
    assert _res(s2, 2).state == ResultState.VERIFICADO and _res(s2, 2).file == "02 - Fjaak - Spirit.flac"
    assert (s2.set_dir / "02 - Fjaak - Spirit.flac").read_bytes() == spirit
    assert sorted(f for f in _files(s2.set_dir) if f.endswith(".flac")) == [
        "01 - Fjaak - Spectrum.flac", "02 - Fjaak - Raw.flac", "02 - Fjaak - Spirit.flac"]   # Raw: stray, kept
    assert not list(s2.set_dir.glob("__tracklister_tmp_*"))
    _no_row_left_running_and_journal_closed(s2)


def test_r4_b1_only_rows_matched_by_artist_title_and_version_inherit():
    """_merge_rows: unchanged, reordered rows and rows that only change the label or the start time keep the
    old uid and result; an edited row and a repeated uid get new ones; every uid ends up unique."""
    from tests.fakes.scenarios import row as fake_row
    from tracklister.core.model import RowResult
    from tracklister.pipeline.session import _merge_rows
    old_rows = [fake_row(1, "Fjaak", "Spirit"), fake_row(2, "Kobosil", "Aggression"), fake_row(3, "Fjaak", "Raw"),
                fake_row(4, "Roll Dann", "Mercy")]
    doc = SetDoc(set_id="s", name="S", preset_id="lossless", rows=old_rows,
                 results={r.uid: RowResult(uid=r.uid, pos=r.pos, state=ResultState.VERIFICADO) for r in old_rows})
    table = _table_copy(old_rows)
    table = [table[1], table[0], table[2], table[3]]                       # rows 1 and 2 swapped
    for i, r in enumerate(table, start=1):
        r.pos = i
    table[0].label, table[1].ts_start = "Drumcode", 120                    # label and start: same track
    table[2].title = "Raw Power"                                           # edited: another track
    dup = _table_copy([table[3]])[0]                                       # a pasted copy with the same uid
    dup.pos, dup.title = 5, "Mercy Me"
    table.append(dup)
    _merge_rows(doc, table)
    by_pos = {r.pos: r.uid for r in doc.rows}
    assert by_pos[1] == old_rows[1].uid and by_pos[2] == old_rows[0].uid and by_pos[4] == old_rows[3].uid
    assert by_pos[3] not in {r.uid for r in old_rows} and by_pos[5] not in {r.uid for r in old_rows}
    assert len(set(by_pos.values())) == 5
    assert set(doc.results) == {old_rows[0].uid, old_rows[1].uid, old_rows[3].uid}


# ---- external audit, round 4, second review (veredicto-r4.json, iteration 2) ------------------------

def _pass_titles(s: SetSession) -> list[str]:
    return [i["title"] for i in read_json(Path(s.doc.passes[-1].work_dir) / "pass.json")["items"]]


@pytest.mark.parametrize("cells", ['Fjaak;"Spirit (Kai Remix) (Extended)"', 'Fjaak;"Spirit (Kai Remix) [Extended]"',
                                   'Fjaak;"Spirit (Kai Remix)";Extended Mix'])
def test_r4_v_b1_an_own_table_with_a_bare_extended_gets_the_remix_never_the_original(tmp_path, cells):
    """Second review of round 4, B1: an own CSV with Title 'Spirit (Kai Remix) (Extended)' (or '[Extended]',
    or a Mix column 'Extended Mix') was the ORIGINAL extended: «Usar el que ya tengo» offered a previous
    set's original extended, the engine was asked for 'Spirit (Extended)' and that file was VERIFICADO.
    Now the row is the Kai Remix: nothing is offered, the engine is asked for 'Spirit (Kai Remix)', and
    the Kai Remix's extended mix is verified."""
    from tests.fakes.scenarios import file as fake_file, row as fake_row
    from tracklister.inputs.importer import import_source
    h = Harness(tmp_path)
    original = fake_file("peerA", "@@x\\Fjaak\\Fjaak - Spirit (Extended).flac", "Fjaak", "Spirit (Extended)", 30)
    remix = fake_file("peerB", "@@y\\Fjaak\\Fjaak - Spirit (Kai Remix) (Extended Mix).flac", "Fjaak",
                      "Spirit (Kai Remix) (Extended Mix)", 30)
    net = _network(h, "v-b1", [original, remix])
    prev, runner0 = _set_with(h, "Set anterior", [fake_row(1, "Fjaak", "Spirit", "Extended")], net)
    h.run(prev, runner0)
    prev.finalize(h.library)
    assert _res(prev, 1).state == ResultState.VERIFICADO and _res(prev, 1).peer == "peerA"
    table = tmp_path / "tabla.csv"
    head = "Artista;Título;Mix" if cells.count(";") == 2 else "Artista;Título"
    table.write_text(f"{head}\n{cells}\n", encoding="utf-8")
    rows = import_source(table).rows
    assert [(r.title, r.version) for r in rows] == [("Spirit", "Kai Remix")]
    s, runner = _set_with(h, "Set B1 tabla", rows, net)
    assert s.find_duplicates(h.library) == []
    h.run(s, runner)
    assert _pass_titles(s) == ["Spirit (Kai Remix)"]
    r = _res(s, 1)
    assert r.state == ResultState.VERIFICADO and r.peer == "peerB", r.reasons
    assert r.file == "01 - Fjaak - Spirit (Kai Remix).flac" and "peerA" not in r.rejected_peers


def test_r4_v_b2_the_radio_edit_of_a_remix_never_takes_the_originals_radio_edit(tmp_path):
    """Second review of round 4, B2: the pasted line 'Fjaak - Spirit (Kai Remix) (Radio Edit)' was the
    plain radio edit: the engine was asked for 'Spirit (Radio Edit)', the ORIGINAL's radio edit came first
    and was VERIFICADO, and «Usar el que ya tengo» offered it from a previous set. Now the engine is asked
    for 'Spirit (Kai Remix)' (the original's radio edit never passes --strict-title), the full Kai Remix
    goes to _dudosos as another version, the next «Reintentar fallos» bans its user and gets the Kai
    Remix's radio edit, named with both groups."""
    from tests.fakes.scenarios import file as fake_file, row as fake_row
    from tracklister.inputs.importer import import_source
    h = Harness(tmp_path)
    radio = fake_file("peerA", "@@x\\Fjaak\\Fjaak - Spirit (Radio Edit).flac", "Fjaak", "Spirit (Radio Edit)", 30)
    full = fake_file("peerB", "@@y\\Fjaak\\Fjaak - Spirit (Kai Remix).flac", "Fjaak", "Spirit (Kai Remix)", 30)
    good = fake_file("peerC", "@@z\\Fjaak\\Fjaak - Spirit (Kai Remix) (Radio Edit).flac", "Fjaak",
                     "Spirit (Kai Remix) (Radio Edit)", 30)
    prev, runner0 = _set_with(h, "Set anterior", [fake_row(1, "Fjaak", "Spirit", "Radio Edit")],
                              _network(h, "v-b2-prev", [radio]))
    h.run(prev, runner0)
    prev.finalize(h.library)
    assert _res(prev, 1).state == ResultState.VERIFICADO and _res(prev, 1).peer == "peerA"
    rows = import_source("Fjaak - Spirit (Kai Remix) (Radio Edit)").rows
    assert [(r.title, r.version, r.notes) for r in rows] == [("Spirit", "Kai Remix - Radio Edit", [])]
    s, runner = _set_with(h, "Set B2", rows, _network(h, "v-b2", [radio, full, good]))
    assert s.find_duplicates(h.library) == []
    h.run(s, runner)
    assert _pass_titles(s) == ["Spirit (Kai Remix)"]
    r = _res(s, 1)
    assert r.state == ResultState.DUDOSO and r.doubt == DoubtKind.VERSION and r.score <= 49, r.reasons
    assert r.peer == "peerB" and r.file == "_dudosos/01 - Fjaak - Spirit (Kai Remix - Radio Edit).flac"
    assert any(x.startswith("Otra versión: se pedía 'Kai Remix - Radio Edit'") for x in r.reasons), r.reasons
    s.retry_failed(runner, CREDS, lambda e: None, threading.Event())
    argv = read_json(Path(s.doc.passes[-1].work_dir) / "pass.json")["argv_redacted"]
    assert argv[argv.index("--banned-users") + 1] == "peerB"
    r = _res(s, 1)
    assert r.state == ResultState.VERIFICADO and r.peer == "peerC", r.reasons
    assert r.file == "01 - Fjaak - Spirit (Kai Remix - Radio Edit).flac" and "peerA" not in r.rejected_peers
    s.finalize(h.library)
    assert _tag_title(s.set_dir / r.file) == "Spirit (Kai Remix) (Radio Edit)"       # peerC's file, not peerA's
    again = SetSession.load(s.set_dir, Settings(preset_id="lossless", library_root=str(h.lib_root)), h.paths)
    assert again.pending_rows() == []                         # a re-run keeps it: idempotent
