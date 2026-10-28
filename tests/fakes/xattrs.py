"""In-memory extended attributes for the macOS quarantine tests that run on Windows (1.1, brief mac-1b).

SPDX-License-Identifier: GPL-3.0-or-later

Stands in for tracklister.core.quarantine._LibcXattrs: same get/names/remove calls. Like real extended
attributes they belong to the FILE, not to its name: they are keyed by (st_dev, st_ino) of the file itself
(never a symlink's target), so a rename keeps them, a replaced file loses them and a new file has none.
Usage: monkeypatch.setattr(quarantine, "_xattrs", FakeXattrs()).
"""
from __future__ import annotations

import os

ENOATTR = 93


class FakeXattrs:
    def __init__(self) -> None:
        self._store: dict[tuple[int, int], dict[str, bytes]] = {}
        self.removed: list[tuple[str, str]] = []           # (file name, attribute) of every remove() call

    @staticmethod
    def _key(path) -> tuple[int, int]:
        st = os.stat(path, follow_symlinks=False)           # FileNotFoundError when there is no file
        return st.st_dev, st.st_ino

    def set(self, path, name: str, value: bytes = b"0083;66e0a1b2;Safari;") -> None:
        self._store.setdefault(self._key(path), {})[name] = value

    def get(self, path: str, name: str) -> bytes | None:
        return self._store.get(self._key(path), {}).get(name)

    def names(self, path: str) -> list[str]:
        return sorted(self._store.get(self._key(path), {}))

    def remove(self, path: str, name: str) -> None:
        self.removed.append((os.path.basename(path), name))
        attrs = self._store.get(self._key(path), {})
        if name not in attrs:
            raise OSError(ENOATTR, "Attribute not found", path)
        del attrs[name]
