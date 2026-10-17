"""Fetch and verify the pinned Soulseek engines (Sockseek 3.0.5 and the sldl 2.6.0 fallback).

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Only public, unauthenticated GitHub GETs: the Releases API, the pinned release assets and the
tag source archives. This script never runs the engine and never talks to Soulseek.

Usage (from the repo root):
    .venv\\Scripts\\python.exe tools\\fetch_engine.py               # download what is missing, verify
    .venv\\Scripts\\python.exe tools\\fetch_engine.py --verify-only # no network: verify local files
    .venv\\Scripts\\python.exe tools\\fetch_engine.py --list        # print assets + digests from the API
    .venv\\Scripts\\python.exe tools\\fetch_engine.py --platform darwin   # the macOS (arm64) pins

Each platform has its own pins (src/tracklister/engine/spec.py, engine_pins()): Windows gets both
engines as zips; macOS only Sockseek 3.0.5, as its osx-arm64 .tar.gz, also checked by size. The
default platform is this computer's.

Files land in third_party/engines/bin/ (git-ignored) and the tag sources in
third_party/engines/bin/src/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from tracklister.engine.spec import (  # noqa: E402
    asset_name, dev_bin_dir, engine_pins, sha256_file, source_archives,
)

API_TAG = "https://api.github.com/repos/fiso64/sockseek/releases/tags/{tag}"
USER_AGENT = "Tracklister-build/1.0 (engine pin fetcher)"
PLATFORMS = ("win32", "darwin")


def default_platform() -> str:
    return "darwin" if sys.platform == "darwin" else "win32"


def _get(url: str, *, stream: bool = False):
    import requests  # imported lazily: --verify-only needs no network stack
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    for attempt in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=60, stream=stream, allow_redirects=True)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001 - report and retry
            if attempt == 2:
                raise
            print(f"  reintento {attempt + 1} tras error: {e}")
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def list_release(tag: str) -> dict:
    data = _get(API_TAG.format(tag=tag)).json()
    out = {"tag": data.get("tag_name"), "name": data.get("name"),
           "published_at": data.get("published_at"), "zipball_url": data.get("zipball_url"),
           "assets": []}
    for a in data.get("assets", []):
        out["assets"].append({"name": a.get("name"), "size": a.get("size"),
                              "digest": a.get("digest"),
                              "url": a.get("browser_download_url")})
    return out


def _download(url: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    r = _get(url, stream=True)
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 20):
            if chunk:
                f.write(chunk)
    tmp.replace(dst)


def verify(fetch: bool, platform: str | None = None) -> int:
    """Download (when `fetch`) and check the pinned archives of `platform` and their tag sources."""
    errors = 0
    bdir = dev_bin_dir()
    for pin in engine_pins(platform or default_platform()).values():
        dst = bdir / asset_name(pin)
        if not dst.exists():
            if not fetch:
                print(f"FALTA {dst.name} ({pin.engine_id})")
                errors += 1
                continue
            print(f"Descargando {pin.asset_url}")
            _download(pin.asset_url, dst)
        got = sha256_file(dst)
        size = dst.stat().st_size
        if got != pin.asset_sha256:
            print(f"ERROR SHA-256 {dst.name}: esperado {pin.asset_sha256}, obtenido {got}")
            errors += 1
        elif pin.asset_size is not None and size != pin.asset_size:
            print(f"ERROR tamaño {dst.name}: esperado {pin.asset_size} bytes, obtenido {size}")
            errors += 1
        elif pin.asset_size is not None:
            print(f"OK {dst.name} sha256={got} ({size} bytes)")
        else:
            print(f"OK {dst.name} sha256={got}")
    for engine_id, (url, expected) in source_archives(platform or default_platform()).items():
        dst = bdir / "src" / f"{engine_id}-src.zip"
        if not dst.exists():
            if not fetch:
                print(f"AVISO falta el codigo fuente {dst.name} (no bloquea)")
                continue
            print(f"Descargando {url}")
            _download(url, dst)
        got = sha256_file(dst)
        if expected and got != expected:
            # GitHub generates tag archives on the fly; a changed hash is reported, not fatal.
            print(f"AVISO SHA-256 del codigo fuente {dst.name}: esperado {expected}, obtenido {got}")
        else:
            print(f"OK {dst.name} sha256={got}")
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify-only", action="store_true", help="no network; verify local files")
    ap.add_argument("--list", action="store_true", help="print the pinned releases from the API")
    ap.add_argument("--platform", choices=PLATFORMS, default=default_platform(),
                    help="whose pins: win32 (both engines, zips) or darwin (Sockseek, tar.gz); default: this one")
    a = ap.parse_args(argv)
    if a.list:
        for tag in sorted({"v" + p.version for p in engine_pins(a.platform).values()}):
            print(json.dumps(list_release(tag), indent=2))
        return 0
    return verify(fetch=not a.verify_only, platform=a.platform)


if __name__ == "__main__":
    raise SystemExit(main())
