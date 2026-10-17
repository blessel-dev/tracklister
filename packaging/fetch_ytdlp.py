"""Fetch and verify the pinned yt-dlp that ships inside Tracklister (Windows: tools\\yt-dlp.exe next to
Tracklister.exe; macOS: Tracklister.app/Contents/Resources/tools/yt-dlp_macos).

SPDX-License-Identifier: GPL-3.0-or-later

Only public, unauthenticated GitHub GETs (the release asset, its SHA2-256SUMS and the licence
texts at the release tag). Never runs yt-dlp.

    .venv\\Scripts\\python.exe packaging\\fetch_ytdlp.py                    # download if missing, verify
    .venv\\Scripts\\python.exe packaging\\fetch_ytdlp.py --verify-only      # no network
    .venv\\Scripts\\python.exe packaging\\fetch_ytdlp.py --platform darwin  # the macOS binary (yt-dlp_macos)
    .venv\\Scripts\\python.exe packaging\\fetch_ytdlp.py --licences         # refresh third_party/yt-dlp/*.txt

The pins (version, asset, SHA-256, size) live in src/tracklister/core/bundled.py (YTDLP_PINS), the
single source the app also reads. The file lands in third_party/yt-dlp/bin/<asset name> (git-ignored).
The app copies it on first run to its per-user tools folder (%LOCALAPPDATA%\\Tracklister\\tools\\ on
Windows, ~/Library/Application Support/Tracklister/tools/ on macOS), where "Actualizar yt-dlp"
(yt-dlp -U) can update it, and only ever runs that copy.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.append(str(REPO / "src"))      # appended, so nothing on sys.path is shadowed

from tracklister.core.bundled import YtdlpPin, ytdlp_pin  # noqa: E402

THIRD_PARTY = REPO / "third_party" / "yt-dlp"
BIN_DIR = THIRD_PARTY / "bin"
PLATFORMS = ("win32", "darwin")


def default_platform() -> str:
    return "darwin" if sys.platform == "darwin" else "win32"


def asset_url(pin: YtdlpPin) -> str:
    return f"https://github.com/yt-dlp/yt-dlp/releases/download/{pin.version}/{pin.asset_name}"


def sums_url(pin: YtdlpPin) -> str:
    return f"https://github.com/yt-dlp/yt-dlp/releases/download/{pin.version}/SHA2-256SUMS"


# This platform's pin, for the build and the older callers (Windows: yt-dlp.exe, exactly as before).
_PIN = ytdlp_pin(default_platform())
VERSION = _PIN.version
EXE_NAME = _PIN.asset_name
EXE_URL = asset_url(_PIN)
# GitHub Releases API `digest` of the asset; fetch() cross-checks it with the release's SHA2-256SUMS.
EXE_SHA256 = _PIN.sha256
EXE_SIZE = _PIN.size
SUMS_URL = sums_url(_PIN)
LICENCE_FILES = {
    "LICENSE": f"https://raw.githubusercontent.com/yt-dlp/yt-dlp/{VERSION}/LICENSE",
    "THIRD_PARTY_LICENSES.txt": f"https://raw.githubusercontent.com/yt-dlp/yt-dlp/{VERSION}/THIRD_PARTY_LICENSES.txt",
}
SOURCE_URL = f"https://github.com/yt-dlp/yt-dlp/tree/{VERSION}"
USER_AGENT = "Tracklister-build/1.0 (yt-dlp pin fetcher)"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def exe_path(platform: str | None = None) -> Path:
    """Where the pinned binary of `platform` (default: the current one) is kept for the build."""
    return BIN_DIR / ytdlp_pin(platform).asset_name


def _get(url: str, *, stream: bool = False):
    import requests  # lazily: --verify-only needs no network stack
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60, stream=stream,
                             allow_redirects=True)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001 - report and retry
            if attempt == 2:
                raise
            print(f"  reintento {attempt + 1} tras error: {e}")
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def sums_entry(sums_text: str, name: str = EXE_NAME) -> str | None:
    """The hash for `name` in a `<hex>  <name>` checksum file."""
    for line in sums_text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return parts[0].lower()
    return None


def verify_local(platform: str | None = None) -> list[str]:
    """Problems with the local binary of `platform` (empty list = OK): missing, SHA-256, size."""
    pin = ytdlp_pin(platform)
    p = exe_path(platform)
    if not p.is_file():
        shown = p.relative_to(REPO) if p.is_relative_to(REPO) else p
        return [f"FALTA {shown}"]
    got = sha256_file(p)
    if got != pin.sha256:
        return [f"ERROR SHA-256 {p.name}: esperado {pin.sha256}, obtenido {got}"]
    size = p.stat().st_size
    if size != pin.size:
        return [f"ERROR tamaño {p.name}: esperado {pin.size} bytes, obtenido {size}"]
    return []


def _ok_line(pin: YtdlpPin) -> str:
    return f"OK {pin.asset_name} {pin.version} sha256={pin.sha256} ({pin.size} bytes)"


def fetch(platform: str | None = None) -> int:
    pin = ytdlp_pin(platform)
    p = exe_path(platform)
    if not p.is_file():
        sums = _get(sums_url(pin)).text
        listed = sums_entry(sums, pin.asset_name)
        if listed != pin.sha256:
            print(f"ERROR: SHA2-256SUMS de {pin.version} dice {listed} para {pin.asset_name}, el pin dice {pin.sha256}")
            return 1
        print(f"Descargando {asset_url(pin)}")
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".part")
        r = _get(asset_url(pin), stream=True)
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
        if sha256_file(tmp) != pin.sha256 or tmp.stat().st_size != pin.size:
            tmp.unlink(missing_ok=True)
            print(f"ERROR: el {pin.asset_name} descargado no coincide con su SHA-256 o su tamaño")
            return 1
        tmp.replace(p)
    problems = verify_local(platform)
    for line in problems:
        print(line)
    if not problems:
        print(_ok_line(pin))
    return 1 if problems else 0


def fetch_licences() -> int:
    THIRD_PARTY.mkdir(parents=True, exist_ok=True)
    for name, url in LICENCE_FILES.items():
        data = _get(url).content
        (THIRD_PARTY / name).write_bytes(data)
        print(f"OK {name} ({len(data)} bytes) sha256={hashlib.sha256(data).hexdigest()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--verify-only", action="store_true", help="no network; verify the local binary")
    ap.add_argument("--licences", action="store_true", help="download the licence texts of the pinned tag")
    ap.add_argument("--platform", choices=PLATFORMS, default=default_platform(),
                    help="which binary: yt-dlp.exe (win32) or yt-dlp_macos (darwin); default: this computer's")
    a = ap.parse_args(argv)
    if a.licences:
        return fetch_licences()
    if a.verify_only:
        problems = verify_local(a.platform)
        for line in problems:
            print(line)
        if not problems:
            print(_ok_line(ytdlp_pin(a.platform)))
        return 1 if problems else 0
    return fetch(a.platform)


if __name__ == "__main__":
    sys.exit(main())
