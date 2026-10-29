"""Atomic JSON read/write. Owner: core (frozen during the parallel phase)."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


def write_json(path: Path, obj: Any, indent: int | None = 2) -> None:
    """Write UTF-8 JSON atomically (temp file in the same dir + os.replace, with retries
    because antivirus/indexers on Windows can briefly lock the target). indent=None writes one line
    (journal.json, rewritten whole after every move: AG-12)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, indent=indent, sort_keys=False)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(data)
            f.write("\n")
            # AG-07: the data must reach the disk before the rename does, or a power cut right after a save can
            # leave the file empty.
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.2 * (attempt + 1))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def read_json(path: Path, default: Any = None) -> Any:
    """Return parsed JSON, or `default` if the file does not exist. Corrupt files raise ValueError."""
    path = Path(path)
    if not path.exists():
        return default
    with open(path, encoding="utf-8-sig") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON corrupto en {path.name}: {e}") from e
