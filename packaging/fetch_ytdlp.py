"""Fetch and verify the pinned yt-dlp.exe that ships next to Tracklister.exe (tools\\yt-dlp.exe).

SPDX-License-Identifier: GPL-3.0-or-later

Only public, unauthenticated GitHub GETs (the release asset, its SHA2-256SUMS and the licence
texts at the release tag). Never runs yt-dlp.

    .venv\\Scripts\\python.exe packaging\\fetch_ytdlp.py               # download if missing, verify
    .venv\\Scripts\\python.exe packaging\\fetch_ytdlp.py --verify-only # no network
    .venv\\Scripts\\python.exe packaging\\fetch_ytdlp.py --licences    # refresh third_party/yt-dlp/*.txt

The exe lands in third_party/yt-dlp/bin/ (git-ignored). The app copies it on first run to
%LOCALAPPDATA%\\Tracklister\\tools\\, where "Actualizar yt-dlp" (yt-dlp -U) can update it.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
THIRD_PARTY = REPO / "third_party" / "yt-dlp"
BIN_DIR = THIRD_PARTY / "bin"

VERSION = "2026.08.19"
EXE_NAME = "yt-dlp.exe"
EXE_URL = f"https://github.com/yt-dlp/yt-dlp/releases/download/{VERSION}/{EXE_NAME}"
# GitHub Releases API `digest` of the asset; build time cross-checks it with the release's SHA2-256SUMS.
EXE_SHA256 = "66674953fe251b89f4d08c5f0e35e0728679bd67ab3d7d05c0562af101dd3e7a"
EXE_SIZE = 17840399
SUMS_URL = f"https://github.com/yt-dlp/yt-dlp/releases/download/{VERSION}/SHA2-256SUMS"
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


def exe_path() -> Path:
    return BIN_DIR / EXE_NAME


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


def verify_local() -> list[str]:
    """Problems with the local exe (empty list = OK)."""
    p = exe_path()
    if not p.is_file():
        shown = p.relative_to(REPO) if p.is_relative_to(REPO) else p
        return [f"FALTA {shown}"]
    got = sha256_file(p)
    if got != EXE_SHA256:
        return [f"ERROR SHA-256 {p.name}: esperado {EXE_SHA256}, obtenido {got}"]
    return []


def fetch() -> int:
    p = exe_path()
    if not p.is_file():
        sums = _get(SUMS_URL).text
        listed = sums_entry(sums)
        if listed != EXE_SHA256:
            print(f"ERROR: SHA2-256SUMS de {VERSION} dice {listed}, el pin dice {EXE_SHA256}")
            return 1
        print(f"Descargando {EXE_URL}")
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".part")
        r = _get(EXE_URL, stream=True)
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
        if sha256_file(tmp) != EXE_SHA256:
            tmp.unlink(missing_ok=True)
            print("ERROR: el yt-dlp.exe descargado no coincide con su SHA-256")
            return 1
        tmp.replace(p)
    problems = verify_local()
    for line in problems:
        print(line)
    if not problems:
        print(f"OK {EXE_NAME} {VERSION} sha256={EXE_SHA256}")
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
    ap.add_argument("--verify-only", action="store_true", help="no network; verify the local exe")
    ap.add_argument("--licences", action="store_true", help="download the licence texts of the pinned tag")
    a = ap.parse_args(argv)
    if a.licences:
        return fetch_licences()
    if a.verify_only:
        problems = verify_local()
        for line in problems:
            print(line)
        if not problems:
            print(f"OK {EXE_NAME} {VERSION} sha256={EXE_SHA256}")
        return 1 if problems else 0
    return fetch()


if __name__ == "__main__":
    sys.exit(main())
