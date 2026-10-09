"""Reversible file operations of a set folder (<set>/.tracklister/journal.json).

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Nothing is ever overwritten: an existing destination gets ' (2)', ' (3)'... The journal is saved
after every operation, so a crash still leaves an undoable record. Undo reverts the last batch
in reverse order and reports, in Spanish, anything it could not revert.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from tracklister.core.jsonio import read_json, write_json
from tracklister.core.layout import journal_path
from tracklister.core.model import JOURNAL_SCHEMA, JournalOp
from tracklister.organize.naming import unique_path, win_long


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def same_file_content(a: Path, b: Path) -> bool:
    """Same size and SHA-1."""
    try:
        if os.path.getsize(win_long(a)) != os.path.getsize(win_long(b)):
            return False
    except OSError:
        return False

    def sha(p: Path) -> str:
        h = hashlib.sha1()
        with open(win_long(p), "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    return sha(a) == sha(b)


class Journal:
    def __init__(self, set_dir: Path):
        self.set_dir = Path(set_dir)
        self.path = journal_path(self.set_dir)
        data = read_json(self.path, default=None)
        if not isinstance(data, dict) or data.get("schema") != JOURNAL_SCHEMA:
            data = {"schema": JOURNAL_SCHEMA, "batches": []}
        self._data = data

    def _save(self) -> None:
        write_json(self.path, self._data)

    def _batch(self, batch_id: str) -> dict:
        for b in self._data["batches"]:
            if b["batch_id"] == batch_id:
                return b
        raise KeyError(batch_id)

    def begin(self, label_es: str) -> str:
        bid = uuid.uuid4().hex[:12]
        self._data["batches"].append({"batch_id": bid, "label_es": label_es, "created_at": _now(),
                                      "committed": False, "ops": []})
        self._save()
        return bid

    def _record(self, batch_id: str, op: str, src: Path, dst: Path, uid: str | None) -> None:
        self._batch(batch_id)["ops"].append(JournalOp(op, str(src), str(dst), uid, _now()).to_dict())
        self._save()

    def mkdir(self, batch_id: str, d: Path) -> None:
        d = Path(d)
        if os.path.isdir(win_long(d)):
            return
        missing = []
        p = d
        while not os.path.isdir(win_long(p)):
            missing.append(p)
            p = p.parent
        for m in reversed(missing):
            os.mkdir(win_long(m))
            self._record(batch_id, "mkdir", m, m, None)

    def move(self, batch_id: str, src: Path, dst: Path, uid: str | None = None) -> Path:
        src, dst = Path(src), Path(dst)
        self.mkdir(batch_id, dst.parent)
        real = unique_path(dst)
        shutil.move(win_long(src), win_long(real))
        self._record(batch_id, "move", src, real, uid)
        return real

    def copy(self, batch_id: str, src: Path, dst: Path, uid: str | None = None) -> Path:
        src, dst = Path(src), Path(dst)
        self.mkdir(batch_id, dst.parent)
        real = unique_path(dst)
        shutil.copy2(win_long(src), win_long(real))
        self._record(batch_id, "copy", src, real, uid)
        return real

    def commit(self, batch_id: str) -> None:
        b = self._batch(batch_id)
        b["committed"] = True
        if not b["ops"]:
            self._data["batches"].remove(b)
        self._save()

    def batches(self) -> list[dict]:
        return [dict(b) for b in self._data["batches"]]

    def undo_last(self) -> list[str]:
        """Revert the last batch. Returns Spanish error lines; [] when everything was reverted."""
        if not self._data["batches"]:
            return ["No hay nada que deshacer."]
        b = self._data["batches"][-1]
        errors: list[str] = []
        remaining: list[dict] = []
        for op in reversed(b["ops"]):
            kind, src, dst = op["op"], Path(op["src"]), Path(op["dst"])
            try:
                if kind == "move":
                    if not os.path.lexists(win_long(dst)):
                        errors.append(f"No se encuentra {dst.name}: no se puede devolver a su sitio.")
                        remaining.append(op)
                    elif os.path.lexists(win_long(src)):
                        errors.append(f"Ya existe {src.name}: no se sobrescribe; {dst.name} se queda como está.")
                        remaining.append(op)
                    else:
                        os.makedirs(win_long(src.parent), exist_ok=True)
                        shutil.move(win_long(dst), win_long(src))
                elif kind == "copy":
                    if os.path.lexists(win_long(dst)):
                        os.remove(win_long(dst))
                elif kind == "mkdir":
                    try:
                        os.rmdir(win_long(dst))
                    except OSError:
                        pass   # not empty (something else was put there): leave it
            except OSError as e:
                errors.append(f"No se pudo deshacer {Path(dst).name}: {e.strerror or e}.")
                remaining.append(op)
        if remaining:
            b["ops"] = list(reversed(remaining))
        else:
            self._data["batches"].pop()
        self._save()
        return errors
