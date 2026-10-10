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

from tracklister.core.layout import is_reserved_subdir
from tracklister.core.model import TrackRow
from tracklister.core.textnorm import nfc, norm_key, versions_compatible
from tracklister.organize.journal import Journal
from tracklister.organize.naming import pad_width, track_filename, win_long
from tracklister.verify.audioinfo import read_tags
from tracklister.verify.identity import (
    FileIdentity, artist_match, file_identities, reading_fits, row_artists, title_similarity,
)

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


def _file_identity(f: Path) -> list[FileIdentity]:
    """Every reading of the file (tags first, then its name and folder): the same readings as the download
    verification (verify.identity.file_identities, 1.0.1 R3: scene names, '1-04-', ' - 06 - ', BPM...)."""
    # win_long: a file of an old folder may be past Windows' 260 characters (LongPathsEnabled=0)
    tag_artist, tag_title = read_tags(Path(win_long(f)))
    return file_identities(nfc(f.name), nfc(f.parent.name), tag_artist, tag_title)


def _reading_score(row: TrackRow, fi: FileIdentity) -> float:
    if not norm_key(fi.base):
        return 0.0
    title, _ = title_similarity(row.title, fi.base)
    m = artist_match(row_artists(row), fi.artist) if norm_key(fi.artist) else None
    # audit v101-1 B1: a later reading of the name that moved title words into the artist is no artist
    art = m.score if m is not None and m.same and reading_fits(row_artists(row), fi) else 0.0
    score = 0.4 * art + 0.6 * title
    if not versions_compatible(row.version, fi.version or fi.name_version)[0]:
        score *= 0.5
    return float(score)


def _pair_score(row: TrackRow, ident: list[FileIdentity]) -> float:
    """Same title/artist rules as the download verification (verify.identity): a title with other
    numbers ('Dust 1' / 'Dust 2') scores at most 0.4*100 + 0.6*50 = 70 < MATCH_MIN; a partial
    one-word artist ('Systems' for 'Planetary Assault Systems') or another artist with a similar name
    ('Adam Port' for 'Adam Beyer', 'Ken Faki' for 'Len Faki') counts as no artist at all, so even the
    same title scores at most 0.6*100 = 60 < MATCH_MIN: never a match (audit round 3, B1). The best
    reading of the file name counts."""
    return max((_reading_score(row, fi) for fi in ident), default=0.0)


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


class ReorderError(ValueError):
    """str(error) is the Spanish message: nothing was renamed."""


def _inside(path: Path, folder: Path) -> bool:
    p, f = Path(os.path.abspath(path)), Path(os.path.abspath(folder))
    return f in p.parents


def apply_reorder(folder: Path, proposals: list[ReorderProposal], journal: Journal) -> str:
    """Rename the proposals with status 'match' (the GUI turns confirmed 'ambiguous' ones into
    'match'). Two phases through temporary names; never overwrites. Returns the batch id.

    Every proposal must belong to THIS folder (its file inside it, its new name directly in it) and
    the journal must be the folder's own, or nothing is renamed (ReorderError): a preview made for
    another folder can never rename files whose undo record would then be written somewhere else."""
    folder = Path(folder)
    todo = [p for p in proposals if p.status == "match" and p.src is not None and p.dst is not None
            and Path(p.src) != Path(p.dst)]
    foreign = [p for p in todo if not _inside(p.src, folder)
               or Path(os.path.abspath(p.dst)).parent != Path(os.path.abspath(folder))]
    if foreign or Path(os.path.abspath(journal.set_dir)) != Path(os.path.abspath(folder)):
        raise ReorderError(f"La propuesta no es de la carpeta {folder}: vuelve a pulsar «Ver propuesta». "
                           "No se ha renombrado nada.")
    bid = journal.begin("Reordenar carpeta existente")
    staged = []
    for p in todo:
        tmp = journal.move(bid, p.src, Path(p.src).with_name(f"__tracklister_tmp_{p.uid}{Path(p.src).suffix}"), uid=p.uid)
        staged.append((p, tmp))
    for p, tmp in staged:
        p.dst = journal.move(bid, tmp, p.dst, uid=p.uid)
    journal.commit(bid)
    return bid
