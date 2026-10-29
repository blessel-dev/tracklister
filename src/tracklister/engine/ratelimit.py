"""App-wide search budget shared by every engine process (and every Tracklister window).

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

The engines limit searches only inside one process (34 every 220 s by default). Soulseek bans an
account for 30 minutes when it searches too much, so the app reserves its searches in a small
JSON file (%LOCALAPPDATA%\\Tracklister\\search-budget.json) before starting each pass.

A pass can need more searches than one window allows (--desperate: up to 7 per row, engine/runner).
The engine then spreads them itself: its limiter hands out per_time searches and gives them all back
one window later (3.x Sockseek.Core/Search/RateLimitedSemaphore.cs:12-39, 2.x Utilities/
RateLimitedSemaphore.cs:9-29). So
reserve() records them the same way, per_time now, per_time one window later..., and the next process
waits for the searches this one is still going to make (1.0.1, R4). Every window such a reservation
covers is kept, however long it is (CL-10). reserve_if_free() checks and reserves in one step under
the file lock, so two windows of the app that start a pass together never both find the budget free.
"""
from __future__ import annotations

import math
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
        # Reservations of k searches reach at most ceil(k / per_time) - 1 windows ahead (reserve()), so every
        # window they cover is kept, however long (CL-10: a deep search of 49+ rows covers more than 10). A
        # timestamp further ahead than all of them could reach means the clock went back, and it is dropped.
        horizon = now + 1 + self.window_s * (math.ceil(len(ev) / max(1, self.per_time)) + 1)
        return sorted(x for x in ev if now - self.window_s < x <= horizon)

    def _wait(self, ev: list[float], n: int, now: float) -> float:
        n = max(0, min(int(n), self.per_time))
        excess = len(ev) + n - self.per_time
        if excess <= 0:
            return 0.0
        return max(0.0, ev[excess - 1] + self.window_s - now)

    def _new(self, n: int, now: float) -> list[float]:
        per = max(1, self.per_time)
        return [now + (i // per) * self.window_s for i in range(max(0, int(n)))]

    def wait_time(self, n: int) -> float:
        """Seconds to wait before n more searches fit in the window (n is capped at per_time).
        Searches reserved for a later window by a running process count as well."""
        now = self.clock()
        return self._wait(self._events(now), n, now)

    def reserve(self, n: int) -> None:
        """Record n searches of the process that starts now: per_time of them now, the next per_time
        one window later, and so on, as the engine's own limiter will make them."""
        with _FileLock(self.path):
            now = self.clock()
            write_json(self.path, {"schema": SCHEMA, "events": sorted(self._events(now) + self._new(n, now))})

    def reserve_if_free(self, n: int) -> float:
        """wait_time() and reserve() in one step, under the file lock (CL-10): 0.0 when the n searches fit
        now and were reserved; otherwise the seconds to wait, and nothing is written."""
        with _FileLock(self.path):
            now = self.clock()
            ev = self._events(now)
            wait = self._wait(ev, n, now)
            if wait <= 0:
                write_json(self.path, {"schema": SCHEMA, "events": sorted(ev + self._new(n, now))})
                return 0.0
            return wait
