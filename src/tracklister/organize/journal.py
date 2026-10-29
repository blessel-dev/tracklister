"""Reversible file operations of a set folder (<set>/.tracklister/journal.json).

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Nothing is ever overwritten: an existing destination gets ' (2)', ' (3)'... The journal is saved
after every operation, so a crash still leaves an undoable record. Undo reverts the last batch
in reverse order and reports, in Spanish, anything it could not revert.
"""
from __future__ import annotations

import errno
import hashlib
import logging
import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

from tracklister.core.jsonio import read_json, write_json
from tracklister.core.layout import journal_path
from tracklister.core.model import JOURNAL_SCHEMA, JournalOp
from tracklister.organize.naming import unique_path, win_long

log = logging.getLogger("tracklister.organize")

DRIVE_GONE_ES = "No se encuentra la unidad de la carpeta del set: ¿se ha desconectado el disco?"
DAMAGED_COPY_NAME = "journal-danado.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _copy_via_part(src: str, dst: str) -> str:
    """Copy src to '<dst>.part' and give it the final name only once it is whole. A power cut, a forced close or
    a USB stick pulled out halfway never leaves a cut file under a track's name (the next run would push the good
    one to ' (2)'). Journal.copy uses it, and shutil.move uses it when it has to copy (another drive); a move on
    the same drive is still a rename. A '.part' is not audio: listings and Reordenar ignore it.
    On Windows an antivirus or the indexer can hold the just-written '.part' for a moment, so its rename is
    retried the way write_json retries journal.json (barrido audit AU-2-01)."""
    part = os.fspath(dst) + ".part"
    try:
        shutil.copy2(src, part)                 # the module attribute, so a test can still patch shutil.copy2
        for attempt in range(5):
            try:
                os.replace(part, dst)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.2 * (attempt + 1))
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    return dst


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
        try:
            data = read_json(self.path, default=None)
        except ValueError:
            # an empty or cut journal.json (a power cut right after a save) must never block the set: its undo
            # history is unreadable anyway, so it is set aside and a new journal starts (barrido AG-06)
            data = None
            try:
                os.replace(self.path, self.path.with_name(DAMAGED_COPY_NAME))
            except OSError:
                pass                              # a read-only folder keeps it; the new journal is in memory
            log.warning("journal.json was damaged: kept as %s, a new one starts", DAMAGED_COPY_NAME)
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
            if p.parent == p:
                # the root of a drive or network share that is not there (a USB or network disk that was
                # unplugged): its parent is itself, so walking up would never end (audit round 4, B5)
                raise FileNotFoundError(errno.ENOENT, DRIVE_GONE_ES, str(d))
            missing.append(p)
            p = p.parent
        for m in reversed(missing):
            os.mkdir(win_long(m))
            self._record(batch_id, "mkdir", m, m, None)

    def move(self, batch_id: str, src: Path, dst: Path, uid: str | None = None) -> Path:
        src, dst = Path(src), Path(dst)
        self.mkdir(batch_id, dst.parent)
        real = unique_path(dst)
        try:
            shutil.move(win_long(src), win_long(real), copy_function=_copy_via_part)
        except OSError:
            # When a rename fails (on Windows, a file open in Ableton or a player), shutil.move copies and
            # then cannot delete the source: never leave that copy (or half of it) behind while the source
            # is still there. `real` did not exist before (unique_path). Audit round 4, B4.
            if os.path.lexists(win_long(src)) and os.path.lexists(win_long(real)):
                try:
                    os.remove(win_long(real))
                except OSError:
                    pass
            raise
        self._record(batch_id, "move", src, real, uid)
        return real

    def copy(self, batch_id: str, src: Path, dst: Path, uid: str | None = None) -> Path:
        src, dst = Path(src), Path(dst)
        self.mkdir(batch_id, dst.parent)
        real = unique_path(dst)
        try:
            _copy_via_part(win_long(src), win_long(real))
        except OSError:
            # never leave half a file behind under a final name: `real` did not exist (unique_path)
            try:
                os.remove(win_long(real))
            except OSError:
                pass
            raise
        self._record(batch_id, "copy", src, real, uid)
        return real

    def commit(self, batch_id: str) -> None:
        b = self._batch(batch_id)
        b["committed"] = True
        if not b["ops"]:
            self._data["batches"].remove(b)
        self._save()

    def discard(self, batch_id: str) -> list[str]:
        """Revert a batch that could not finish (it must be the last one) and close it. Returns the
        Spanish lines of what could not be reverted; that stays recorded, so undo can retry it."""
        last = self._data["batches"][-1] if self._data["batches"] else None
        if last is None or last["batch_id"] != batch_id:
            raise KeyError(batch_id)
        errors = self.undo_last()
        if self._data["batches"] and self._data["batches"][-1]["batch_id"] == batch_id:
            self.commit(batch_id)
        return errors

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
