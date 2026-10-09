"""Update notice: at most once a day, ETag, rate limits, and no request while the owner is a placeholder."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracklister import config
from tracklister.net.http import HttpClient, HttpError, HttpRequest, ReplayTransport, fixture_path
from tracklister.net.update_check import UpdateInfo, check_for_update, owner_configured

GH = Path(__file__).resolve().parents[1] / "fixtures" / "http" / "github"
DAY = config.UPDATE_CHECK_INTERVAL_S
T0 = 1_791_000_000.0


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setattr(config, "GITHUB_OWNER", "tracklister-test")


def _http(case: str) -> tuple[HttpClient, ReplayTransport]:
    rt = ReplayTransport(GH / case)
    return HttpClient(rt, sleep=lambda s: None), rt


def _state(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def test_fixtures_match_the_api_url(owner):
    req = HttpRequest("GET", config.releases_latest_api_url())
    for case in ("newer", "equal", "ratelimited", "notmodified", "sinrelease"):
        assert fixture_path(GH / case, req).is_file(), case


def test_placeholder_owner_sends_nothing(tmp_path):
    assert config.GITHUB_OWNER == "OWNER_PLACEHOLDER" and not owner_configured()

    def boom(req):
        raise AssertionError("no request may be sent while the owner is a placeholder")

    st = tmp_path / "update.json"
    assert check_for_update(HttpClient(boom), current="1.0.0", state_path=st, now=T0, force=True) is None
    assert not st.exists()


def test_newer_release_shows_a_notice_and_is_checked_once_a_day(owner, tmp_path):
    http, rt = _http("newer")
    st = tmp_path / "update.json"
    info = check_for_update(http, current="1.0.0", state_path=st, now=T0)
    assert info == UpdateInfo(latest="1.0.1",
                              url="https://github.com/tracklister-test/tracklister/releases/tag/v1.0.1",
                              name_es="Tracklister 1.0.1 ya está disponible")
    assert _state(st) == {"last_check": T0, "latest_seen": "1.0.1", "etag": 'W/"etag-101"'}
    headers = dict(rt.calls[0].headers)
    assert headers["Accept"] == "application/vnd.github+json" and "If-None-Match" not in headers
    again = check_for_update(http, current="1.0.0", state_path=st, now=T0 + 3600)
    assert len(rt.calls) == 1                                  # same day: no request
    assert again is not None and again.latest == "1.0.1"
    assert again.url == "https://github.com/tracklister-test/tracklister/releases/latest"
    check_for_update(http, current="1.0.0", state_path=st, now=T0 + DAY + 1)
    assert len(rt.calls) == 2                                  # next day: asks again, with the ETag
    assert dict(rt.calls[1].headers)["If-None-Match"] == 'W/"etag-101"'
    assert check_for_update(http, current="1.0.1", state_path=st, now=T0 + DAY + 2) is None   # updated


def test_force_ignores_the_daily_limit(owner, tmp_path):
    http, rt = _http("equal")
    st = tmp_path / "update.json"
    assert check_for_update(http, current="1.0.0", state_path=st, now=T0) is None
    assert check_for_update(http, current="1.0.0", state_path=st, now=T0 + 10, force=True) is None
    assert len(rt.calls) == 2 and _state(st)["latest_seen"] == "1.0.0"


def test_not_modified_uses_the_saved_version(owner, tmp_path):
    st = tmp_path / "update.json"
    st.write_text(json.dumps({"last_check": T0 - 2 * DAY, "latest_seen": "1.0.1", "etag": 'W/"etag-101"'}),
                  encoding="utf-8")
    http, rt = _http("notmodified")
    info = check_for_update(http, current="1.0.0", state_path=st, now=T0)
    assert info is not None and info.latest == "1.0.1"
    assert dict(rt.calls[0].headers)["If-None-Match"] == 'W/"etag-101"'
    assert _state(st) == {"last_check": T0, "latest_seen": "1.0.1", "etag": 'W/"etag-101"'}


@pytest.mark.parametrize("case", ["ratelimited", "sinrelease"])
def test_rate_limit_or_no_release_is_silent_and_waits_a_day(owner, tmp_path, case):
    http, rt = _http(case)
    st = tmp_path / "update.json"
    assert check_for_update(http, current="1.0.0", state_path=st, now=T0) is None
    assert _state(st)["last_check"] == T0
    assert check_for_update(http, current="1.0.0", state_path=st, now=T0 + 60) is None
    assert len(rt.calls) == 1


def test_offline_and_bad_state_never_raise(owner, tmp_path):
    def offline(req):
        raise HttpError("sin conexión con api.github.com (ConnectionError)")

    st = tmp_path / "update.json"
    st.write_text("{roto", encoding="utf-8")
    assert check_for_update(HttpClient(offline), current="1.0.0", state_path=st, now=T0) is None
    assert st.read_text(encoding="utf-8") == "{roto"           # nothing learnt: try again next launch
    http, _ = _http("newer")
    assert check_for_update(http, current="no-es-version", state_path=st, now=T0) is None
    assert check_for_update(http, current="1.1.0.dev1", state_path=st, now=T0) is None      # dev build is newer
