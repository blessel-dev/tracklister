"""Every folder listing whose order decides something is read in ONE order on every platform (brief mac-1b):
the library rebuild (the set that wins, the copy «Ya en biblioteca» offers first), Reordenar (the file that
wins a tie) and the stray files. NTFS lists names sorted, APFS in no fixed order, HFS+ hands names back
decomposed (NFD), and pathlib sorts case-insensitively only on Windows: so these tests feed every listing
SHUFFLED (a seeded shuffle of os.scandir, os.walk and Path.iterdir), on Windows too, with names whose
case-sensitive, NFD and NFC orders differ.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import os
import random
import unicodedata
from pathlib import Path

import pytest

from tracklister.core.jsonio import write_json
from tracklister.core.layout import set_doc_path
from tracklister.core.model import ResultState, RowResult, SetDoc, TrackRow
from tracklister.library.index import LibraryIndex
from tracklister.organize.finalize import stray_audio_files
from tracklister.organize.naming import listing_key
from tracklister.organize.reorder import propose_reorder

SEEDS = range(8)
NFD_EXITOS = unicodedata.normalize("NFD", "\u00c9xitos viejos")      # as HFS+ hands it back
NFD_EPOCA = unicodedata.normalize("NFD", "\u00c9poca")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


class _Listing:
    """What os.scandir returns, over a list: a context manager and an iterator (os.walk calls next() on it)."""

    def __init__(self, entries):
        self._it = iter(entries)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._it)

    def close(self):
        pass


@pytest.fixture
def shuffled(monkeypatch):
    """shuffled(seed): from then on os.scandir, os.walk and Path.iterdir list in a seeded random order.
    shuffled.varied() says whether some folder really was listed in more than one order."""
    real_scandir, real_walk, real_iterdir = os.scandir, os.walk, Path.iterdir
    state = {"rng": random.Random(0)}
    orders: dict[str, set[tuple[str, ...]]] = {}

    def seen(folder, names) -> None:
        orders.setdefault(str(folder), set()).add(tuple(names))

    def scandir(path="."):
        with real_scandir(path) as it:
            entries = list(it)
        state["rng"].shuffle(entries)
        seen(("scandir", path), (e.name for e in entries))
        return _Listing(entries)

    def walk(top, *args, **kwargs):
        for dirpath, dirnames, filenames in real_walk(top, *args, **kwargs):
            state["rng"].shuffle(dirnames)             # in place: the walk goes on with this very list
            files = list(filenames)
            state["rng"].shuffle(files)
            seen(("walk", dirpath), files)
            yield dirpath, dirnames, files

    def iterdir(self):
        items = list(real_iterdir(self))
        state["rng"].shuffle(items)
        seen(("iterdir", str(self)), (p.name for p in items))
        return iter(items)

    monkeypatch.setattr(os, "scandir", scandir)
    monkeypatch.setattr(os, "walk", walk)
    monkeypatch.setattr(Path, "iterdir", iterdir)

    def reseed(seed: int) -> None:
        state["rng"] = random.Random(seed)
    reseed.varied = lambda: any(len(v) > 1 for v in orders.values())
    return reseed


def _row(pos, artist, title):
    return TrackRow(pos=pos, title=title, artists=[artist], artist_display=artist)


def test_listing_key_is_case_and_normalisation_blind_and_never_ties():
    assert sorted(["b set", "C set", "a set"], key=listing_key) == ["a set", "b set", "C set"]   # Windows' order
    assert listing_key("E\u0301xitos")[0] == listing_key("\u00c9xitos")[0] == "\u00e9xitos"
    assert listing_key("a") != listing_key("A") and sorted(["a", "A"], key=listing_key) == ["A", "a"]
    assert sorted(["Zeta", NFD_EPOCA], key=listing_key) == ["Zeta", NFD_EPOCA]      # where its NFC spelling goes


def _library_set(root: Path, folder: str, set_id: str, tracks: list[tuple[str, str]]) -> None:
    d = root / folder
    d.mkdir(parents=True)
    rows = [_row(i + 1, a, t) for i, (a, t) in enumerate(tracks)]
    results = {}
    for r in rows:
        name = f"{r.pos:02d} - {r.artist_display} - {r.title}.flac"
        (d / name).write_bytes(folder.encode("utf-8"))
        results[r.uid] = RowResult(r.uid, r.pos, ResultState.VERIFICADO, file=name)
    write_json(set_doc_path(d), SetDoc(set_id=set_id, name=nfc(folder), preset_id="lossless", rows=rows,
                                       results=results).to_dict())


def test_the_library_rebuild_and_ya_en_biblioteca_ignore_the_listing_order(tmp_path, shuffled):
    """The same library from any listing: a copied set folder ("a set", "C set": one set_id) keeps the copy of the
    folder that comes last, and «Ya en biblioteca» offers the copies of a track in one order, the NFD spelling of
    a folder (HFS+) where its NFC one goes."""
    root = tmp_path / "biblioteca"
    spirit, aggression, dynamic = ("Fjaak", "Spirit"), ("Kobosil", "Aggression"), ("Rene Wise", "Dynamic")
    _library_set(root, "a set", "dup00001", [aggression])
    _library_set(root, "C set", "dup00001", [aggression])
    _library_set(root, "b set", "b0000001", [spirit])
    _library_set(root, "Zeta", "z0000001", [spirit])
    _library_set(root, "\u00c9xitos", "e0000002", [dynamic])
    _library_set(root, NFD_EXITOS, "e0000001", [spirit])
    got = set()
    for seed in SEEDS:
        shuffled(seed)
        lib = LibraryIndex(tmp_path / "library.json")
        assert lib.rebuild(root) == 5
        entries = tuple((nfc(Path(e.path).parent.name), e.key) for e in lib.entries)
        offered = tuple(nfc(Path(e.path).parent.name) for e in lib.find(_row(9, *spirit)))
        copies = tuple(nfc(Path(e.path).parent.name) for e in lib.find(_row(9, *aggression)))
        got.add((entries, offered, copies))
    assert len(got) == 1, got
    entries, offered, copies = got.pop()
    assert [folder for folder, _ in entries] == ["b set", "C set", "Zeta", "\u00c9xitos", nfc(NFD_EXITOS)]
    assert offered == ("b set", "Zeta", nfc(NFD_EXITOS)) and copies == ("C set",)
    assert shuffled.varied()                                   # the listings really came in other orders


def test_reordenar_breaks_a_tie_the_same_way_whatever_the_listing(tmp_path, shuffled):
    """Two old copies of the same track fit the row equally well: the same one is proposed every time (and the
    other is the extra), with a folder spelled in NFD placed where its NFC spelling goes."""
    folder = tmp_path / "carpeta vieja"
    for sub in ("Zeta", NFD_EPOCA):
        (folder / sub).mkdir(parents=True)
        (folder / sub / "Fjaak - Spirit.flac").write_bytes(sub.encode("utf-8"))
    (folder / "Kobosil - Aggression.flac").write_bytes(b"k")
    rows = [_row(1, "Fjaak", "Spirit"), _row(2, "Kobosil", "Aggression")]
    got = set()
    for seed in SEEDS:
        shuffled(seed)
        props = propose_reorder(folder, rows)
        got.add(tuple((p.pos, p.status, nfc(str(p.src.relative_to(folder))) if p.src else None) for p in props))
    assert len(got) == 1, got
    proposals = got.pop()
    spirit = next(p for p in proposals if p[0] == 1)
    assert spirit[1] == "ambiguous" and spirit[2] == str(Path("Zeta") / "Fjaak - Spirit.flac")
    assert (0, "extra", nfc(str(Path(NFD_EPOCA) / "Fjaak - Spirit.flac"))) in proposals
    assert shuffled.varied()


def test_the_stray_files_come_in_one_order_whatever_the_listing(tmp_path, shuffled):
    """NFC and NFD spellings of one name fold alike: they still come out in one order, after the other names.
    (NTFS keeps both spellings as two files; APFS, which ignores the normalisation, keeps the first one only.)"""
    set_dir = tmp_path / "Set"
    (set_dir / "_dudosos").mkdir(parents=True)
    cafe_nfd = unicodedata.normalize("NFD", "Caf\u00e9.flac")
    for n in ["b.flac", "C.flac", "Caf\u00e9.flac", cafe_nfd, "a.mp3"]:
        (set_dir / n).write_bytes(b"x")
    (set_dir / "_dudosos" / "Z.flac").write_bytes(b"x")
    cafes = sorted(p.name for p in set_dir.iterdir() if nfc(p.name) == "Caf\u00e9.flac")
    assert cafes in (["Caf\u00e9.flac"], [cafe_nfd, "Caf\u00e9.flac"]), cafes
    used = [RowResult("u1", 1, ResultState.VERIFICADO, file="a.mp3")]
    got = set()
    for seed in SEEDS:
        shuffled(seed)
        got.add(tuple(stray_audio_files(set_dir, used)))
    assert len(got) == 1, got
    assert list(got.pop()) == ["_dudosos/Z.flac", "b.flac", "C.flac", *cafes]      # the NFD spelling first
    assert shuffled.varied()
