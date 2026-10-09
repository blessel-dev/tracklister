"""What did the user drop or paste? A file, a link or a block of text.

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from tracklister.inputs.mapping import guess_mapping
from tracklister.inputs.tabular import CSV_EXTS, TABLE_EXTS, XLS_EXTS, TableError, read_table
from tracklister.inputs.trackid import is_trackid_table


class InputKind(StrEnum):
    TRACKID_CSV = "trackid_csv"
    TABLE = "tabla"
    XLS_UNSUPPORTED = "xls"
    YOUTUBE = "youtube"
    SOUNDCLOUD = "soundcloud"
    TRACKID_URL = "trackid_url"
    PASTE_ONLY_URL = "pegar_texto_url"   # 1001tracklists, mixesdb
    OTHER_URL = "otra_url"
    TEXT = "texto"


YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")
SOUNDCLOUD_HOSTS = ("soundcloud.com", "snd.sc")
TRACKID_HOSTS = ("trackid.net",)
PASTE_ONLY_HOSTS = ("1001tracklists.com", "mixesdb.com")
_URL = re.compile(r"^(?:https?://|www\.)\S+$", re.I)
_BARE_HOST = re.compile(r"^(?:[\w-]+\.)+(?:com|net|be|sc|org)(?:/\S*)?$", re.I)


def _host_in(host: str, domains: tuple[str, ...]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in domains)


def normalize_url(s: str) -> str | None:
    """'www.youtube.com/watch?v=x' -> 'https://www.youtube.com/watch?v=x'; None if not a link."""
    s = s.strip().strip("<>\"'")
    if not s or any(c.isspace() for c in s):
        return None
    if _URL.match(s) or _BARE_HOST.match(s):
        return s if re.match(r"(?i)^https?://", s) else "https://" + s
    return None


def url_kind(url: str) -> InputKind:
    host = urlparse(url).hostname or ""
    if _host_in(host, YOUTUBE_HOSTS):
        return InputKind.YOUTUBE
    if _host_in(host, SOUNDCLOUD_HOSTS):
        return InputKind.SOUNDCLOUD
    if _host_in(host, TRACKID_HOSTS):
        return InputKind.TRACKID_URL
    if _host_in(host, PASTE_ONLY_HOSTS):
        return InputKind.PASTE_ONLY_URL
    return InputKind.OTHER_URL


def as_path(source: str | Path) -> Path | None:
    """A dropped/pasted file reference -> Path (quotes and file:// URLs accepted); None otherwise."""
    if isinstance(source, Path):
        return source
    s = source.strip().strip('"').strip("'")
    if not s or "\n" in s or re.match(r"(?i)^(?:https?://|www\.)", s):
        return None
    if s.lower().startswith("file:"):
        parsed = urlparse(s)
        return Path(url2pathname(unquote(parsed.path)))
    if re.match(r"^[a-zA-Z]:[\\/]|^\\\\", s) or Path(s).suffix.lower() in TABLE_EXTS + XLS_EXTS:
        return Path(s)
    return None


def file_kind(path: Path) -> InputKind:
    """By extension and, for tables, by the header (trackid.net columns or not)."""
    ext = path.suffix.lower()
    if ext in XLS_EXTS:
        return InputKind.XLS_UNSUPPORTED
    if ext not in TABLE_EXTS or not path.is_file():
        return InputKind.TABLE           # the importer explains what is wrong
    try:
        t = read_table(path)
    except TableError:
        return InputKind.TABLE
    if is_trackid_table(t):
        return InputKind.TRACKID_CSV
    if ext in CSV_EXTS and ext != ".csv":
        # a .txt is a table only with 2+ columns that have recognisable names
        if len(t.headers) < 2 or not guess_mapping(t.headers).is_usable():
            return InputKind.TEXT
    return InputKind.TABLE


def detect(source: str | Path) -> InputKind:
    p = as_path(source)
    if p is not None:
        return file_kind(p)
    url = normalize_url(source)
    if url is not None:
        return url_kind(url)
    return InputKind.TEXT
