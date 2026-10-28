"""The key assumption of report 3.8, proved on the macOS runner: the engine and yt-dlp the app RUNS are its own
copies outside the .app, and they carry no quarantine even when the bundled files do. So the friend's Mac asks
«Abrir igualmente» once, for Tracklister, and never for sockseek or yt-dlp.

Uses the real pinned binaries that the workflow fetched (tools/fetch_engine.py, packaging/fetch_ytdlp.py), marks
the bundled copies with com.apple.quarantine like a browser download, then lets the app copy them. Neither
binary is ever executed. Every check prints the extended attributes of the files it looked at, so a failure
explains itself in the log.

CI run 3 (brief mac-1b): the yt-dlp copy kept the bundled file's quarantine. shutil.copy2 copies through
fcopyfile(3), which applies the source's quarantine to the copy even with COPYFILE_DATA; the app now writes the
copy data-only (tracklister.core.quarantine). test_shutil_copies_carry_the_quarantine_over is that root cause.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import logging
import shutil
import stat
import sys
from pathlib import Path

import pytest

from tests.darwin.conftest import REPO, XATTR, fetched_or_skip, run_tool

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="solo macOS")

QUARANTINE = "com.apple.quarantine"
MARK = "0083;66e0a1b2;Safari;"            # flags;time;agent;uuid: what a browser download carries
OTHER = "com.tracklister.prueba"


def quarantined(path: Path) -> bool:
    return run_tool([XATTR, "-p", QUARANTINE, str(path)]).returncode == 0


def mark(path: Path, name: str = QUARANTINE, value: str = MARK) -> None:
    r = run_tool([XATTR, "-w", name, value, str(path)])
    assert r.returncode == 0, r.stdout + r.stderr


def attrs(*paths: Path) -> str:
    """`xattr -l` of each file: printed (pytest shows it with a failure) and returned for the messages."""
    out = []
    for p in paths:
        r = run_tool([XATTR, "-l", str(p)])
        listing = (r.stdout + r.stderr).strip().replace("\n", " | ") or "(sin atributos)"
        out.append(f"{p.name}: {listing}")
    text = "\n".join(out)
    print(text)
    return text


def _bundle(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Tracklister.app/Contents/Resources with the pinned engine and yt-dlp, both marked like a download."""
    from tracklister.core.bundled import ytdlp_pin
    from tracklister.engine.spec import asset_name, dev_bin_dir, engine_pins

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
        mark(dst)
        assert quarantined(dst), attrs(dst)
    return resources, bundled_tar, bundled_ytdlp


def test_the_copies_the_app_runs_have_no_quarantine_and_mode_755(tmp_path, caplog):
    from tracklister.core import quarantine
    from tracklister.core.bundled import ytdlp_pin
    from tracklister.core.paths import app_paths
    from tracklister.engine.spec import resolve_engine, sha256_file
    from tracklister.gui.services import Services

    resources, bundled_tar, bundled_ytdlp = _bundle(tmp_path)
    ypin = ytdlp_pin()
    paths = app_paths().ensure()
    with caplog.at_level(logging.WARNING, logger="tracklister"):
        spec = resolve_engine("sockseek-3.0.5", paths, bundled_dir=resources)
        engine = Path(spec.argv_prefix[0])
        copy = Services(bundle=resources).ensure_ytdlp()
    report = attrs(bundled_tar, bundled_ytdlp, engine, engine.parent / "LICENSE", copy)
    assert engine == paths.tools_dir / "engines" / "sockseek-3.0.5" / "sockseek"
    assert stat.S_IMODE(engine.stat().st_mode) == 0o755
    assert not quarantined(engine) and not quarantined(engine.parent / "LICENSE"), report
    assert copy == paths.tools_dir / ypin.exe_name == paths.tools_dir / "yt-dlp"
    assert copy.stat().st_size == ypin.size and sha256_file(copy) == ypin.sha256
    assert copy.stat().st_nlink == 1                                      # a copy of its own, not a link
    assert stat.S_IMODE(copy.stat().st_mode) == 0o755 and not quarantined(copy), report
    # the data-only copies were enough: the fallback of core.quarantine (macOS itself marking a fresh copy)
    # never ran, and the library's own reading of the attributes agrees with /usr/bin/xattr
    assert "macOS put com.apple.quarantine" not in caplog.text, caplog.text + report
    for f in (bundled_tar, bundled_ytdlp, engine, copy):
        assert quarantine.carries(f) == quarantined(f), report
    # the bundled files keep their mark: only the copies are clean, and the app never runs a bundled file
    assert quarantined(bundled_tar) and quarantined(bundled_ytdlp), report


def test_shutil_copies_carry_the_quarantine_over(tmp_path):
    """Why the app never copies the helpers with shutil on macOS: fcopyfile(3) applies the source's quarantine
    to the copy even with COPYFILE_DATA (Apple's copyfile.c), so copyfile and copy2 both keep it."""
    from tracklister.core import quarantine

    src = tmp_path / "descargado"
    src.write_bytes(b"\xca\xfe\xba\xbe" + bytes(range(256)) * 512)
    mark(src)
    mark(src, OTHER, "1")
    by_copyfile, by_copy2, data_only = tmp_path / "copyfile", tmp_path / "copy2", tmp_path / "data-only"
    shutil.copyfile(src, by_copyfile)
    shutil.copy2(src, by_copy2)
    quarantine.copy_data_only(src, data_only)
    report = attrs(src, by_copyfile, by_copy2, data_only)
    assert quarantined(by_copyfile) and quarantined(by_copy2), report
    # none of the source's attributes (whatever macOS may add to any new file of its own accord)
    assert not quarantined(data_only) and not {QUARANTINE, OTHER} & set(quarantine.attribute_names(data_only)), report
    assert data_only.read_bytes() == src.read_bytes()


def test_copies_left_quarantined_by_an_older_build_are_replaced(tmp_path, caplog):
    """A yt-dlp copied by 1.1.0.dev1 (mac-1, shutil.copy2) carries the quarantine: it is copied again. The same
    for an engine copy that carries it, whatever put it there: it is extracted again."""
    from tracklister.core.bundled import ytdlp_pin
    from tracklister.core.paths import app_paths
    from tracklister.engine.spec import resolve_engine, sha256_file
    from tracklister.gui.services import Services

    resources, _, bundled_ytdlp = _bundle(tmp_path)
    paths = app_paths().ensure()
    old = paths.tools_dir / ytdlp_pin().exe_name
    old.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundled_ytdlp, old)                                       # what mac-1 did
    mark(old)                                                              # whatever copy2 kept
    assert quarantined(old), attrs(old)
    engine = Path(resolve_engine("sockseek-3.0.5", paths, bundled_dir=resources).argv_prefix[0])
    mark(engine)
    with caplog.at_level(logging.WARNING, logger="tracklister"):
        copy = Services(bundle=resources).ensure_ytdlp()
        again = Path(resolve_engine("sockseek-3.0.5", paths, bundled_dir=resources).argv_prefix[0])
    report = attrs(copy, again)
    assert copy == old and sha256_file(copy) == ytdlp_pin().sha256 and not quarantined(copy), report
    assert again == engine and not quarantined(again) and stat.S_IMODE(again.stat().st_mode) == 0o755, report
    assert "copying it again" in caplog.text and "extracting it again" in caplog.text, caplog.text


def test_clear_ours_removes_only_the_quarantine_and_only_inside_the_tools_folder(tmp_path):
    """The fallback for when macOS itself marks a fresh copy, with the real libc removexattr."""
    from tracklister.core import quarantine
    from tracklister.core.paths import app_paths

    tools = app_paths().ensure().tools_dir
    tools.mkdir(parents=True, exist_ok=True)
    ours = tools / "yt-dlp.part"
    ours.write_bytes(b"pinned bytes")
    outside = tmp_path / "Tracklister.app" / "Contents" / "Resources" / "tools" / "yt-dlp_macos"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"bundled bytes")
    for f in (ours, outside):
        mark(f)
        mark(f, OTHER, "1")
    link = tools / "enlace"
    link.symlink_to(outside)
    assert quarantine.carries(ours) and quarantine.carries(outside), attrs(ours, outside)
    before_ours, before_outside = set(quarantine.attribute_names(ours)), set(quarantine.attribute_names(outside))
    assert {QUARANTINE, OTHER} <= before_ours and {QUARANTINE, OTHER} <= before_outside
    assert quarantine.clear_ours(ours, tools)
    assert not quarantine.clear_ours(outside, tools) and quarantine.clear_ours(link, tools)
    report = attrs(ours, outside)
    assert not quarantined(ours) and set(quarantine.attribute_names(ours)) == before_ours - {QUARANTINE}, report
    assert quarantined(outside) and set(quarantine.attribute_names(outside)) == before_outside, report
