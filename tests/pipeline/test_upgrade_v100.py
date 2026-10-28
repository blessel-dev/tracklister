"""1.0.1 R8 (+ R5 rename, decision B): a set, library.json and settings.json written by Tracklister 1.0.0.

SPDX-License-Identifier: GPL-3.0-or-later

The fixtures were written by the 1.0.0 code (tests/fixtures/v100/make_fixtures.py on commit 9191dd6): a set
of tracks of the user's public set with his symptoms of 10 Oct (a scene name and a watermark in _dudosos,
three spectral marks at 18.8, 20.2 and 16.2 kHz, a label as co-artist, an ID row, a radio edit in
_dudosos, a row not found). Fake engine only.
"""
from __future__ import annotations

import json
import os
import threading

import keyring
import pytest

from tests.fakes.scenarios import file
from tests.pipeline.v100 import LONG_PREFIX, SET_NAME, install_v100, local_path
from tracklister import config
from tracklister.core.jsonio import read_json
from tracklister.core.layout import journal_path, set_doc_path
from tracklister.core.model import (
    LIBRARY_SCHEMA, DoubtKind, ResultState, RowStatus, SetDoc, SourceRef, TrackRow, new_uid,
)
from tracklister.core.paths import app_paths
from tracklister.core.settings import load_settings, load_settings_checked, save_settings
from tracklister.engine.credentials import CredentialStore, Credentials
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.runner import EngineRunner
from tracklister.engine.spec import fake_engine_spec
from tracklister.library.index import LibraryIndex
from tracklister.organize.journal import Journal
from tracklister.pipeline.session import (
    UPGRADE_LABEL, UPGRADE_MARKER, UPGRADED_FROM_DUDOSOS_ES, UPGRADED_SPECTRUM_ES, SetSession,
)

CREDS = Credentials("usuario-prueba", "clave-prueba")


@pytest.fixture()
def v(tmp_path, monkeypatch):
    return install_v100(tmp_path / "casa", monkeypatch)


def _runner(net) -> EngineRunner:
    paths = app_paths().ensure()
    return EngineRunner(fake_engine_spec(), SearchBudget(paths.search_budget_file),
                        env={"TRACKLISTER_FAKE_NETWORK": str(net)})


def _reimported_rows(v) -> list[TrackRow]:
    """The same tracklist imported again: the rows of the 1.0.0 set with fresh uids (as a new import)."""
    doc = SetDoc.from_dict(read_json(set_doc_path(v.set_dir)))
    return [TrackRow.from_dict({**r.to_dict(), "uid": new_uid()}) for r in sorted(doc.rows, key=lambda r: r.pos)]


def _session(v, rows=None) -> SetSession:
    settings = load_settings(app_paths().settings_file)
    return SetSession.create(SET_NAME, rows or _reimported_rows(v), [SourceRef("youtube_comment", "comentario.txt")],
                             settings, v.library_root, app_paths())


def _res(s: SetSession, pos: int):
    return s.doc.results[next(r.uid for r in s.doc.rows if r.pos == pos)]


def _files(d) -> list[str]:
    return sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file() and ".tracklister" not in p.parts
                  and p.suffix in (".flac", ".wav", ".mp3"))


def test_v100_fixtures_are_the_bytes_1_0_0_wrote(v):
    assert v.audio and all(a["same_bytes"] for a in v.audio), [a["path"] for a in v.audio if not a["same_bytes"]]
    doc = SetDoc.from_dict(read_json(set_doc_path(v.set_dir)))
    assert doc.app_version == "1.0.0" and doc.migrations == []
    states = {r.pos: (doc.results[r.uid].state, doc.results[r.uid].doubt) for r in doc.rows}
    assert states[2] == (ResultState.DUDOSO, DoubtKind.IDENTIDAD) and states[9] == (ResultState.DUDOSO, DoubtKind.IDENTIDAD)
    assert {states[p] for p in (4, 5, 6)} == {(ResultState.DUDOSO, DoubtKind.ESPECTRO)}
    assert read_json(app_paths().library_file)["schema"] == "tracklister.library/1"


def test_v100_settings_and_the_stored_account_carry_over(v, fake_keyring):
    s, bad = load_settings_checked(app_paths().settings_file)
    assert bad == [] and s.theme == "noche" and s.preset_id == "lossless" and s.listen_port == 49998
    assert s.library_root == str(v.library_root) and s.first_run_done and s.legal_notice_accepted
    # the account: 1.0.1 reads the keyring entries exactly where 1.0.0 wrote them
    assert v.keyring == {"service": config.KEYRING_SERVICE, "account_key": config.KEYRING_ACCOUNT_KEY}
    keyring.set_password(v.keyring["service"], "usuario-prueba", "clave-prueba")
    keyring.set_password(v.keyring["service"], v.keyring["account_key"], "usuario-prueba")
    assert CredentialStore().get() == CREDS


def test_v100_library_is_re_keyed_and_duplicates_are_still_found(v, tmp_path):
    lib = LibraryIndex(app_paths().library_file)
    lib.load()
    keys = {e.pos: e.key for e in lib.entries}
    assert keys[12] == "fjaak|spirit|kai remix radio edit"           # 1.0.0 wrote 'radio edit kai remix'
    flags = {e.pos: e.flags for e in lib.entries}
    assert flags[6] == ["probable_mp3_convertido"] and flags[4] == ["probable_mp3_convertido"]   # 16.2 / 18.8
    assert flags[5] == [] and flags[3] == []                                                    # 20.2: no mark
    # a new 1.0.1 set with the same tracks, the version groups in another order
    rows = [TrackRow(pos=1, title="Spirit", artists=["Fjaak"], artist_display="Fjaak",
                     version="Kai Remix - Radio Edit", expected_duration_s=12),
            TrackRow(pos=2, title="Show Me That Light", artists=["Kwartz"], artist_display="Kwartz",
                     version="Cleric Remix", expected_duration_s=12)]
    settings = load_settings(app_paths().settings_file)
    s = SetSession.create("Set nuevo", rows, [], settings, v.library_root, app_paths())
    hits = {h.row.pos: h for h in s.find_duplicates(lib)}
    assert set(hits) == {1, 2} and all(h.entries[0].set_name == SET_NAME for h in hits.values())
    lib.save()
    assert read_json(app_paths().library_file)["schema"] == LIBRARY_SCHEMA


def test_v100_fixture_paths_are_installed_as_this_system_writes_them():
    """1.1b, CI run 3: the 1.0.0 files only ever existed on Windows. Installed elsewhere, a path that starts at
    {ROOT} gets that system's separator; on Windows the bytes are the ones 1.0.0 wrote."""
    lib = "{ROOT}\\biblioteca\\Set casa 1.0.0\\12 - Fjaak - Spirit (Radio Edit - Kai Remix).flac"
    long = "\\\\?\\{ROOT}\\home\\data\\work\\eca75c21\\p01\\in\\2\\04-red_rooms-trip.flac"
    soulseek = "Musica Inventada\\Fjaak - Spirit (Kai Remix) (Radio Edit).flac"
    assert local_path(lib, r"C:\t\casa", "\\") == r"C:\t\casa\biblioteca\Set casa 1.0.0\12 - Fjaak - Spirit " \
                                                    r"(Radio Edit - Kai Remix).flac"
    assert local_path(long, r"C:\t\casa", "\\") == (r"\\?\C:\t\casa\home\data\work\eca75c21\p01\in\2"
                                                    r"\04-red_rooms-trip.flac")
    assert local_path(lib, "/private/var/t/casa", "/") == ("/private/var/t/casa/biblioteca/Set casa 1.0.0/12 - Fjaak - "
                                                            "Spirit (Radio Edit - Kai Remix).flac")
    assert local_path(long, "/private/var/t/casa", "/") == ("/private/var/t/casa/home/data/work/eca75c21/p01/in/2/"
                                                             "04-red_rooms-trip.flac")
    assert local_path(soulseek, "/r", "/") == soulseek == local_path(soulseek, r"C:\r", "\\")


def _paths_written(v) -> tuple[list[str], list[str]]:
    """(absolute, relative) paths in what the migration wrote: settings.json, library.json, set.json, journal.json."""
    settings = read_json(app_paths().settings_file)
    library = read_json(app_paths().library_file)
    doc = read_json(set_doc_path(v.set_dir))
    journal = read_json(journal_path(v.set_dir))
    absolute = [settings["library_root"]] + [e["path"] for e in library["entries"]]
    absolute += [p["work_dir"] for p in doc["passes"] if p.get("work_dir")]
    absolute += [op[k] for b in journal["batches"] for op in b["ops"] for k in ("src", "dst")]
    relative = [r[k] for r in doc["results"].values() for k in ("file", "original_file") if r.get(k)]
    return absolute, relative


def test_v100_the_migration_never_writes_a_mixed_separator_path(v):
    """1.1b: every path the migration of 1.0.0 data writes is made with pathlib/os.path, so on macOS it holds no
    Windows '\\' (and on Windows no '/'): the settings saved again, the re-keyed library, the upgraded set and its
    journal. set.json's own paths are relative with '/' on every system (organize.finalize.rel_to_set)."""
    settings, _ = load_settings_checked(app_paths().settings_file)
    save_settings(app_paths().settings_file, settings)
    lib = LibraryIndex(app_paths().library_file)
    lib.load()
    lib.save()
    s = _session(v)
    s.run(_runner(v.network), CREDS, lambda e: None, threading.Event(), lambda rows: set())
    assert s.doc.migrations == [UPGRADE_MARKER]
    s.finalize(LibraryIndex(app_paths().library_file))
    absolute, relative = _paths_written(v)
    assert len(absolute) > 20 and len(relative) >= 10
    foreign = "/" if os.sep == "\\" else "\\"
    assert [p for p in absolute if foreign in p or not os.path.isabs(p.removeprefix(LONG_PREFIX))] == []
    assert [p for p in relative if "\\" in p or os.path.isabs(p)] == []
    assert any(p.endswith(os.sep + "02 - Red Rooms - Trip.flac") for p in absolute)   # the upgrade's own move


def test_v100_opening_the_set_writes_nothing(v):
    before = set_doc_path(v.set_dir).read_bytes()
    s = SetSession.load(v.set_dir, load_settings(app_paths().settings_file), app_paths())
    assert s.doc.migrations == [] and set_doc_path(v.set_dir).read_bytes() == before


def test_v100_rerun_upgrades_once_without_downloading_anything(v):
    s = _session(v)
    files_before = _files(v.set_dir)
    passes = len(s.doc.passes)
    events = []
    s.run(_runner(v.network), CREDS, events.append, threading.Event(), lambda rows: set())
    assert len(s.doc.passes) == passes                                   # no verified row downloaded again
    got = {r.pos: (_res(s, r.pos).state, _res(s, r.pos).doubt) for r in s.doc.rows}
    assert got[1] == (ResultState.NO_ENCONTRADO, None) and got[8] == (ResultState.OMITIDA, None)
    for pos in (3, 7, 11, 12):
        assert got[pos] == (ResultState.VERIFICADO, None), pos
    # R3 on 1.0.0 data: the scene name and the watermark were identity doubts; now verified, to the root
    for pos, name in ((2, "02 - Red Rooms - Trip.flac"), (9, "09 - 13130 Space Project - Talitha.flac")):
        r = _res(s, pos)
        assert (r.state, r.doubt, r.file) == (ResultState.VERIFICADO, None, name), (pos, r.reasons)
        assert r.reasons[0] == UPGRADED_FROM_DUDOSOS_ES and (v.set_dir / name).is_file()
    # R6 on 1.0.0 data: 18.8 and 16.2 kHz keep the strong mark, 20.2 kHz gets only the neutral line
    for pos in (4, 6):
        r = _res(s, pos)
        assert r.state == ResultState.REVISAR_CALIDAD and r.doubt is None and r.score == 100, (pos, r.reasons)
        assert r.flags == ["probable_mp3_convertido"] and r.reasons[0] == UPGRADED_SPECTRUM_ES
    r5 = _res(s, 5)
    assert r5.state == ResultState.VERIFICADO and r5.score == 100 and "posible_falso_lossless" not in r5.flags
    assert "Corte a 20,2 kHz: habitual tanto en MP3 320 como en másters legítimos; no se puede saber solo con el " \
           "espectro." in r5.reasons
    # a real doubt stays a doubt, in _dudosos
    r10 = _res(s, 10)
    assert (r10.state, r10.doubt) == (ResultState.DUDOSO, DoubtKind.VERSION)
    assert r10.file == "_dudosos/10 - Confusion & Tino Machauer - Interchange III.flac"
    assert s.doc.migrations == [UPGRADE_MARKER]
    batch = Journal(v.set_dir).batches()[-1]
    assert batch["label_es"] == UPGRADE_LABEL and batch["committed"] and len(batch["ops"]) == 2
    assert len(_files(v.set_dir)) == len(files_before)                   # moved, never deleted
    s.finalize(LibraryIndex(app_paths().library_file))
    rep = (v.set_dir / f"Informe - {SET_NAME}.txt").read_text(encoding="utf-8")
    assert rep.split("\n")[5] == ("Resumen: verificado 7, verificado \u00b7 revisar calidad 2, dudoso 1, "
                                  "no encontrado 1, omitida 1")
    assert "scúchalo" not in rep and "posible lossless falso" not in rep
    # a second run does nothing more: the upgrade ran once
    journal_len = len(Journal(v.set_dir).batches())
    s2 = _session(v)
    s2.run(_runner(v.network), CREDS, lambda e: None, threading.Event(), lambda rows: set())
    assert s2.doc.migrations == [UPGRADE_MARKER] and len(Journal(v.set_dir).batches()) == journal_len


@pytest.mark.parametrize("dur", [None, 17])
def test_v101_b1clase_the_upgrade_leaves_an_unconfirmed_name_in_dudosos(v, dur):
    """Addendum 10 on the set 1.0.0 wrote: row 2's untagged '04-red_rooms-trip.flac' (a scene name: the artist is
    cut off without ' - ') is in _dudosos. With the row's 12 s it is confirmed and moves (test above). Without an
    expected duration, or with one 5 s off, nothing confirms the name: the one-time check leaves it there."""
    rows = _reimported_rows(v)
    next(r for r in rows if r.pos == 2).expected_duration_s = dur
    s = _session(v, rows)
    passes = len(s.doc.passes)
    s.run(_runner(v.network), CREDS, lambda e: None, threading.Event(), lambda rows: set())
    assert len(s.doc.passes) == passes and s.doc.migrations == [UPGRADE_MARKER]
    r = _res(s, 2)
    assert (r.state, r.doubt) == (ResultState.DUDOSO, DoubtKind.IDENTIDAD), r.reasons
    assert r.file == "_dudosos/02 - Red Rooms - Trip.flac" and (v.set_dir / r.file).is_file()
    assert not (v.set_dir / "02 - Red Rooms - Trip.flac").exists()
    assert UPGRADED_FROM_DUDOSOS_ES not in r.reasons
    # the watermark row (its artist and title tags confirm it) still moves to its number
    assert _res(s, 9).file == "09 - 13130 Space Project - Talitha.flac"


def test_v100_retry_finds_better_copies_of_the_marked_files(v):
    """«Reintentar fallos» on the upgraded 1.0.0 set: clean copies of Border One and Rene Wise from other users
    replace the marked ones, which go to _dudosos; the radio edit in _dudosos is looked for again."""
    s = _session(v)
    net = json.loads(v.network.read_text(encoding="utf-8"))
    net["files"] += [file("peerLimpio", "@@limpio\\Border One - Spectral Tension.flac", "Border One",
                          "Spectral Tension", 12, audio={"seed": 11}),
                     file("peerLimpio", "@@limpio\\Rene Wise - Dynamic.flac", "Rene Wise", "Dynamic", 12,
                          audio={"seed": 12})]
    v.network.write_text(json.dumps(net), encoding="utf-8")
    s.retry_failed(_runner(v.network), CREDS, lambda e: None, threading.Event())
    for pos, name in ((4, "04 - Rene Wise - Dynamic.flac"), (6, "06 - Border One - Spectral Tension.flac")):
        r = _res(s, pos)
        assert r.state == ResultState.VERIFICADO and r.peer == "peerLimpio" and r.file == name, (pos, r.reasons)
        assert (v.set_dir / "_dudosos" / name).is_file()
    assert _res(s, 5).state == ResultState.VERIFICADO and _res(s, 5).peer == "peerC"     # not looked for again
    r10 = _res(s, 10)
    assert r10.state == ResultState.DUDOSO and "peerF" in r10.rejected_peers


def test_v100_r5_editing_only_the_artist_renames_the_file(v):
    """R5: 'GCOD & KYSH Records' (the label credited as co-artist) edited to 'GCOD' in Nuevo set: the file is
    renamed, nothing is downloaded, and the library points to the new name."""
    rows = _reimported_rows(v)
    gcod = next(r for r in rows if r.pos == 7)
    gcod.artist_display, gcod.artists = "GCOD", ["GCOD"]
    s = _session(v, rows)
    assert _res(s, 7).state == ResultState.VERIFICADO                   # the result is kept
    passes = len(s.doc.passes)
    s.run(_runner(v.network), CREDS, lambda e: None, threading.Event(), lambda rows: set())
    lib = LibraryIndex(app_paths().library_file)
    s.finalize(lib)
    assert len(s.doc.passes) == passes
    assert _res(s, 7).file == "07 - GCOD - Incentive Systems.flac"
    assert (v.set_dir / "07 - GCOD - Incentive Systems.flac").is_file()
    assert not (v.set_dir / "07 - GCOD & KYSH Records - Incentive Systems.flac").exists()
    entry = next(e for e in lib.entries if e.pos == 7)
    assert entry.path.endswith("07 - GCOD - Incentive Systems.flac")


def test_v100_decision_b_identifying_the_id_row_adds_only_its_file(v):
    """Decision B: the ID row keeps its number 08. Once identified, only its file is added, with that number,
    and no other file is renamed."""
    rows = _reimported_rows(v)
    idr = next(r for r in rows if r.pos == 8)
    idr.is_id, idr.status, idr.download = False, RowStatus.OK, True
    idr.artist_display, idr.artists, idr.title = "Aidan Rudd", ["Aidan Rudd"], "Necromancer"
    idr.version, idr.expected_duration_s = "Connor Wall Remix", 12
    net = json.loads(v.network.read_text(encoding="utf-8"))
    net["files"].append(file("peerH", "@@inventado\\Lista\\Aidan Rudd - Necromancer (Connor Wall Remix).flac",
                             "Aidan Rudd", "Necromancer (Connor Wall Remix)", 12))
    v.network.write_text(json.dumps(net), encoding="utf-8")
    s = _session(v, rows)
    before = set(_files(v.set_dir))
    s.run(_runner(v.network), CREDS, lambda e: None, threading.Event(), lambda rows: set())
    s.finalize(LibraryIndex(app_paths().library_file))
    new = "08 - Aidan Rudd - Necromancer (Connor Wall Remix).flac"
    assert _res(s, 8).state == ResultState.VERIFICADO and _res(s, 8).file == new
    assert [p.uids for p in s.doc.passes][-1] == [idr.uid]               # the only download of this run
    after = set(_files(v.set_dir))
    moved_by_upgrade = {"_dudosos/02 - Red Rooms - Trip.flac", "_dudosos/09 - 13130 Space Project - Talitha.flac"}
    assert after - before == {new, "02 - Red Rooms - Trip.flac", "09 - 13130 Space Project - Talitha.flac"}
    assert before - after == moved_by_upgrade                            # no other file renamed
    assert not any(b["label_es"].startswith("Actualizar nombres") for b in Journal(v.set_dir).batches())
