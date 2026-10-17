"""The key assumption of report 3.8, proved on the macOS runner: the engine and yt-dlp the app RUNS are its own
copies outside the .app, and they carry no quarantine even when the bundled files do. So the friend's Mac asks
«Abrir igualmente» once, for Tracklister, and never for sockseek or yt-dlp.

Uses the real pinned binaries that the workflow fetched (tools/fetch_engine.py, packaging/fetch_ytdlp.py), marks
the bundled copies with com.apple.quarantine like a browser download, then lets the app copy them. Neither
binary is ever executed.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import shutil
import stat
import sys
from pathlib import Path

import pytest

from tests.darwin.conftest import REPO, XATTR, fetched_or_skip, run_tool

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="solo macOS")

QUARANTINE = "com.apple.quarantine"
MARK = "0083;66e0a1b2;Safari;"            # flags;time;agent;uuid: what a browser download carries


def quarantined(path: Path) -> bool:
    return run_tool([XATTR, "-p", QUARANTINE, str(path)]).returncode == 0


def test_the_copies_the_app_runs_have_no_quarantine_and_mode_755(tmp_path):
    from tracklister.core.bundled import ytdlp_pin
    from tracklister.core.paths import app_paths
    from tracklister.engine.spec import asset_name, dev_bin_dir, engine_pins, resolve_engine, sha256_file
    from tracklister.gui.services import Services

    pin, ypin = engine_pins()["sockseek-3.0.5"], ytdlp_pin()
    assert (asset_name(pin), ypin.asset_name) == ("sockseek_3.0.5_osx-arm64.tar.gz", "yt-dlp_macos")
    tar = fetched_or_skip(dev_bin_dir() / asset_name(pin))
    ytdlp = fetched_or_skip(REPO / "third_party" / "yt-dlp" / "bin" / ypin.asset_name)
    resources = tmp_path / "Tracklister.app" / "Contents" / "Resources"   # the layout of the real bundle
    bundled_tar = resources / "engines" / tar.name
    bundled_ytdlp = resources / "tools" / ytdlp.name
    for src, dst in ((tar, bundled_tar), (ytdlp, bundled_ytdlp)):
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        r = run_tool([XATTR, "-w", QUARANTINE, MARK, str(dst)])
        assert r.returncode == 0 and quarantined(dst), r.stdout + r.stderr

    paths = app_paths().ensure()
    spec = resolve_engine("sockseek-3.0.5", paths, bundled_dir=resources)
    engine = Path(spec.argv_prefix[0])
    assert engine == paths.tools_dir / "engines" / "sockseek-3.0.5" / "sockseek"
    assert stat.S_IMODE(engine.stat().st_mode) == 0o755
    assert not quarantined(engine) and not quarantined(engine.parent / "LICENSE")

    copy = Services(bundle=resources).ensure_ytdlp()
    assert copy == paths.tools_dir / ypin.exe_name == paths.tools_dir / "yt-dlp"
    assert copy.stat().st_size == ypin.size and sha256_file(copy) == ypin.sha256
    assert stat.S_IMODE(copy.stat().st_mode) == 0o755 and not quarantined(copy)

    # the bundled files keep their mark: only the copies are clean, and the app never runs a bundled file
    assert quarantined(bundled_tar) and quarantined(bundled_ytdlp)
