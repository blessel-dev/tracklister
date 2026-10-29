"""'Reordenar carpeta existente': name an old folder (downloaded with the old tool) in tracklist order.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Fuzzy artist+title match (tags, else the file name), version-aware, optimal one-to-one assignment
(greedy over the sorted score matrix), no substring matching. propose_reorder() only proposes:
the GUI shows a mandatory preview, apply_reorder() renames through the journal (undo) and never
overwrites anything.

1.0.1, Addendum 10 (DECISIONES X.42): a file whose name only fits its row after leaving words out, or by
cutting the artist off without ' - ' (verify.identity.unconfirmed_es), is never a 'match' unless its
artist and title tags or its duration (within 3 s of the row's expected one) confirm it. It is proposed
as 'ambiguous': unchecked, with the reason, like the other doubtful matches (G.11).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from tracklister.core.layout import is_reserved_subdir
from tracklister.core.model import TrackRow
from tracklister.core.textnorm import nfc, norm_key, versions_compatible
from tracklister.organize.finalize import RENAME_NOT_REVERTED_ES
from tracklister.organize.journal import Journal
from tracklister.organize.naming import is_mac_metadata_file, listing_key, pad_width, track_filename, win_long
from tracklister.verify.audioinfo import read_tags_and_length
from tracklister.verify.identity import (
    FileIdentity, artist_match, duration_confirms, file_identities, reading_fits, row_artists, title_similarity,
    unconfirmed_es,
)

AUDIO_EXTS = (".flac", ".wav", ".aiff", ".aif", ".mp3", ".m4a", ".ogg", ".opus")
MATCH_MIN = 75.0
AMBIGUOUS_GAP = 5.0
UNCONFIRMED_ES = "{why}, y ni las etiquetas ni la duración lo confirman: confírmalo."


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
    """The audio files of an old folder, never its AppleDouble '._*' files (naming.is_mac_metadata_file, on every
    platform): they are never proposed, so apply_reorder never renames them.

    In naming.listing_key order, part by part, never in listing order or by Path: a file's place in this list
    breaks the ties of the assignment (two files that fit a row equally well), so it must be the same on every
    platform (brief mac-1b)."""
    out = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not is_reserved_subdir(d)]
        for fn in filenames:
            if Path(fn).suffix.lower() in AUDIO_EXTS and not fn.startswith("__tracklister_tmp_") \
                    and not is_mac_metadata_file(fn):
                out.append(Path(dirpath) / fn)
    return sorted(out, key=lambda f: [listing_key(part) for part in f.relative_to(folder).parts])


def _file_identity(f: Path) -> tuple[list[FileIdentity], float | None]:
    """Every reading of the file (tags first, then its name and folder): the same readings as the download
    verification (verify.identity.file_identities, 1.0.1 R3: scene names, '1-04-', ' - 06 - ', BPM...),
    and the duration its header says (the confirmation of a guessed reading, Addendum 10)."""
    # win_long: a file of an old folder may be past Windows' 260 characters (LongPathsEnabled=0)
    tag_artist, tag_title, length = read_tags_and_length(Path(win_long(f)))
    return file_identities(nfc(f.name), nfc(f.parent.name), tag_artist, tag_title), length


def _reading_score(row: TrackRow, fi: FileIdentity) -> float:
    if not norm_key(fi.base):
        return 0.0
    title, _ = title_similarity(row.title, fi.base, at_name_start=fi.title_at_name_start)
    m = artist_match(row_artists(row), fi.artist) if norm_key(fi.artist) else None
    # audit v101-1 B1: a later reading of the name that moved title words into the artist is no artist
    art = m.score if m is not None and m.same and reading_fits(row_artists(row), fi) else 0.0
    score = 0.4 * art + 0.6 * title
    if not versions_compatible(row.version, fi.version or fi.name_version)[0]:
        score *= 0.5
    return float(score)


def _pair_score(row: TrackRow, ident: list[FileIdentity], length: float | None = None) -> tuple[float, str | None]:
    """Same title/artist rules as the download verification (verify.identity): a title with other
    numbers ('Dust 1' / 'Dust 2') scores at most 0.4*100 + 0.6*50 = 70 < MATCH_MIN; a partial
    one-word artist ('Systems' for 'Planetary Assault Systems') or another artist with a similar name
    ('Adam Port' for 'Adam Beyer', 'Ken Faki' for 'Len Faki') counts as no artist at all, so even the
    same title scores at most 0.6*100 = 60 < MATCH_MIN: never a match (audit round 3, B1). The best
    reading of the file name counts, and among the readings that reach MATCH_MIN one that needs no
    confirmation wins (Addendum 10). Returns (score, why it still needs a confirmation, or None)."""
    best: tuple[float, str | None] = (0.0, None)
    for fi in ident:
        s = _reading_score(row, fi)
        why = unconfirmed_es(row, fi)
        if why and duration_confirms(row.expected_duration_s, length):
            why = None
        if (s >= MATCH_MIN, s >= MATCH_MIN and why is None, s) > \
                (best[0] >= MATCH_MIN, best[0] >= MATCH_MIN and best[1] is None, best[0]):
            best = (s, why)
    return best


def propose_reorder(folder: Path, rows: list[TrackRow]) -> list[ReorderProposal]:
    folder = Path(folder)
    files = _audio_files(folder)
    idents = {f: _file_identity(f) for f in files}
    width = pad_width(len(rows))
    usable = [r for r in rows if not r.is_id and (r.title or "").strip()]
    scores: list[tuple[float, int, int]] = []
    per_row: dict[int, list[tuple[float, int]]] = {}
    unconfirmed: dict[tuple[int, int], str] = {}
    for ri, row in enumerate(usable):
        for fi, f in enumerate(files):
            s, why = _pair_score(row, *idents[f])
            if s >= MATCH_MIN:
                scores.append((s, ri, fi))
                per_row.setdefault(ri, []).append((s, fi))
                if why:
                    unconfirmed[(ri, fi)] = why
    # equal scores: a confirmed pair first (Addendum 10), then the table order
    scores.sort(key=lambda x: (-x[0], (x[1], x[2]) in unconfirmed, usable[x[1]].pos, x[2]))
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
        why = unconfirmed.get((ri, fi))
        if why:
            reason = UNCONFIRMED_ES.format(why=why[:1].upper() + why[1:])
            if rivals:
                others = ", ".join(files[x[1]].name for x in rivals[:3])
                reason += f" Hay otro archivo casi igual de parecido ({others})."
            out.append(ReorderProposal(row.uid, row.pos, src, dst, round(s, 1), "ambiguous", reason))
        elif rivals:
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


REORDER_LOCKED_ES = ("No se pudo cambiar el nombre de '{name}': está abierto en otro programa (Ableton, un "
                     "reproductor…). Ciérralo y vuelve a pulsar «Aplicar cambios».")
REORDER_FAILED_ES = "No se pudo cambiar el nombre de '{name}' ({err})."
NOTHING_RENAMED_ES = "No se ha renombrado nada."


class ReorderError(ValueError):
    """str(error) is the Spanish message: nothing was renamed. msg_es is the same text, so the window shows it
    as it is (gui.workers.error_text), never as «Error inesperado (ReorderError): …» (barrido CL-08)."""

    def __init__(self, msg_es: str):
        super().__init__(msg_es)
        self.msg_es = msg_es


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
    current: Path | None = None
    renamed: list[tuple[ReorderProposal, Path]] = []
    try:
        staged = []
        for p in todo:
            current = Path(p.src)
            tmp = journal.move(bid, p.src, Path(p.src).with_name(f"__tracklister_tmp_{p.uid}{Path(p.src).suffix}"),
                               uid=p.uid)
            staged.append((p, tmp))
        for p, tmp in staged:
            current = Path(p.src)
            renamed.append((p, journal.move(bid, tmp, p.dst, uid=p.uid)))
    except Exception as e:
        # all or nothing, as sync_names (U.4): a file open in Ableton must not leave the others with their
        # temporary names (barrido CL-08, U.8 N9)
        not_reverted = journal.discard(bid)          # in reverse order: every temporary name goes back
        if not isinstance(e, OSError):
            raise
        name = current.name if current is not None else "?"
        if isinstance(e, PermissionError):
            msg = REORDER_LOCKED_ES.format(name=name)
        else:
            msg = REORDER_FAILED_ES.format(name=name, err=e.strerror or type(e).__name__)
        msg += " " + (" ".join([RENAME_NOT_REVERTED_ES] + not_reverted) if not_reverted else NOTHING_RENAMED_ES)
        raise ReorderError(msg) from e
    journal.commit(bid)
    for p, real in renamed:
        p.dst = real
    return bid
