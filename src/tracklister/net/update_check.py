"""In-app update notice: GitHub releases/latest at most once a day, a link, never an install.

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

State lives in %APPDATA%\\Tracklister\\update.json: {last_check: epoch, latest_seen, etag}.
The ETag makes the daily request conditional (a 304 answer does not count against GitHub's
60 requests/hour for unauthenticated clients). While config.GITHUB_OWNER is still the build
placeholder, nothing is requested at all. Any error -> None: no notice, no exception.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from packaging.version import InvalidVersion, Version

from tracklister import config
from tracklister.core.jsonio import read_json, write_json
from tracklister.net.http import HttpClient, ReplayMiss

_OWNER_OK = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


@dataclass(frozen=True)
class UpdateInfo:
    latest: str          # "1.0.1"
    url: str             # release page to open in the browser
    name_es: str         # "Tracklister 1.0.1 ya está disponible"


def owner_configured() -> bool:
    owner = config.GITHUB_OWNER or ""
    return bool(_OWNER_OK.match(owner)) and "PLACEHOLDER" not in owner.upper()


def _version(s: str | None) -> Version | None:
    try:
        return Version((s or "").strip().lstrip("vV"))
    except InvalidVersion:
        return None


def _load_state(path: Path) -> dict:
    try:
        d = read_json(path, default={})
    except ValueError:
        d = {}
    return d if isinstance(d, dict) else {}


def _info(latest: str, url: str | None) -> UpdateInfo:
    return UpdateInfo(latest=latest, url=url or f"{config.project_url()}/releases/latest",
                      name_es=f"Tracklister {latest} ya está disponible")


def check_for_update(http: HttpClient, *, current: str, state_path: Path, now: float,
                     interval_s: int = config.UPDATE_CHECK_INTERVAL_S, force: bool = False) -> UpdateInfo | None:
    if not owner_configured():
        return None
    cur = _version(current)
    if cur is None:
        return None
    state = _load_state(state_path)
    latest_seen, etag = state.get("latest_seen"), state.get("etag")
    last = state.get("last_check")
    recent = isinstance(last, (int, float)) and 0 <= now - float(last) < interval_s
    url = None
    if force or not recent:
        headers = {"Accept": "application/vnd.github+json"}
        if etag and latest_seen:
            headers["If-None-Match"] = etag
        try:
            resp = http.get(config.releases_latest_api_url(), headers=headers)
        except ReplayMiss:
            raise                                    # tests: a missing fixture must fail loudly
        except Exception:  # offline, DNS, proxy...: no notice; try again next launch
            return None
        tag = None
        if resp.status == 200:
            try:
                data = resp.json()
                tag = str(data.get("tag_name") or "")
                url = data.get("html_url") or None
            except (ValueError, AttributeError, UnicodeDecodeError):
                tag = None
        if resp.status != 304 and _version(tag) is None:   # 403/429 rate limit, 404 no release yet...
            state["last_check"] = now
            _save(state_path, state)
            return None
        if resp.status == 200:
            latest_seen, etag = tag.lstrip("vV"), resp.header("etag")
        state.update(last_check=now, latest_seen=latest_seen, etag=etag)
        _save(state_path, state)
    seen = _version(latest_seen)
    if seen is not None and seen > cur:
        return _info(latest_seen, url)
    return None


def _save(path: Path, state: dict) -> None:
    try:
        write_json(path, {"last_check": state.get("last_check"), "latest_seen": state.get("latest_seen"),
                          "etag": state.get("etag")})
    except OSError:
        pass
