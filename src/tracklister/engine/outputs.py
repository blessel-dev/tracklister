"""Reading what an engine pass left behind: progress lines, index, playlist and in/<snum>/ files.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Ground truth is the files on disk under in/<snum>/ (one folder per CSV item, see
ENGINE-FACTS.md item 5). The index, the playlist and stdout only add reasons, the peer and the
Soulseek path tail. Line formats and codes: ENGINE-FACTS.md items 1 and 2.
"""
from __future__ import annotations

import csv
import io
import os
import re
from dataclasses import dataclass
from pathlib import Path

from tracklister.core.textnorm import norm_key
from tracklister.engine.cli import EngineJob
from tracklister.engine.csvwriter import ManifestItem
from tracklister.engine.spec import EngineDialect

INCOMPLETE_SUFFIXES = (".incomplete", ".part", ".tmp")
STAGING_DIRS = (".sockseek-staging",)


@dataclass(frozen=True)
class EngineEvent:
    kind: str            # "searching" | "downloading" | "succeeded" | "failed" | "not_found" | "ban" | "log"
    snum: int | None
    text: str            # already redacted
    subject: str = ""    # the part after the status label ("Artist - Title: peer\\..\\path" in 3.x)


@dataclass(frozen=True)
class ItemOutcome:
    snum: int
    file: Path | None
    engine_state: str    # "downloaded" | "not_found" | "failed" | "unknown"
    reason: str | None   # engine reason name, e.g. "NoSearchResults"; Spanish text is made later
    source_path_tail: str | None
    peer: str | None


# ---- progress lines -------------------------------------------------------------------------

_V3 = re.compile(r"^\[(\d+)\] SongJob: ([a-z ()A-Z]+?)(?: \[([^\]]*)\])?: (.*)$")
_V3_NOT_FOUND_REASONS = {"no search results", "no matching results"}
_V2 = re.compile(r"^(Searching|Initialize|Succeeded|Not found|TimedOut|Errored|Rejected|Cancelled|Aborted|Failed)"
                 r":\s+(.*)$")
_BAN = re.compile(r"kicked|banned|\bban\b", re.IGNORECASE)


def parse_progress_line(dialect: EngineDialect, line: str) -> EngineEvent | None:
    text = line.rstrip("\r\n")
    if not text.strip():
        return None

    def other() -> EngineEvent:
        # Only non-song lines can be a server kick/ban (a track title may contain "ban").
        if _BAN.search(text) and ("soulseek" in text.lower() or "server" in text.lower()):
            return EngineEvent("ban", None, text)
        return EngineEvent("log", None, text)

    if dialect == EngineDialect.SOCKSEEK3:
        m = _V3.match(text)
        if not m:
            return other()
        status, reason, subject = m.group(2).strip().lower(), (m.group(3) or "").strip().lower(), m.group(4)
        if status == "searching":
            kind = "searching"
        elif status in ("downloading", "initialising", "queued (r)", "queued (l)"):
            kind = "downloading"
        elif status in ("succeeded", "already exists"):
            kind = "succeeded"
        elif status == "not found" or (status == "failed" and reason in _V3_NOT_FOUND_REASONS):
            kind = "not_found"
        elif status in ("failed", "timed out", "cancelled", "partial"):
            kind = "failed"
        else:
            return EngineEvent("log", None, text)
        return EngineEvent(kind, None, text, subject)
    m = _V2.match(text)
    if not m:
        return other()
    label, subject = m.group(1), m.group(2)
    kind = {"Searching": "searching", "Initialize": "downloading", "Succeeded": "succeeded",
            "Not found": "not_found"}.get(label, "failed")
    return EngineEvent(kind, None, text, subject)


_FATAL = (
    (re.compile(r"login failed|failed to ensure soulseek connection|missing soulseek (username|password)|"
                r"no soulseek username or password", re.IGNORECASE),
     "No se pudo entrar en Soulseek: revisa tu usuario y tu contrasena en Ajustes (y que la cuenta no "
     "este abierta en otro programa)."),
    (re.compile(r"address already in use|only one usage of each socket address|failed to bind", re.IGNORECASE),
     "El puerto de escucha esta ocupado por otro programa: cambia el puerto en Ajustes."),
    (re.compile(r"^input error:|unknown argument", re.IGNORECASE),
     "El motor no acepto las opciones de Tracklister: reinstala Tracklister o cambia de motor en Ajustes."),
)


def fatal_reason_es(line: str) -> str | None:
    """Spanish explanation for an engine line that means the whole run cannot work.

    Indented lines are skipped: they are the track preview ("  Artist - Title") or error details,
    and a track may well be called "Login Failed"."""
    if not line or line[:1].isspace():
        return None
    for pat, msg in _FATAL:
        if pat.search(line):
            return msg
    return None


def query_text(item: ManifestItem) -> str:
    return f"{item.artist} - {item.title}"


def match_snum(subject: str, manifest: list[ManifestItem]) -> int | None:
    """Map an event subject back to its CSV item by the exact 'Artist - Title' the app sent."""
    best: tuple[int, int] | None = None
    low = subject.lower()
    for it in manifest:
        q = query_text(it).lower()
        if low == q or low.startswith(q + " (") or low.startswith(q + ":") or low.startswith(q + " ["):
            if best is None or len(q) > best[1]:
                best = (it.snum, len(q))
    return best[0] if best else None


# ---- index / playlist -----------------------------------------------------------------------

_STATE_V3 = {0: "Pending", 1: "Done", 2: "Failed", 3: "AlreadyExists", 4: "NotFoundLastTime"}
_STATE_V2 = {0: "Initial", 1: "Downloaded", 2: "Failed", 3: "AlreadyExists", 4: "NotFoundLastTime"}
_REASON_V3 = {0: "None", 1: "InvalidSearchString", 2: "OutOfDownloadRetries", 3: "NoMatchingResults",
              4: "AllDownloadsFailed", 5: "Other", 6: "ExtractionFailed", 7: "Cancelled",
              8: "ChildJobsFailed", 9: "NoSearchResults", 10: "NoMatchingResults"}
_REASON_V2 = {0: "None", 1: "InvalidSearchString", 2: "OutOfDownloadRetries", 3: "NoSuitableFileFound",
              4: "AllDownloadsFailed", 5: "Other"}
NOT_FOUND_REASONS = frozenset({"NoSearchResults", "NoMatchingResults", "NoSuitableFileFound"})


def _int(s: str, default: int = 0) -> int:
    try:
        return int(str(s).strip())
    except ValueError:
        return default


def parse_index(dialect: EngineDialect, index_path: Path) -> list[dict]:
    """Rows of the engine index as dicts with decoded state/reason names."""
    p = Path(index_path)
    if not p.is_file():
        return []
    text = p.read_text(encoding="utf-8-sig", errors="replace")
    states = _STATE_V3 if dialect == EngineDialect.SOCKSEEK3 else _STATE_V2
    reasons = _REASON_V3 if dialect == EngineDialect.SOCKSEEK3 else _REASON_V2
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        if not r or not any((v or "").strip() for v in r.values()):
            continue
        fp = (r.get("filepath") or "").strip()
        rel = None
        if fp:
            fp = fp.replace("\\", "/")
            rel = fp[2:] if fp.startswith("./") else fp
        length = _int(r.get("length", "-1"), -1)
        state, reason = _int(r.get("state", "0")), _int(r.get("failurereason", "0"))
        out.append({"filepath": rel, "artist": r.get("artist") or "", "album": r.get("album") or "",
                    "title": r.get("title") or "", "length": None if length < 0 else length,
                    "state": state, "state_name": states.get(state, str(state)),
                    "reason": reason, "reason_name": reasons.get(reason, str(reason))})
    return out


_FAIL = re.compile(r"^#FAIL: (.*) \[([^\]]+)\]\s*$")


def parse_playlist_failures(path: Path) -> dict[str, str]:
    """'Artist - Title' (lower) -> reason name, from the m3u #FAIL lines."""
    p = Path(path)
    if not p.is_file():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _FAIL.match(line.strip())
        if m:
            out[m.group(1).lower()] = m.group(2)
    return out


# ---- stdout: peer and path tail of each download --------------------------------------------

def _split_display(path_text: str) -> tuple[str | None, list[str]]:
    """'peer\\..\\Music\\Fjaak\\x.flac [20s/...]' -> ('peer', ['Music','Fjaak','x.flac'])."""
    s = re.sub(r"\s+\[[^\]]*\]\s*$", "", path_text.strip())
    parts = [x for x in s.replace("/", "\\").split("\\") if x and x != ".."]
    if len(parts) < 2:
        return None, parts
    return parts[0], parts[1:]


def _download_lines(dialect: EngineDialect, stdout_path: Path) -> list[tuple[str, str | None, list[str]]]:
    """(query subject or '', peer, path parts) for every downloading/succeeded line."""
    p = Path(stdout_path)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        ev = parse_progress_line(dialect, line)
        if ev is None or ev.kind not in ("downloading", "succeeded"):
            continue
        if dialect == EngineDialect.SOCKSEEK3:
            # "Artist - Title: peer\..\path" (the query itself may contain ': ')
            idx = ev.subject.rfind(": ")
            if idx < 0:
                continue
            query, disp = ev.subject[:idx], ev.subject[idx + 2:]
        else:
            query, disp = "", ev.subject
        peer, parts = _split_display(disp)
        if parts:
            out.append((query, peer, parts))
    return out


def _files_in(d: Path) -> list[Path]:
    """Files in one in/<snum>/ folder; long names come back in \\\\?\\ form so they stay openable."""
    try:
        with os.scandir(_long(d)) as it:
            found = [(e.stat().st_size, e.name, e.path) for e in it
                     if e.is_file() and not e.name.lower().endswith(INCOMPLETE_SUFFIXES)]
    except OSError:
        return []
    found.sort(key=lambda x: (-x[0], x[1]))
    return [Path(p) for _, _, p in found]


def _long(p: Path) -> str:
    s = os.path.abspath(str(p))
    if os.name == "nt" and not s.startswith("\\\\?\\"):
        return "\\\\?\\" + s
    return s


def collect_outputs(job: EngineJob, manifest: list[ManifestItem], dialect: EngineDialect) -> dict[int, ItemOutcome]:
    idx = parse_index(dialect, job.index_path)
    by_query: dict[tuple[str, str], dict] = {}
    for r in idx:
        by_query.setdefault((norm_key(r["artist"], drop_original=False), norm_key(r["title"], drop_original=False)), r)
    fails = parse_playlist_failures(job.playlist_path)
    downloads = _download_lines(dialect, job.stdout_path)
    out: dict[int, ItemOutcome] = {}
    for it in manifest:
        files = _files_in(job.out_dir / str(it.snum))
        q = query_text(it)
        if files:
            f = files[0]
            peer = tail = None
            hits = [d for d in downloads if d[2][-1].lower() == f.name.lower()]
            exact = [d for d in hits if d[0].lower() == q.lower()]
            pick = (exact or hits)
            if pick:
                peer = pick[-1][1]
                tail = "\\".join(pick[-1][2][-2:])
            out[it.snum] = ItemOutcome(it.snum, f, "downloaded", None, tail, peer)
            continue
        r = by_query.get((norm_key(it.artist, drop_original=False), norm_key(it.title, drop_original=False)))
        reason = None
        if r is not None and r["state"] in (2, 4):
            reason = r["reason_name"] if r["reason"] else r["state_name"]
        elif q.lower() in fails:
            reason = fails[q.lower()]
        if reason is None:
            out[it.snum] = ItemOutcome(it.snum, None, "unknown", None, None, None)
        elif reason in NOT_FOUND_REASONS or reason == "NotFoundLastTime":
            out[it.snum] = ItemOutcome(it.snum, None, "not_found", reason, None, None)
        else:
            out[it.snum] = ItemOutcome(it.snum, None, "failed", reason, None, None)
    return out
