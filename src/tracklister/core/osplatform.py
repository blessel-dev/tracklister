"""Which operating system's POLICY applies: per-user paths, texts, pins, file names, keys, bundle layout.

Owner: platform layer (1.1, macOS).
SPDX-License-Identifier: GPL-3.0-or-later

current() is sys.platform, unless a test simulates another platform with simulate() (tests only, through the
`as_macos` / `as_windows` fixtures of tests/conftest.py). That is how the macOS branches are unit-tested on
Windows, and the Windows branches on the macOS runner. Any platform other than darwin gets exactly the
Windows behaviour (the win32 tables and texts), so code branches on is_macos().

OS MECHANISMS do not ask here: process groups, the \\\\?\\ prefix and the like check the real OS (os.name,
hasattr(os, "killpg")), because simulating darwin cannot give Windows a killpg.
"""
from __future__ import annotations

import contextlib
import platform
import sys
from collections.abc import Iterator

WINDOWS = "win32"
MACOS = "darwin"

_simulated: list[str] = []      # a stack: simulate() nests; module-wide, so worker threads see it too


def current() -> str:
    """The platform whose policy applies: sys.platform, or the innermost simulate()."""
    try:
        return _simulated[-1]           # one read: safe while another thread leaves a simulate() block
    except IndexError:
        return sys.platform


def is_windows() -> bool:
    return current() == WINDOWS


def is_macos() -> bool:
    return current() == MACOS


@contextlib.contextmanager
def simulate(name: str) -> Iterator[None]:
    """Tests only: behave as `name` ("win32", "darwin"...) inside the block. Nests, and always restores."""
    if not isinstance(name, str) or not name:
        raise ValueError(f"not a platform name: {name!r}")
    _simulated.append(name)
    try:
        yield
    finally:
        _simulated.pop()


def os_version() -> str:
    """The OS line of the Diagnóstico: «Windows 11 (build 10.0.26100)» or «macOS 15.6 (arm64)»."""
    if is_macos():
        return f"macOS {platform.mac_ver()[0] or '?'} ({platform.machine()})"
    return f"Windows {platform.release()} (build {platform.version()})"
