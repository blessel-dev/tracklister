"""Build-time constants. Owner: core (frozen during the parallel phase).

GITHUB_OWNER is the single constant that points the update check and the MusicBrainz
User-Agent at the published repo (https://github.com/blessel-dev/tracklister). A fork keeps
it; the release workflow then warns that the notice still looks at this repo.
Nothing here may contain personal data or credentials.
"""
from __future__ import annotations

from tracklister import __version__

APP_NAME = "Tracklister"                 # product name: never contains the creator's name
APP_DISPLAY_NAME = "Tracklister by Blessel"  # header text only
APP_VERSION = __version__

GITHUB_OWNER = "blessel-dev"             # owner of the public repo (update check, User-Agent)
GITHUB_REPO = "tracklister"


def project_url() -> str:
    return f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"


def releases_latest_api_url() -> str:
    return f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


def user_agent() -> str:
    """User-Agent for every HTTP request (MusicBrainz requires name/version/URL)."""
    return f"{APP_NAME}/{APP_VERSION} ( {project_url()} )"


KEYRING_SERVICE = "Tracklister/Soulseek"  # Windows Credential Manager target prefix
KEYRING_ACCOUNT_KEY = "__account__"       # entry whose password field stores the username

TRACKID_URL = "https://trackid.net"
DEFAULT_LISTEN_PORT = 49998
MUSICBRAINZ_MIN_INTERVAL_S = 1.0
UPDATE_CHECK_INTERVAL_S = 24 * 3600
