"""R12 / Addendum 6: the autouse _no_network guard (tests/conftest.py) trips on a real host.

SPDX-License-Identifier: GPL-3.0-or-later

GITHUB_OWNER is the real "blessel-dev" since 1.0.1, so the update check and the User-Agent now
build real URLs. These tests prove that a connection attempt to a real host is refused AND
recorded (so the guard fails the test at teardown even when app code swallows the error), and
then clear the record so that they themselves pass.
"""
from __future__ import annotations

import socket

import pytest

from tracklister import config
from tracklister.gui.services import Services
from tracklister.net.http import HttpClient, requests_transport


def test_the_guard_trips_on_a_real_host_connection(_no_network):
    assert config.GITHUB_OWNER == "blessel-dev"
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="Network access blocked"):
            s.connect(("140.82.112.6", 443))                  # a public address: never reached
        with pytest.raises(RuntimeError, match="Network access blocked"):
            s.connect_ex(("140.82.112.6", 443))
    finally:
        s.close()
    with pytest.raises(RuntimeError, match="DNS lookup blocked"):
        HttpClient(requests_transport(timeout_s=2), sleep=lambda x: None).get(config.releases_latest_api_url())
    assert len(_no_network) == 3 and "'api.github.com'" in _no_network[2]
    _no_network.clear()                                       # expected attempts: let this test pass


def test_the_window_update_check_is_caught_even_though_the_app_swallows_errors(_no_network, tmp_path):
    # What the window runs 1.5 s after it opens (MainWindow.check_updates -> Services.check_for_update)
    # with the live transport: the app returns None on any error, the guard still records the attempt.
    assert Services(bundle=tmp_path / "bundle").check_for_update(force=True) is None
    assert _no_network and all("api.github.com" in a for a in _no_network)
    _no_network.clear()
