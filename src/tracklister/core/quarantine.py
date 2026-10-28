"""macOS quarantine and the two helpers the app runs there: the engine and yt-dlp (1.1).

Owner: platform layer (1.1, macOS; brief mac-1b).
SPDX-License-Identifier: GPL-3.0-or-later

The app only ever runs its OWN copies of Sockseek and yt-dlp, written to its tools folder
(~/Library/Application Support/Tracklister/tools), never the files inside the .app (engine.spec.resolve_engine,
gui.services.Services.ensure_ytdlp). Inside a downloaded .app those files carry com.apple.quarantine, and
macOS blocks a quarantined command-line tool when the app starts it. So those copies must never carry it:

1. They are written DATA-ONLY. copy_data_only() opens, reads and writes: no extended attributes, flags or
   times. Never shutil.copyfile/copy2 for them on macOS: CPython copies with fcopyfile(3) and COPYFILE_DATA,
   and Apple's copyfile still carries the source's quarantine over (copyfile.c: fcopyfile() reads it with
   copyfile_quarantine() and copyfile_internal() applies it with qtn_file_apply_to_fd(), whatever the flags).
   That was CI run 3: the yt-dlp copy had the pinned bytes and mode 0755, and the bundled file's quarantine.
   tarfile, which extracts the engine, also only writes data.
2. Only if macOS ITSELF still puts the attribute on such a copy, right after the app wrote it from a source
   whose pinned SHA-256 it had just checked, clear_ours() removes ONLY com.apple.quarantine, ONLY from that
   file, and only inside the app's own tools folder (libc removexattr). That is safe: the bytes are the
   pinned ones, the scope is our two helpers, and Gatekeeper still checks the .app itself and every other
   file. Nothing here touches any other file or attribute, or Gatekeeper's settings.

Python's os module has no extended-attribute calls on macOS, so they go through libc (getxattr, listxattr,
removexattr; XATTR_NOFOLLOW). That is an OS mechanism: it is used only where sys.platform is darwin. Anywhere
else there are no such attributes, carries() is False and nothing is removed. Tests swap `_xattrs` for a fake.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

log = logging.getLogger("tracklister.platform")

QUARANTINE = "com.apple.quarantine"
COPY_CHUNK = 1024 * 1024
_XATTR_NOFOLLOW = 0x0001          # <sys/xattr.h>
_ENOATTR = 93                     # <sys/errno.h> on macOS: the attribute does not exist


class _LibcXattrs:
    """Extended attributes of ONE file (never a symlink's target) through macOS libc."""

    def __init__(self) -> None:
        import ctypes
        import ctypes.util
        lib = ctypes.CDLL(ctypes.util.find_library("c") or "/usr/lib/libc.dylib", use_errno=True)
        self._ctypes = ctypes
        self._get = lib.getxattr
        self._get.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32,
                              ctypes.c_int]
        self._get.restype = ctypes.c_ssize_t
        self._list = lib.listxattr
        self._list.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        self._list.restype = ctypes.c_ssize_t
        self._remove = lib.removexattr
        self._remove.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        self._remove.restype = ctypes.c_int

    def _error(self, path: str) -> OSError:
        err = self._ctypes.get_errno()
        return OSError(err, os.strerror(err), path)

    def get(self, path: str, name: str) -> bytes | None:
        """The attribute's value, or None when the file does not carry it."""
        p, n = os.fsencode(path), name.encode("utf-8")
        size = self._get(p, n, None, 0, 0, _XATTR_NOFOLLOW)
        if size < 0:
            err = self._error(path)
            if err.errno == _ENOATTR:
                return None
            raise err
        buf = self._ctypes.create_string_buffer(max(1, size))
        got = self._get(p, n, buf, size, 0, _XATTR_NOFOLLOW)
        if got < 0:
            err = self._error(path)
            if err.errno == _ENOATTR:
                return None
            raise err
        return buf.raw[:got]

    def names(self, path: str) -> list[str]:
        p = os.fsencode(path)
        size = self._list(p, None, 0, _XATTR_NOFOLLOW)
        if size < 0:
            raise self._error(path)
        if size == 0:
            return []
        buf = self._ctypes.create_string_buffer(size)
        got = self._list(p, buf, size, _XATTR_NOFOLLOW)
        if got < 0:
            raise self._error(path)
        return [x.decode("utf-8", "replace") for x in buf.raw[:got].split(b"\0") if x]

    def remove(self, path: str, name: str) -> None:
        if self._remove(os.fsencode(path), name.encode("utf-8"), _XATTR_NOFOLLOW) != 0:
            raise self._error(path)


_NOT_LOADED = object()
_xattrs: object = _NOT_LOADED     # _LibcXattrs on macOS, None elsewhere (or when libc cannot be loaded)


def _api():
    global _xattrs
    if _xattrs is _NOT_LOADED:
        api = None
        if sys.platform == "darwin":
            try:
                api = _LibcXattrs()
            except (OSError, AttributeError) as e:
                log.error("extended attributes unavailable: %s", type(e).__name__)
        _xattrs = api
    return _xattrs


def carries(path: Path | str) -> bool:
    """Does the file at `path` (itself, never a symlink's target) carry com.apple.quarantine? False on a system
    without these attributes, and when they cannot be read (the file is then used as before)."""
    api = _api()
    if api is None:
        return False
    try:
        return api.get(os.fspath(path), QUARANTINE) is not None
    except OSError as e:
        log.warning("cannot read the attributes of %s: %s", Path(path).name, e.strerror or type(e).__name__)
        return False


def attribute_names(path: Path | str) -> list[str]:
    """The names of the file's extended attributes ([] without them, or when they cannot be read)."""
    api = _api()
    if api is None:
        return []
    try:
        return sorted(api.names(os.fspath(path)))
    except OSError:
        return []


def copy_data_only(src: Path | str, dst: Path | str) -> None:
    """Write `dst` as a NEW file with the bytes of `src` and nothing else: no extended attributes (so no
    quarantine), no flags, times or mode. An old `dst` is deleted first, because truncating it would keep its
    attributes."""
    dst = Path(dst)
    try:
        dst.unlink()
    except FileNotFoundError:
        pass
    with open(src, "rb") as fsrc, open(dst, "xb") as fdst:
        shutil.copyfileobj(fsrc, fdst, COPY_CHUNK)


def _inside(path: Path, folder: Path) -> bool:
    real, root = Path(os.path.realpath(path)), Path(os.path.realpath(folder))
    return root in real.parents


def clear_ours(path: Path | str, tools_dir: Path | str) -> bool:
    """Remove com.apple.quarantine, and only that attribute, from `path`: one of the two helper copies (the
    engine or yt-dlp) that the app has just written data-only from a source whose pinned SHA-256 it checked.
    Only for when macOS itself put the attribute there. Refuses anything that is not a regular file inside the
    app's own tools folder (a symlink, or a path that leads out of it). True when `path` no longer carries it."""
    path = Path(path)
    if not carries(path):
        return True
    if path.is_symlink() or not path.is_file() or not _inside(path, Path(tools_dir)):
        log.error("%s: not one of the app's own copies; its attributes are left as they are", path.name)
        return False
    try:
        _api().remove(os.fspath(path), QUARANTINE)
    except OSError as e:
        log.error("cannot remove %s from %s: %s", QUARANTINE, path.name, e.strerror or type(e).__name__)
        return False
    if carries(path):
        log.error("%s still carries %s", path.name, QUARANTINE)
        return False
    log.warning("macOS put %s on the %s copy the app had just written and checked: removed (only that "
                "attribute, only that file)", QUARANTINE, path.name)
    return True
