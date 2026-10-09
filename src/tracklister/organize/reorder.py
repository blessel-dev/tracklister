"""'Reordenar carpeta existente': name an old folder (downloaded with the old tool) in tracklist order.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Fuzzy artist+title match (tags, else the file name), version-aware, optimal one-to-one assignment
(greedy over the sorted score matrix), no substring matching. propose_reorder() only proposes:
the GUI shows a mandatory preview, apply_reorder() renames through the journal (undo) and never
overwrites anything.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz

from tracklister.core.layout import is_reserved_subdir
from tracklister.core.model import TrackRow
from tracklister.core.textnorm import nfc, norm_key, split_title_version, versions_compatible
from tracklister.organize.journal import Journal
from tracklister.organize.naming import pad_width, track_filename
from tracklister.verify.audioinfo import read_tags
from tracklister.verify.identity import parse_name

AUDIO_EXTS = (".flac", ".wav", ".aiff", ".aif", ".mp3", ".m4a", ".ogg", ".opus")
MATCH_MIN = 75.0
AMBIGUOUS_GAP = 5.0


@dataclass
class ReorderProposal:
    uid: str
    pos: int
    src: Path | None
    dst: Path | None
    score: float
    status: str           # "match" | "ambiguous" | "missing" | "extra"
    reason_es: str


def _audio_files(folder: Path) -> list[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not is_reserved_subdir(d)]
        for fn in filenames:
            if Path(fn).suffix.lower() in AUDIO_EXTS and not fn.startswith("__tracklister_tmp_"):
                out.append(Path(dirpath) / fn)
    return sorted(out)


def _file_identity(f: Path) -> tuple[str, str, str | None]:
    tag_artist, tag_title = read_tags(f)
    name_artist, name_title = parse_name(nfc(f.name), nfc(f.parent.name))
    artist = tag_artist or name_artist
    title_full = tag_title or name_title
    base, version = split_title_version(title_full)
    _, name_version = split_title_version(name_title)
    return artist, base or title_full, version or name_version


def _pair_score(row: TrackRow, ident: tuple[str, str, str | None]) -> float:
    artist, base, version = ident
    a = norm_key(artist)
    t = norm_key(base)
    if not t:
        return 0.0
    want_t = norm_key(row.title)
    title = max(fuzz.ratio(want_t, t), fuzz.token_sort_ratio(want_t, t))
    art = 0.0
    for c in [row.artist_display] + list(row.artists or []):
        k = norm_key(c)
        if k and a:
            art = max(art, fuzz.token_set_ratio(k, a), fuzz.ratio(k, a))
    score = 0.4 * art + 0.6 * title
    if not versions_compatible(row.version, version)[0]:
        score *= 0.5
    return float(score)


def propose_reorder(folder: Path, rows: list[TrackRow]) -> list[ReorderProposal]:
    folder = Path(folder)
    files = _audio_files(folder)
    idents = {f: _file_identity(f) for f in files}
    width = pad_width(len(rows))
    usable = [r for r in rows if not r.is_id and (r.title or "").strip()]
    scores: list[tuple[float, int, int]] = []
    per_row: dict[int, list[tuple[float, int]]] = {}
    for ri, row in enumerate(usable):
        for fi, f in enumerate(files):
            s = _pair_score(row, idents[f])
            if s >= MATCH_MIN:
                scores.append((s, ri, fi))
                per_row.setdefault(ri, []).append((s, fi))
    scores.sort(key=lambda x: (-x[0], usable[x[1]].pos, x[2]))
    taken_rows: dict[int, tuple[float, int]] = {}
    taken_files: set[int] = set()
    for s, ri, fi in scores:
        if ri in taken_rows or fi in taken_files:
            continue
        taken_rows[ri] = (s, fi)
        taken_files.add(fi)
    out: list[ReorderProposal] = []
    for ri, row in enumerate(usable):
        if ri not in taken_rows:
            out.append(ReorderProposal(row.uid, row.pos, None, None, 0.0, "missing",
                                       "No hay ningún archivo que encaje con esta fila."))
            continue
        s, fi = taken_rows[ri]
        src = files[fi]
        dst = folder / track_filename(row, src.suffix, width)
        rivals = [x for x in per_row.get(ri, []) if x[1] != fi and s - x[0] <= AMBIGUOUS_GAP]
        if rivals:
            others = ", ".join(files[x[1]].name for x in rivals[:3])
            out.append(ReorderProposal(row.uid, row.pos, src, dst, round(s, 1), "ambiguous",
                                       f"Hay otro archivo casi igual de parecido ({others}): confírmalo."))
        else:
            out.append(ReorderProposal(row.uid, row.pos, src, dst, round(s, 1), "match",
                                       f"Coincide {s:.0f}%."))
    for r in rows:
        if r.is_id or not (r.title or "").strip():
            out.append(ReorderProposal(r.uid, r.pos, None, None, 0.0, "missing",
                                       "Fila sin título o ID: no se empareja con ningún archivo."))
    for fi, f in enumerate(files):
        if fi not in taken_files:
            out.append(ReorderProposal("", 0, f, None, 0.0, "extra",
                                       "Este archivo no encaja con ninguna fila: se deja como está."))
    out.sort(key=lambda p: (p.pos == 0, p.pos, str(p.src or "")))
    return out


def apply_reorder(folder: Path, proposals: list[ReorderProposal], journal: Journal) -> str:
    """Rename the proposals with status 'match' (the GUI turns confirmed 'ambiguous' ones into
    'match'). Two phases through temporary names; never overwrites. Returns the batch id."""
    todo = [p for p in proposals if p.status == "match" and p.src is not None and p.dst is not None
            and Path(p.src) != Path(p.dst)]
    bid = journal.begin("Reordenar carpeta existente")
    staged = []
    for p in todo:
        tmp = journal.move(bid, p.src, Path(p.src).with_name(f"__tracklister_tmp_{p.uid}{Path(p.src).suffix}"), uid=p.uid)
        staged.append((p, tmp))
    for p, tmp in staged:
        p.dst = journal.move(bid, tmp, p.dst, uid=p.uid)
    journal.commit(bid)
    return bid
