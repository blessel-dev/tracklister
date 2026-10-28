"""core.quarantine (1.1, brief mac-1b): the data-only copy and the narrow quarantine fallback of the two helper
copies. Runs everywhere: the extended attributes are a fake (tests/fakes/xattrs.py) except where noted.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import logging
import os
import shutil
import sys

import pytest

from tests.fakes.xattrs import FakeXattrs
from tracklister.core import quarantine
from tracklister.core.quarantine import QUARANTINE

OTHER = "com.apple.provenance"


@pytest.fixture
def xattrs(monkeypatch):
    fake = FakeXattrs()
    monkeypatch.setattr(quarantine, "_xattrs", fake)
    return fake


@pytest.fixture
def no_shutil_copies(monkeypatch):
    """shutil's copy functions: on macOS they go through fcopyfile(3), which carries the quarantine over."""
    def must_not_run(*a, **k):
        raise AssertionError("the helper copies are never made with shutil's copy functions")
    for name in ("copyfile", "copy", "copy2", "copystat", "copymode"):
        monkeypatch.setattr(shutil, name, must_not_run)


def test_the_libc_attributes_are_only_loaded_on_a_real_mac(monkeypatch):
    monkeypatch.setattr(quarantine, "_xattrs", quarantine._NOT_LOADED)
    api = quarantine._api()
    assert (api is not None) == (sys.platform == "darwin")
    if api is None:                                        # no such attributes here: nothing carries any
        assert quarantine.attribute_names(__file__) == [] and not quarantine.carries(__file__)


def test_the_data_only_copy_has_the_bytes_and_none_of_the_attributes(tmp_path, xattrs, no_shutil_copies):
    src = tmp_path / "yt-dlp_macos"
    src.write_bytes(bytes(range(256)) * 9000)              # more than one chunk
    xattrs.set(src, QUARANTINE)
    xattrs.set(src, OTHER, b"x")
    dst = tmp_path / "tools" / "yt-dlp.part"
    dst.parent.mkdir()
    dst.write_bytes(b"an interrupted copy")
    xattrs.set(dst, QUARANTINE)                           # left by an older copy: a NEW file replaces it
    quarantine.copy_data_only(src, dst)
    assert dst.read_bytes() == src.read_bytes()
    assert quarantine.attribute_names(dst) == [] and not quarantine.carries(dst)
    assert quarantine.attribute_names(src) == [OTHER, QUARANTINE]       # the source is never touched (sorted)


def test_clear_ours_removes_only_the_quarantine_of_our_own_copy(tmp_path, xattrs, caplog):
    tools = tmp_path / "data" / "tools"
    copy = tools / "yt-dlp.part"
    copy.parent.mkdir(parents=True)
    copy.write_bytes(b"pinned bytes")
    xattrs.set(copy, QUARANTINE)
    xattrs.set(copy, OTHER, b"x")
    with caplog.at_level(logging.WARNING, logger="tracklister.platform"):
        assert quarantine.clear_ours(copy, tools)
    assert quarantine.attribute_names(copy) == [OTHER] and xattrs.removed == [("yt-dlp.part", QUARANTINE)]
    assert "macOS put com.apple.quarantine on the yt-dlp.part copy" in caplog.text
    assert str(tmp_path) not in caplog.text                                  # no user path in the log
    assert quarantine.clear_ours(copy, tools) and len(xattrs.removed) == 1   # nothing left to remove


def test_clear_ours_refuses_anything_outside_the_tools_folder(tmp_path, xattrs, caplog):
    tools = tmp_path / "data" / "tools"
    tools.mkdir(parents=True)
    outside = tmp_path / "Tracklister.app" / "Contents" / "Resources" / "tools" / "yt-dlp_macos"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"bundled")
    xattrs.set(outside, QUARANTINE)
    sneaky = tools / ".." / ".." / "Tracklister.app" / "Contents" / "Resources" / "tools" / "yt-dlp_macos"
    xattrs.set(tools, QUARANTINE)
    with caplog.at_level(logging.ERROR, logger="tracklister.platform"):
        assert not quarantine.clear_ours(outside, tools)
        assert not quarantine.clear_ours(sneaky, tools)
        assert not quarantine.clear_ours(tools, tools.parent)             # a folder is not one of the copies
    assert xattrs.removed == [] and quarantine.carries(outside) and quarantine.carries(tools)
    assert "not one of the app's own copies" in caplog.text


def test_clear_ours_never_follows_a_symlink(tmp_path, xattrs):
    tools = tmp_path / "data" / "tools"
    tools.mkdir(parents=True)
    target = tmp_path / "elsewhere"
    target.write_bytes(b"x")
    xattrs.set(target, QUARANTINE)
    link = tools / "yt-dlp"
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("this account cannot create symbolic links")
    assert quarantine.clear_ours(link, tools)               # the link itself carries nothing
    xattrs.set(link, QUARANTINE)                            # and a marked link is refused, never followed
    assert not quarantine.clear_ours(link, tools)
    assert xattrs.removed == [] and quarantine.carries(target)


def test_a_failed_removal_is_reported_not_raised(tmp_path, xattrs, monkeypatch, caplog):
    tools = tmp_path / "tools"
    copy = tools / "sockseek"
    copy.parent.mkdir()
    copy.write_bytes(b"engine")
    xattrs.set(copy, QUARANTINE)

    def refuse(path, name):
        raise PermissionError(1, "Operation not permitted", path)
    monkeypatch.setattr(xattrs, "remove", refuse)
    with caplog.at_level(logging.ERROR, logger="tracklister.platform"):
        assert not quarantine.clear_ours(copy, tools)
    assert quarantine.carries(copy) and "cannot remove com.apple.quarantine from sockseek" in caplog.text


def test_unreadable_attributes_count_as_none(tmp_path, xattrs, monkeypatch, caplog):
    f = tmp_path / "x"
    f.write_bytes(b"x")

    def broken(path, name):
        raise OSError(5, "Input/output error", path)
    monkeypatch.setattr(xattrs, "get", broken)
    with caplog.at_level(logging.WARNING, logger="tracklister.platform"):
        assert not quarantine.carries(f)
    assert "cannot read the attributes of x" in caplog.text
