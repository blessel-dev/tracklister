"""THE engine adapter: one download plan (a pass) -> the exact CLI argv of the pinned engine.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Every option is explicit (never a config file). Golden tests in tests/engine/golden pin the argv
byte for byte per dialect. Facts with file:line references: third_party/engines/ENGINE-FACTS.md.

Never passed: -o (3.x output dir / 2.x offset), --strict-conditions, --fast-search, --profile.
The full argv contains the password: it is never logged; use redact_argv() for anything shown.

--desperate (1.0.1, R4; the same long flag in both engines, ENGINE-FACTS "Desperate mode") is only
for the last «Reintentar fallos» pass: when a row's searches find nothing, the engine searches again
without the length condition, then by title only and by artist only, each time keeping the strict
title and artist filters. It costs up to DESPERATE_SEARCHES_PER_ITEM searches per row (engine/runner).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from tracklister.engine.credentials import Credentials
from tracklister.engine.presets import FormatPass
from tracklister.engine.spec import EngineDialect, EngineSpec

NAME_FORMAT = "{snum}/{slsk-filename}"   # the engine appends the extension itself (ENGINE-FACTS 5)
REDACTED = "***"
_SECRET_FLAGS = ("--user", "--pass", "--username", "--password")

INPUT_CSV = "input.csv"
PASS_JSON = "pass.json"
INDEX_CSV = "index.csv"
ENGINE_LOG = "engine.log"
PLAYLIST = "playlist.m3u"
STDOUT_TXT = "stdout.txt"
IN_DIR = "in"


@dataclass(frozen=True)
class EngineJob:
    work_dir: Path                 # <work>/<set_id[:8]>/p<NN>/
    fmt: FormatPass
    has_lengths: bool              # any item has a Length -> add --length-tol
    listen_port: int
    concurrent: int = 4
    searches_per_time: int = 34
    searches_renew_s: int = 220
    print_json_all: bool = False   # Diagnostico search-only
    input_override: str | None = None  # Diagnostico keyed string "artist=A, title=T, length=L"
    banned_users: tuple[str, ...] = ()  # "Reintentar fallos": peers whose file went to _dudosos
    desperate: bool = False        # "Reintentar fallos", last pass: --desperate (R4)

    @property
    def out_dir(self) -> Path:
        return Path(self.work_dir) / IN_DIR

    @property
    def index_path(self) -> Path:
        return Path(self.work_dir) / INDEX_CSV

    @property
    def log_path(self) -> Path:
        return Path(self.work_dir) / ENGINE_LOG

    @property
    def playlist_path(self) -> Path:
        return Path(self.work_dir) / PLAYLIST

    @property
    def stdout_path(self) -> Path:
        return Path(self.work_dir) / STDOUT_TXT


def bannable_peer(name: str | None, own_username: str | None) -> bool:
    """Can this peer go in --banned-users? Both engines split the list on ',' and trim each name
    (3.x ConfigManager.cs:413,788-789; 2.x Config.cs:1284-1285), so a name with a comma or with
    spaces at either end could never match. The own account never goes in the list."""
    if not name or "," in name or name != name.strip():
        return False
    return name.casefold() != (own_username or "").casefold()


def _opt(flag: str, value: str) -> list[str]:
    """`--flag value`, or `--flag=value` when the value starts with '-'.

    Both engines expand a separate token like '-abc' into '-a -b -c' (3.x ConfigManager.cs
    NormalizeArgs, 2.x Config.cs:153-167); the attached form keeps such a value intact.
    """
    if value.startswith("-"):
        return [f"{flag}={value}"]
    return [flag, value]


def build_command(spec: EngineSpec, job: EngineJob, creds: Credentials) -> list[str]:
    """Full argv (argv_prefix + engine options) for one engine process."""
    d = spec.dialect
    w = Path(job.work_dir)
    fmt = job.fmt
    a: list[str] = []
    if job.input_override is not None:
        a += [job.input_override, "--input-type", "string"]
    else:
        a += [str(w / INPUT_CSV), "--input-type", "csv"]
    a += ["--no-config"]
    a += _opt("--user", creds.username)
    a += _opt("--pass", creds.password)
    a += ["--output-dir" if d == EngineDialect.SOCKSEEK3 else "-p", str(w / IN_DIR)]
    a += ["--name-format", NAME_FORMAT]
    a += ["--index-path", str(w / INDEX_CSV)]
    a += ["--log-file", str(w / ENGINE_LOG)]
    a += ["--no-progress"]
    a += ["--listen-port", str(int(job.listen_port))]
    a += ["--no-modify-share-count"]
    if job.input_override is None:
        a += ["--artist-col", "Artist", "--title-col", "Title", "--length-col", "Length",
              "--time-format", "s"]
    a += ["--format", ",".join(fmt.formats)]
    if fmt.min_bitrate:
        a += ["--min-bitrate", str(int(fmt.min_bitrate))]
    if fmt.max_samplerate:
        a += ["--max-samplerate", str(int(fmt.max_samplerate))]
    if job.has_lengths:
        a += ["--length-tol", str(int(fmt.length_tol_s))]
    if fmt.strict_title:
        a += ["--strict-title"]
    if fmt.strict_artist:
        a += ["--strict-artist"]
    banned = [u for u in dict.fromkeys(job.banned_users) if bannable_peer(u, creds.username)]
    if banned:
        a += _opt("--banned-users", ",".join(banned))
    if job.desperate:
        # a bare flag: the next token starts with '-', so both engines read it as true
        # (3.x ConfigManager.cs:307-311 with IsBoolLiteral :1265; 2.x Config.cs:707-711 getFlag)
        a += ["--desperate"]
    a += ["--no-skip-existing"]
    a += ["--write-playlist", "--playlist-path", str(w / PLAYLIST)]
    a += ["--concurrent-jobs" if d == EngineDialect.SOCKSEEK3 else "--concurrent-downloads",
          str(int(job.concurrent))]
    a += ["--searches-per-time", str(int(job.searches_per_time)),
          "--searches-renew-time", str(int(job.searches_renew_s))]
    if job.print_json_all:
        a += ["--print", "json-all"]
    return list(spec.argv_prefix) + a


def redact_argv(argv: Sequence[str]) -> list[str]:
    """Copy of argv with the values of --user/--pass (both forms) replaced by '***'."""
    out: list[str] = []
    hide_next = False
    for tok in argv:
        if hide_next:
            out.append(REDACTED)
            hide_next = False
            continue
        if tok in _SECRET_FLAGS:
            out.append(tok)
            hide_next = True
            continue
        flag, sep, _ = tok.partition("=")
        if sep and flag in _SECRET_FLAGS:
            out.append(f"{flag}={REDACTED}")
            continue
        out.append(tok)
    return out
