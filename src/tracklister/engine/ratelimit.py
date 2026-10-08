"""App-wide search budget shared by every engine process (and every Tracklister window).

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

The engines limit searches only inside one process (34 every 220 s by default). Soulseek bans an
account for 30 minutes when it searches too much, so the app reserves its searches in a small
JSON file (%LOCALAPPDATA%\\Tracklister\\search-budget.json) before starting each pass.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

from tracklister.core.jsonio import read_json, write_json

SCHEMA = "tracklister.searchbudget/1"


class _FileLock:
    """Tiny cross-process lock: an exclusively created lock file (stale after 30 s)."""

    def __init__(self, path: Path, timeout_s: float = 10.0):
        self.path, self.timeout_s = Path(str(path) + ".lock"), timeout_s

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_s
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > 30:
                        self.path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() > deadline:
                    raise TimeoutError("search budget lock busy") from None
                time.sleep(0.05)

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


class SearchBudget:
    def __init__(self, path: Path, per_time: int = 34, window_s: int = 220,
                 clock: Callable[[], float] = time.time):
        self.path, self.per_time, self.window_s, self.clock = Path(path), int(per_time), int(window_s), clock

    def _events(self, now: float) -> list[float]:
        try:
            data = read_json(self.path, default={}) or {}
        except ValueError:
            data = {}
        ev = [float(x) for x in data.get("events", []) if isinstance(x, (int, float))]
        return sorted(x for x in ev if now - self.window_s < x <= now + 1)

    def wait_time(self, n: int) -> float:
        """Seconds to wait before n more searches fit in the window (n is capped at per_time)."""
        now = self.clock()
        ev = self._events(now)
        n = max(0, min(int(n), self.per_time))
        excess = len(ev) + n - self.per_time
        if excess <= 0:
            return 0.0
        return max(0.0, ev[excess - 1] + self.window_s - now)

    def reserve(self, n: int) -> None:
        with _FileLock(self.path):
            now = self.clock()
            ev = self._events(now) + [now] * max(0, int(n))
            write_json(self.path, {"schema": SCHEMA, "events": ev[-max(self.per_time * 4, 1):]})
