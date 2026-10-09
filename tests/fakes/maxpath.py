"""Make THIS process behave like a Windows PC whose LongPathsEnabled is 0 (the default), whatever the
registry of the machine running the tests says.

SPDX-License-Identifier: GPL-3.0-or-later

On such a PC a path of 260 characters or more (248 for a new folder) only works with the \\\\?\\
prefix (organize.naming.win_long). simulate_max_path(monkeypatch) makes the file functions Python,
mutagen and soundfile go through refuse an unprefixed long path, like Windows does there:
FileNotFoundError, or False from the os.path checks. Every refused path is recorded, so a test can
also show what would have failed. Paths with the prefix, and short paths, work as usual.

Covered: open/io.open (pathlib, mutagen, csv...), os.open (tempfile), os.stat/lstat (pathlib's
exists/is_file/is_dir, getsize), os.scandir/listdir (iterdir, walk, glob), os.mkdir (Path.mkdir,
makedirs), os.remove/unlink/rmdir/replace/rename (shutil.move), os.utime/chmod, os.path.isfile/
isdir/exists/lexists, _winapi.CopyFile2 (shutil.copy2) and soundfile.SoundFile (libsndfile opens
files itself). The fake engine runs in another process and is not affected.
"""
from __future__ import annotations

import builtins
import errno
import io
import os

MAX_PATH = 260          # a path this long fails (MAX_PATH counts the terminating NUL)
MAX_DIR = 248           # CreateDirectory leaves room for an 8.3 file name
PREFIX = "\\\\?\\"


def too_long(path, limit: int = MAX_PATH) -> bool:
    if isinstance(path, int) or path is None:
        return False
    try:
        s = os.fsdecode(os.fspath(path))
    except TypeError:
        return False
    return not s.startswith(PREFIX) and len(os.path.abspath(s)) >= limit


def simulate_max_path(monkeypatch) -> list[str]:
    """Patch the file functions for the rest of the test. Returns the list of refused paths."""
    import shutil  # noqa: F401 - shutil.copy2 goes through _winapi.CopyFile2 below

    refused: list[str] = []

    def refuse(path):
        s = os.fsdecode(os.fspath(path))
        refused.append(s)
        raise FileNotFoundError(errno.ENOENT, "ruta de más de 260 caracteres sin \\\\?\\ "
                                "(LongPathsEnabled=0, simulado)", s)

    def guard(fn, nargs: int = 1, limit: int = MAX_PATH, first: int = 0):
        def wrapper(*args, **kwargs):
            for p in args[first:first + nargs]:
                if too_long(p, limit):
                    refuse(p)
            return fn(*args, **kwargs)
        wrapper.__wrapped__ = fn
        return wrapper

    def guard_bool(fn):
        def wrapper(path, *args, **kwargs):
            if too_long(path):
                refused.append(os.fsdecode(os.fspath(path)))
                return False
            return fn(path, *args, **kwargs)
        wrapper.__wrapped__ = fn
        return wrapper

    opener = guard(builtins.open)
    monkeypatch.setattr(builtins, "open", opener)
    monkeypatch.setattr(io, "open", opener)
    for name in ("open", "stat", "lstat", "scandir", "listdir", "remove", "unlink", "rmdir", "utime", "chmod"):
        monkeypatch.setattr(os, name, guard(getattr(os, name)))
    monkeypatch.setattr(os, "mkdir", guard(os.mkdir, limit=MAX_DIR))
    for name in ("replace", "rename"):
        monkeypatch.setattr(os, name, guard(getattr(os, name), nargs=2))
    for name in ("isfile", "isdir", "exists", "lexists"):
        monkeypatch.setattr(os.path, name, guard_bool(getattr(os.path, name)))
    try:
        import _winapi
        if hasattr(_winapi, "CopyFile2"):
            monkeypatch.setattr(_winapi, "CopyFile2", guard(_winapi.CopyFile2, nargs=2))
    except ImportError:
        pass
    import soundfile
    monkeypatch.setattr(soundfile.SoundFile, "__init__", guard(soundfile.SoundFile.__init__, first=1))
    return refused
