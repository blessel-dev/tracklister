"""Placing verified downloads in the set folder and keeping names in sync with the table.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import os
from pathlib import Path

from tracklister.core.layout import DUDOSOS
from tracklister.core.model import QUARANTINE_DOUBTS, RowResult, TrackRow
from tracklister.organize.journal import Journal, same_file_content
from tracklister.organize.naming import pad_width, track_filename, win_long
from tracklister.verify.verifier import Verdict


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
    """Rename existing files after table edits (pos changed). Two phases through temporary names
    so that swapped positions never collide. Returns how many files got a new name."""
    set_dir = Path(set_dir)
    width = pad_width(len(rows))
    plan: list[tuple[RowResult, Path, Path]] = []
    for row in rows:
        res = results.get(row.uid)
        if res is None or not res.file:
            continue
        cur = set_dir / res.file
        if not os.path.lexists(win_long(cur)):
            continue
        want = cur.parent / track_filename(row, cur.suffix, width)
        if want.name != cur.name:
            plan.append((res, cur, want))
    if not plan:
        return 0
    bid = journal.begin("Actualizar nombres con el orden de la tabla")
    staged: list[tuple[RowResult, Path, Path]] = []
    for res, cur, want in plan:
        tmp = journal.move(bid, cur, cur.with_name(f"__tracklister_tmp_{res.uid}{cur.suffix}"), uid=res.uid)
        staged.append((res, tmp, want))
    for res, tmp, want in staged:
        real = journal.move(bid, tmp, want, uid=res.uid)
        res.file = rel_to_set(set_dir, real)
        res.pos = next((r.pos for r in rows if r.uid == res.uid), res.pos)
    journal.commit(bid)
    return len(plan)
