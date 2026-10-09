"""Placing verified downloads in the set folder and keeping names in sync with the table.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import os
import unicodedata
from pathlib import Path
from typing import Iterable

from tracklister.core.layout import DUDOSOS, ORIGINALES
from tracklister.core.model import QUARANTINE_DOUBTS, RowResult, TrackRow
from tracklister.organize.journal import Journal, same_file_content
from tracklister.organize.naming import pad_width, track_filename, win_long
from tracklister.verify.verifier import Verdict

AUDIO_EXTS = (".flac", ".wav", ".aiff", ".aif", ".mp3", ".m4a", ".ogg", ".opus")


def rel_to_set(set_dir: Path, p: Path) -> str:
    return Path(os.path.relpath(p, set_dir)).as_posix()


def target_dir_for(set_dir: Path, verdict: Verdict) -> Path:
    return Path(set_dir) / DUDOSOS if verdict.doubt in QUARANTINE_DOUBTS else Path(set_dir)


def place_verified(set_dir: Path, row: TrackRow, src: Path, verdict: Verdict, width: int,
                   journal: Journal, batch_id: str) -> str:
    """Move `src` to its NN name (set root, or _dudosos for identity/version/duration doubts).

    Idempotent: if the target already holds a file with the same size and SHA-1, `src` is
    removed and the existing target is reused. Never overwrites. Returns RowResult.file.
    """
    set_dir, src = Path(set_dir), Path(src)
    target = target_dir_for(set_dir, verdict) / track_filename(row, src.suffix, width)
    if os.path.lexists(win_long(target)) and same_file_content(src, target):
        os.remove(win_long(src))
        return rel_to_set(set_dir, target)
    real = journal.move(batch_id, src, target, uid=row.uid)
    return rel_to_set(set_dir, real)


def sync_names(set_dir: Path, rows: list[TrackRow], results: dict[str, RowResult], journal: Journal) -> int:
    """Rename existing files after table edits (pos changed): the file AND its copy in _originales,
    in one journal batch. Two phases through temporary names so that swapped positions never
    collide. Returns how many files got a new name."""
    set_dir = Path(set_dir)
    width = pad_width(len(rows))
    plan: list[tuple[RowResult, str, Path, Path]] = []
    for row in rows:
        res = results.get(row.uid)
        if res is None:
            continue
        for attr in ("file", "original_file"):
            rel = getattr(res, attr)
            if not rel:
                continue
            cur = set_dir / rel
            if not os.path.lexists(win_long(cur)):
                continue
            want = cur.parent / track_filename(row, cur.suffix, width)
            if want.name != cur.name:
                plan.append((res, attr, cur, want))
    if not plan:
        return 0
    bid = journal.begin("Actualizar nombres con el orden de la tabla")
    try:
        staged: list[tuple[RowResult, str, Path, Path]] = []
        for res, attr, cur, want in plan:
            tag = "" if attr == "file" else "_orig"
            tmp_name = f"__tracklister_tmp_{res.uid}{tag}{cur.suffix}"
            tmp = journal.move(bid, cur, cur.with_name(tmp_name), uid=res.uid)
            staged.append((res, attr, tmp, want))
        for res, attr, tmp, want in staged:
            real = journal.move(bid, tmp, want, uid=res.uid)
            setattr(res, attr, rel_to_set(set_dir, real))
            res.pos = next((r.pos for r in rows if r.uid == res.uid), res.pos)
    finally:
        journal.commit(bid)
    return len(plan)


def _nfc_key(rel: str) -> str:
    return unicodedata.normalize("NFC", rel.replace("\\", "/")).casefold()


def stray_audio_files(set_dir: Path, results: Iterable[RowResult]) -> list[str]:
    """Audio files in the set folder, _dudosos and _originales that belong to no current result
    (rows deleted from the table, earlier attempts). Relative paths; nothing is ever deleted."""
    set_dir = Path(set_dir)
    used = {_nfc_key(p) for res in results for p in (res.file, res.original_file) if p}
    out: list[str] = []
    for sub in ("", DUDOSOS, ORIGINALES):
        d = set_dir / sub if sub else set_dir
        try:
            with os.scandir(win_long(d)) as it:
                names = [e.name for e in it if e.is_file() and Path(e.name).suffix.lower() in AUDIO_EXTS]
        except OSError:
            continue
        for name in names:
            rel = f"{sub}/{name}" if sub else name
            if _nfc_key(rel) not in used:
                out.append(rel)
    return sorted(out, key=_nfc_key)
