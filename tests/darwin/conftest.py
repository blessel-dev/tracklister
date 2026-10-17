"""macOS-only tests (1.1, report 3.10): they run on the macOS runner of the release workflow and are skipped
everywhere else. Owner: branch B (packaging). Standard library and pytest only at import time, so Windows
collects these modules without importing anything of macOS.

mounted_volume(fs) gives a real HFS+ or exFAT volume (a sparse disk image, attached without Finder and
detached at teardown), so the library tests meet NFD names, AppleDouble '._*' files and a
case-insensitive volume, like a DJ's USB stick.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

HDIUTIL = "/usr/bin/hdiutil"
XATTR = "/usr/bin/xattr"
REPO = Path(__file__).resolve().parents[2]


def run_tool(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def fetched_or_skip(path: Path) -> Path:
    """A binary fetched by tools/fetch_engine.py or packaging/fetch_ytdlp.py: required on the CI runner
    (the workflow fetches it before the tests), skipped elsewhere when it is missing."""
    if path.is_file():
        return path
    if os.environ.get("GITHUB_ACTIONS") == "true":
        pytest.fail(f"falta {path.relative_to(REPO)}: el job de macOS lo descarga antes de los tests")
    pytest.skip(f"falta {path.name} (descárgalo con --platform darwin)")


@pytest.fixture
def mounted_volume(tmp_path):
    """mounted_volume("HFS+" | "ExFAT") -> the mount point of a fresh 64 MB volume of that file system."""
    attached: list[Path] = []

    def _mount(fs: str) -> Path:
        if sys.platform != "darwin":
            pytest.skip("solo macOS")
        image = tmp_path / f"vol-{len(attached)}"
        mount = tmp_path / f"mnt-{len(attached)}"
        mount.mkdir()
        r = run_tool([HDIUTIL, "create", "-size", "64m", "-fs", fs, "-volname", "TL", "-type", "SPARSE", str(image)])
        assert r.returncode == 0, f"hdiutil create -fs {fs}: {r.stdout}{r.stderr}"
        sparse = image.with_name(image.name + ".sparseimage")
        cmd = [HDIUTIL, "attach", "-nobrowse", "-noverify", "-mountpoint", str(mount), str(sparse)]
        r = run_tool(cmd)
        if r.returncode != 0:                      # one retry: the disk arbitration daemon can be slow on CI
            time.sleep(3)
            r = run_tool(cmd)
        assert r.returncode == 0, f"hdiutil attach ({fs}): {r.stdout}{r.stderr}"
        attached.append(mount)
        return mount

    yield _mount
    for mount in attached:
        run_tool([HDIUTIL, "detach", "-force", str(mount)])
