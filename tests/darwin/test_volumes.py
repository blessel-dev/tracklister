"""A library on a USB stick (report 3.2 and 3.10): finalize, the stray-file list, reorder and the library index
on real HFS+ and exFAT volumes. macOS only; the engine is the fake one, nothing leaves the runner.

- HFS+ hands file names back decomposed (NFD) although the app writes them composed (NFC);
- a volume without extended attributes (exFAT, FAT) gets an AppleDouble '._<name>' file for each file that
  has one: never audio, never proposed, never moved;
- both are case-insensitive: a file renamed in upper case is still its row's file.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import json
import os
import sys
import threading
import unicodedata
from pathlib import Path

import pytest

from tests.darwin.conftest import XATTR, run_tool

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="solo macOS")

FILESYSTEMS = ["HFS+", "ExFAT"]
# (artist, title, seconds): composed accents in both, as the app writes them
TRACKS = [("\u00d1u Sound", "Canci\u00f3n del Ni\u00f1o", 25), ("Sigur R\u00f3s", "Gl\u00f3s\u00f3li", 24),
          ("Fjaak", "Spirit", 30)]
# a 4 KB AppleDouble header (magic 00 05 16 07, version 2), as macOS leaves on a FAT or exFAT stick
APPLEDOUBLE = b"\x00\x05\x16\x07\x00\x02\x00\x00" + b"\x00" * (4096 - 8)


def nfc(name: str) -> str:
    return unicodedata.normalize("NFC", name)


def make_set(volume: Path, tmp_path: Path, name: str = "Set con acentos"):
    """A set whose library root is on `volume` (the work folder stays on the runner's own disk)."""
    from tests.fakes.scenarios import file, row
    from tracklister.core.model import SourceRef
    from tracklister.core.paths import app_paths
    from tracklister.core.settings import Settings
    from tracklister.engine.ratelimit import SearchBudget
    from tracklister.engine.runner import EngineRunner
    from tracklister.engine.spec import fake_engine_spec
    from tracklister.pipeline.session import SetSession

    rows = [row(i + 1, artist, title, dur=dur) for i, (artist, title, dur) in enumerate(TRACKS)]
    files = [file("peerA", f"@@x\\{artist}\\{artist} - {title}.flac", artist, title, dur)
             for artist, title, dur in TRACKS]
    net = tmp_path / f"fakenet-{len(list(tmp_path.glob('fakenet-*')))}.json"
    net.write_text(json.dumps({"schema": "tracklister.fakenet/1", "search_delay_ms": 0, "ban_after_searches": None,
                               "peers": {}, "files": files}, ensure_ascii=False), encoding="utf-8")
    paths = app_paths().ensure()
    root = volume / "biblioteca"
    settings = Settings(preset_id="lossless", library_root=str(root))
    session = SetSession.create(name, rows, [SourceRef("tabla", "acentos.csv")], settings, root, paths)
    runner = EngineRunner(fake_engine_spec(), SearchBudget(paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net)})
    return session, runner, paths, root


def download_and_finalize(session, runner, paths):
    from tracklister.engine.credentials import Credentials
    from tracklister.library.index import LibraryIndex
    session.run(runner, Credentials("usuario-prueba", "clave-prueba"), lambda event: None, threading.Event(),
                lambda rows: set())
    session.finalize(LibraryIndex(paths.library_file))
    return [session.doc.results[r.uid] for r in session.doc.rows]


@pytest.mark.parametrize("fs", FILESYSTEMS)
def test_accented_names_finalize_and_stay_in_the_library(mounted_volume, tmp_path, fs):
    from tracklister.core.model import ResultState
    from tracklister.library.index import LibraryIndex
    from tracklister.organize.finalize import stray_audio_files

    session, runner, paths, root = make_set(mounted_volume(fs), tmp_path)
    results = download_and_finalize(session, runner, paths)
    assert [r.state for r in results] == [ResultState.VERIFICADO] * 3, [(r.state, r.reasons) for r in results]
    on_disk = sorted(p.name for p in session.set_dir.iterdir() if p.suffix == ".flac")
    if fs == "HFS+":                       # HFS+ gives the names back decomposed: the app must not care
        assert any(name != nfc(name) for name in on_disk), on_disk
    assert sorted(nfc(n) for n in on_disk) == sorted(nfc(r.file) for r in results)
    assert stray_audio_files(session.set_dir, session.doc.results.values()) == []
    library = LibraryIndex(paths.library_file)
    assert library.rebuild(root) == 3
    library.save()
    again, _, _, _ = make_set(root.parent, tmp_path, name="Otro set")
    hits = again.find_duplicates(library)
    assert sorted(h.row.pos for h in hits) == [1, 2, 3]                    # «Ya en biblioteca» for all three
    assert all(h.entries and h.entries[0].set_name == "Set con acentos" for h in hits)


@pytest.mark.parametrize("fs", FILESYSTEMS)
def test_appledouble_files_are_never_strays_proposals_or_moved(mounted_volume, tmp_path, fs):
    from tracklister.organize.finalize import stray_audio_files
    from tracklister.organize.journal import Journal
    from tracklister.organize.reorder import apply_reorder, propose_reorder

    session, runner, paths, _ = make_set(mounted_volume(fs), tmp_path)
    download_and_finalize(session, runner, paths)
    first = session.set_dir / session.doc.results[session.doc.rows[0].uid].file
    r = run_tool([XATTR, "-w", "com.tracklister.prueba", "1", str(first)])
    assert r.returncode == 0, r.stdout + r.stderr
    companion = first.with_name("._" + first.name)
    if fs == "ExFAT":                      # no extended attributes on exFAT: macOS writes the '._' file itself
        assert companion.is_file(), sorted(p.name for p in session.set_dir.iterdir())
    else:                                  # HFS+ keeps the attribute inside: plant one, as a copy from a stick would
        assert not companion.exists()
        companion.write_bytes(APPLEDOUBLE)
    orphan = session.set_dir / "._02 - Otro - Tema.aiff"
    orphan.write_bytes(APPLEDOUBLE)
    before = {p.name: p.read_bytes() for p in (companion, orphan)}
    assert stray_audio_files(session.set_dir, session.doc.results.values()) == []
    third = session.set_dir / session.doc.results[session.doc.rows[2].uid].file
    old_name = third.with_name("Fjaak - Spirit.flac")                     # an old folder: a file without its number
    os.rename(third, old_name)
    proposals = propose_reorder(session.set_dir, session.doc.rows)
    named = [Path(p).name for prop in proposals for p in (prop.src, prop.dst) if p is not None]
    assert not [n for n in named if n.startswith("._")], named
    assert [p.status for p in proposals] == ["match"] * 3, [(p.status, p.reason_es) for p in proposals]
    apply_reorder(session.set_dir, proposals, Journal(session.set_dir))
    assert third.is_file() and not old_name.exists()
    assert {p.name: p.read_bytes() for p in (companion, orphan)} == before


@pytest.mark.parametrize("fs", FILESYSTEMS)
def test_a_file_renamed_in_upper_case_is_still_its_row(mounted_volume, tmp_path, fs):
    from tracklister.library.index import LibraryIndex
    from tracklister.organize.finalize import stray_audio_files
    from tracklister.organize.reorder import propose_reorder

    session, runner, paths, root = make_set(mounted_volume(fs), tmp_path)
    download_and_finalize(session, runner, paths)
    second = session.set_dir / session.doc.results[session.doc.rows[1].uid].file
    upper = second.with_name(second.stem.upper() + second.suffix)
    os.rename(second, upper)                                               # a case-only rename
    listed = [nfc(p.name) for p in session.set_dir.iterdir()]
    assert nfc(upper.name) in listed and nfc(second.name) not in listed   # the volume kept the new case
    assert stray_audio_files(session.set_dir, session.doc.results.values()) == []
    library = LibraryIndex(paths.library_file)
    assert library.rebuild(root) == 3                                      # still three entries: no duplicate
    proposals = propose_reorder(session.set_dir, session.doc.rows)
    assert [p.status for p in proposals] == ["match"] * 3, [(p.status, p.reason_es) for p in proposals]
    row2 = next(p for p in proposals if p.pos == 2)
    assert nfc(row2.src.name) == nfc(upper.name)
