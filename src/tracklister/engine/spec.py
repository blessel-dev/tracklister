"""Engine pins and resolution: Sockseek 3.0.5 (default), sldl 2.6.0 (fallback), FAKE engine (tests).

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

The pinned zips are verified by SHA-256 (the digest published by the GitHub Releases API, see
third_party/engines/ENGINE-FACTS.md) before they are unpacked to
%LOCALAPPDATA%\\Tracklister\\tools\\engines\\<engine_id>\\. Nothing here runs the engine.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from tracklister.core.paths import AppPaths


class EngineDialect(StrEnum):
    SOCKSEEK3 = "sockseek3"
    SLDL2 = "sldl2"


@dataclass(frozen=True)
class EnginePin:
    engine_id: str            # "sockseek-3.0.5" | "sldl-2.6.0"
    dialect: EngineDialect
    version: str
    asset_url: str
    asset_sha256: str
    exe_name: str
    license_id: str
    source_url: str           # tag URL


ENGINE_PINS: dict[str, EnginePin] = {
    "sockseek-3.0.5": EnginePin(
        engine_id="sockseek-3.0.5", dialect=EngineDialect.SOCKSEEK3, version="3.0.5",
        asset_url="https://github.com/fiso64/sockseek/releases/download/v3.0.5/sockseek_3.0.5_win-x64.zip",
        asset_sha256="1b5c1189dcfc24cc9fea22dc67a58b7a5f0a127d0367355cf2a8718100044802",
        exe_name="sockseek.exe", license_id="AGPL-3.0-only",
        source_url="https://github.com/fiso64/sockseek/tree/v3.0.5"),
    # Upstream publishes no win-x64 build of 2.6.0: the self-contained win-x86 zip runs on x64
    # Windows without installing .NET (see ENGINE-FACTS.md).
    "sldl-2.6.0": EnginePin(
        engine_id="sldl-2.6.0", dialect=EngineDialect.SLDL2, version="2.6.0",
        asset_url="https://github.com/fiso64/sockseek/releases/download/v2.6.0/sldl_win-x86_self-contained.zip",
        asset_sha256="6e39232c8c22f9b4e5f6a635dae85fdc405e50bcc56392351001d8964cf29a63",
        exe_name="sldl.exe", license_id="GPL-3.0-only",
        source_url="https://github.com/fiso64/sockseek/tree/v2.6.0"),
}
DEFAULT_ENGINE_ID = "sockseek-3.0.5"

# Tag source archives (GPL/AGPL "corresponding source"), shipped next to the binary.
SOURCE_ARCHIVES: dict[str, tuple[str, str]] = {
    "sockseek-3.0.5": ("https://github.com/fiso64/sockseek/archive/refs/tags/v3.0.5.zip",
                       "96e638bb0e76864a2d0c9d1f42321b59e75e4003eca8ec8a31ff3af3c173530d"),
    "sldl-2.6.0": ("https://github.com/fiso64/sockseek/archive/refs/tags/v2.6.0.zip",
                   "1d5d234382488b676f59e8f8a4ff970285b1f1372d20a8d7c3c2c80b8add33aa"),
}

_FAKE_PIN_BY_DIALECT = {EngineDialect.SOCKSEEK3: "sockseek-3.0.5", EngineDialect.SLDL2: "sldl-2.6.0"}
_MARKER = ".tracklister-sha256"


class EngineMissing(Exception):
    """The engine cannot be found or failed verification. `msg_es` is user-facing."""

    def __init__(self, msg_es: str):
        super().__init__(msg_es)
        self.msg_es = msg_es


@dataclass(frozen=True)
class EngineSpec:
    engine_id: str                    # pin id, or "fake:<pin id>"
    dialect: EngineDialect
    argv_prefix: tuple[str, ...]      # (exe,) or (python, ".../tests/fakes/fake_engine.py")

    def is_fake(self) -> bool:
        return self.engine_id.startswith("fake:")


def asset_name(pin: EnginePin) -> str:
    return pin.asset_url.rsplit("/", 1)[-1]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def dev_bin_dir() -> Path:
    """Development location of the downloaded zips (git-ignored)."""
    return repo_root() / "third_party" / "engines" / "bin"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_extract(zip_path: Path, dest: Path) -> None:
    """Extract every regular member, refusing absolute paths and '..' (zip-slip)."""
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = PurePosixPath(info.filename.replace("\\", "/"))
            if info.is_dir():
                continue
            if name.is_absolute() or ".." in name.parts or ":" in info.filename:
                raise EngineMissing(f"El zip del motor contiene una ruta no valida: {info.filename}")
            target = dest.joinpath(*name.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


def resolve_engine(engine_id: str, paths: AppPaths, bundled_dir: Path | None = None) -> EngineSpec:
    """Return a runnable spec for a pinned engine, unpacking its verified zip if needed.

    Looks for the zip next to the frozen exe (`bundled_dir`, and its `engines/` subfolder),
    then in third_party/engines/bin (development). Raises EngineMissing(msg_es).
    """
    pin = ENGINE_PINS.get(engine_id)
    if pin is None:
        raise EngineMissing(f"Motor desconocido: {engine_id}. Elige otro en Ajustes > Motor.")
    target = paths.tools_dir / "engines" / engine_id
    exe = target / pin.exe_name
    marker = target / _MARKER
    if exe.is_file() and marker.is_file() and marker.read_text(encoding="ascii").strip() == pin.asset_sha256:
        return EngineSpec(engine_id, pin.dialect, (str(exe),))

    candidates: list[Path] = []
    if bundled_dir is not None:
        candidates += [Path(bundled_dir) / asset_name(pin), Path(bundled_dir) / "engines" / asset_name(pin)]
    candidates.append(dev_bin_dir() / asset_name(pin))
    for zpath in candidates:
        if not zpath.is_file():
            continue
        got = sha256_file(zpath)
        if got != pin.asset_sha256:
            raise EngineMissing(
                f"El archivo del motor {zpath.name} no coincide con su huella SHA-256 "
                f"(esperada {pin.asset_sha256[:12]}..., encontrada {got[:12]}...). "
                "Vuelve a descargar Tracklister desde su pagina oficial.")
        tmp = target.with_name(target.name + ".tmp")
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        _safe_extract(zpath, tmp)
        if not (tmp / pin.exe_name).is_file():
            shutil.rmtree(tmp, ignore_errors=True)
            raise EngineMissing(f"El zip {zpath.name} no contiene {pin.exe_name}.")
        (tmp / _MARKER).write_text(pin.asset_sha256, encoding="ascii")
        if target.exists():
            shutil.rmtree(target)
        tmp.replace(target)
        return EngineSpec(engine_id, pin.dialect, (str(target / pin.exe_name),))
    raise EngineMissing(
        f"No se encuentra el motor {engine_id} ({asset_name(pin)}). "
        "Vuelve a descomprimir Tracklister completo o reinstalalo.")


def fake_engine_spec(dialect: EngineDialect = EngineDialect.SOCKSEEK3) -> EngineSpec:
    """The offline stand-in used by every engine test and by the GUI screenshots (dev only)."""
    script = repo_root() / "tests" / "fakes" / "fake_engine.py"
    return EngineSpec(f"fake:{_FAKE_PIN_BY_DIALECT[dialect]}", dialect, (sys.executable, str(script)))
