"""A library drive that disappears (an unplugged USB or network disk), seen by ONE module only.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

unplug_drive(monkeypatch, module) swaps that module's `os` for a proxy whose os.path.isdir() is always
False, as when the drive of the set folder is gone; everything else is the real `os`, and no other
module (nor pytest) is affected. A counting guard raises LoopGuard after `limit` calls, so code that
would keep walking up the folders forever (audit round 4, B5) fails the test instead of hanging it.
"""
from __future__ import annotations


class LoopGuard(RuntimeError):
    """os.path.isdir() was asked about folders without end."""


class _Proxy:
    def __init__(self, real, **override):
        self._real = real
        self.__dict__.update(override)

    def __getattr__(self, name):
        return getattr(self._real, name)


def unplug_drive(monkeypatch, module, *, limit: int = 1000) -> dict:
    calls = {"isdir": 0}
    real_os = module.os

    def isdir(_path) -> bool:
        calls["isdir"] += 1
        if calls["isdir"] > limit:
            raise LoopGuard("os.path.isdir() llamado sin fin")
        return False

    monkeypatch.setattr(module, "os", _Proxy(real_os, path=_Proxy(real_os.path, isdir=isdir)))
    return calls
