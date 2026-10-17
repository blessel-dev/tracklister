"""Compare the installed Python packages with the lock files, and warn about anything that differs.

SPDX-License-Identifier: GPL-3.0-or-later

    .venv/bin/python packaging/check_lock.py [--lock requirements-dev.lock.txt] [--platform darwin]

Reads the lock (and every `-r` file it includes), keeps the pins whose environment marker applies to
this platform, and compares them with the distributions installed in this Python (importlib.metadata).
It prints a GitHub `::warning::` for every installed distribution the lock does not pin (pip
excepted: the venv brings it), every pin installed at another version, and every pin that is
missing. It never stops the job (exit code 0): the same lock serves Windows and macOS, and a warning
on one runner names a platform-only dependency that the lock should pin, as macholib was on macOS.
"""
from __future__ import annotations

import argparse
import sys
from importlib import metadata
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = REPO / "requirements-dev.lock.txt"
NOT_PINNED_OK = {"pip"}


def canonical(name: str) -> str:
    from packaging.utils import canonicalize_name  # the library (a runtime pin), never this folder
    return str(canonicalize_name(name))


def lock_pins(lock: Path, platform: str | None = None, _seen: set[Path] | None = None) -> dict[str, str]:
    """{canonical name: version} of the pins of `lock` and its `-r` includes that apply to `platform`
    (default: this one). A requirement without an exact `==` version maps to ''."""
    from packaging.requirements import Requirement
    env = {"sys_platform": platform or sys.platform}
    seen = set() if _seen is None else _seen
    lock = Path(lock).resolve()
    if lock in seen:
        return {}
    seen.add(lock)
    pins: dict[str, str] = {}
    for raw in lock.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(("-r ", "--requirement ")):
            pins.update(lock_pins(lock.parent / line.split(None, 1)[1].strip(), platform, seen))
            continue
        if line.startswith("-"):
            continue
        req = Requirement(line)
        if req.marker is not None and not req.marker.evaluate(env):
            continue
        exact = [s.version for s in req.specifier if s.operator == "=="]
        pins[canonical(req.name)] = exact[0] if len(exact) == 1 else ""
    return pins


def installed() -> dict[str, str]:
    """{canonical name: version} of every distribution of this Python environment."""
    out: dict[str, str] = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if name:
            out[canonical(name)] = dist.version
    return out


def _same(a: str, b: str) -> bool:
    from packaging.version import InvalidVersion, Version
    try:
        return Version(a) == Version(b)
    except InvalidVersion:
        return a == b


def differences(pins: dict[str, str], have: dict[str, str]) -> list[str]:
    out = []
    for name in sorted(have):
        if name in NOT_PINNED_OK:
            continue
        if name not in pins:
            out.append(f"{name} {have[name]} está instalado, pero el lock no lo fija (¿una dependencia solo de "
                       "esta plataforma?): añádelo con su versión y un marcador sys_platform.")
        elif pins[name] and not _same(have[name], pins[name]):
            out.append(f"{name} instalado {have[name]}, pero el lock fija {pins[name]}.")
    for name in sorted(set(pins) - set(have)):
        out.append(f"{name} {pins[name]} está en el lock, pero no está instalado.")
    return out


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lock", type=Path, default=DEFAULT_LOCK, help="the lock file (default: the dev lock)")
    ap.add_argument("--platform", default=None, help="the sys.platform the markers are evaluated for (default: this one)")
    a = ap.parse_args(argv)
    try:
        pins = lock_pins(a.lock, a.platform)
    except (OSError, ValueError) as e:
        print(f"::warning title=Lock::{_escape(f'No se pudo leer {a.lock.name}: {e}')}")
        return 0
    found = differences(pins, installed())
    for line in found:
        print(f"::warning title=Lock::{_escape(line)}")
    print(f"check_lock: {len(pins)} pines para {a.platform or sys.platform}, {len(found)} avisos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
