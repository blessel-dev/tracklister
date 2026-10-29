"""Diagnostico: search a few rows WITHOUT downloading and explain every candidate.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Search-only by default: one `--print json-all` engine process per row (keyed string input).
Downloads happen only when the user opted in; then a normal SetSession runs on a temporary set.

1.0.1 (R7): candidates that would print the same line (same peer, folder and file, size, bitrate,
duration and verdict) are listed once, with CandidateLine.repeats; his report showed one peer's file
three times. The results come from the engine's JSON as read before redaction (EngineRunResult.json_all,
audit r4-3 N7); the report censors the text afterwards.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Callable

from tracklister.core.aliases import MAX_VARIANTS
from tracklister.core.model import TrackRow
from tracklister.core.paths import AppPaths, app_paths
from tracklister.core.settings import Settings
from tracklister.core.textnorm import norm_key, split_title_version, versions_compatible
from tracklister.engine.cli import EngineJob
from tracklister.engine.credentials import Credentials
from tracklister.engine.csvwriter import ManifestItem, SearchQuery, engine_artist, engine_title, row_variants
from tracklister.engine.presets import FormatPass, build_preset
from tracklister.engine.runner import EngineError, EngineRunner
from tracklister.verify.identity import (
    artist_match, duration_confirms, file_identities, name_artist_fits, name_readings, row_artists, title_similarity,
    unconfirmed_es,
)
from tracklister.verify.verifier import ACCEPT_SCORE, HARD_DOUBT_MAX_SCORE

MAX_CANDIDATES = 15
NO_RESULTS_ES = "Sin resultados en Soulseek para esta búsqueda."


@dataclass
class CandidateLine:
    peer: str
    path_tail: str
    size: int | None
    bitrate: int | None
    duration_s: float | None
    score: float
    accepted: bool
    why_es: str
    samplerate: int | None = None
    repeats: int = 1                 # identical lines merged into this one (the report adds «(×N)»)


def mb_text(n: int | None) -> str:
    """A size as the report shows it: '41.0 MB', or '? MB'."""
    return f"{n / (1024 * 1024):.1f} MB" if n else "? MB"


def mmss_text(s: float | None) -> str:
    """A duration as the report shows it: '6:24', or '?'."""
    if not s:
        return "?"
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


@dataclass
class DiagRow:
    row: TrackRow
    candidates: list[CandidateLine] = field(default_factory=list)
    error_es: str | None = None
    result_es: str | None = None     # only when the user asked to download
    # Addendum 5 (R4): a row with no results is also searched with its other spellings, as the download does
    found_by: str | None = None      # «Artista - Título» of the spelling that found the candidates
    tried: list[str] = field(default_factory=list)   # spellings searched without results (the row's own first)


# Keys of the engines' keyed string (3.x Sockseek.Core/Extractors/String.cs ParseArgs, 2.x
# slsk-batchdl/Extractors/String.cs ParseTrackArg): case-sensitive, compared after trimming.
KEYED_KEYS = ("title", "artist", "length", "album", "artist-maybe-wrong", "album-track-count")


def keyed_value(value: str) -> str:
    """A value the engines read back intact from 'artist=..., title=...'.

    Both engines split the whole string on EVERY ',' and glue the pieces of a value back with ','
    ("Earth, Wind & Fire" survives), except a piece that reads '<key>=...': that one starts a new
    property ("Hey, title=X" would cut the title and replace it). Such a comma is escaped as a space;
    every other comma is kept. Soulseek searches by words, so the space changes nothing."""
    pieces = value.split(",")
    out = pieces[0]
    for piece in pieces[1:]:
        left, eq, _ = piece.partition("=")
        out += (" " if eq and left.strip() in KEYED_KEYS else ",") + piece
    return out.strip()


def keyed_input(row: TrackRow, query: SearchQuery | None = None) -> str:
    """The engines' keyed string for a row, or for another spelling of it (a search variant)."""
    artist = query.artist if query is not None else engine_artist(row)
    title = query.title if query is not None else engine_title(row)
    s = f"artist={keyed_value(artist)}, title={keyed_value(title)}"
    if row.expected_duration_s:
        s += f", length={int(row.expected_duration_s)}"
    return s


def query_text(row: TrackRow, query: SearchQuery | None = None) -> str:
    artist = query.artist if query is not None else engine_artist(row)
    title = query.title if query is not None else engine_title(row)
    return f"{artist} - {title}" if artist else title


def _ext(filename: str) -> str:
    base = filename.replace("/", "\\").rsplit("\\", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def judge_candidate(row: TrackRow, fmt: FormatPass, filename: str, duration: float | None,
                    bitrate: int | None) -> tuple[float, bool, str]:
    """Score a search result from its path alone (no audio yet) and say why it passes or not. A name that only
    fits after leaving words out needs the duration the result reports to confirm it (Addendum 10)."""
    parts = [p for p in PureWindowsPath(filename.replace("/", "\\")).parts if p not in ("\\",)]
    name = parts[-1] if parts else filename
    parent = parts[-2] if len(parts) >= 2 else None
    first = name_readings(name, parent)[0]           # the first reading of the name (parse_name)
    artist, title_full = first.artist, first.title
    base, version = split_title_version(title_full)
    # Addendum 10: what that reading left out of the name (a search result has no tags), as in the download
    guess = unconfirmed_es(row, file_identities(name, parent, None, None)[0])
    # same title/artist rules as the verification (verify.identity): other numbers in the title are
    # another track, and a one-word partial artist does not count
    # (a leading number is a track number only at the start of the name: barrido CL-01)
    title, numbers_ok = title_similarity(row.title, base, at_name_start=first.from_folder or not first.artist)
    # the artist must match word by word: 'Adam Port' is not 'Adam Beyer' (audit round 3, B1)
    m = artist_match(row_artists(row), artist)
    art, same_artist = m.score, m.same
    # audit v101-1 review, B1-R: an artist part cut out of the name at a glued hyphen or of a scene name is
    # the row's only when it is exactly one of its names (or a credit with a joiner word), as in the
    # download: 'Adam Beyer Space-Time.flac' is not «Adam Beyer - Time»
    if first.cut and not name_artist_fits(row_artists(row), artist):
        same_artist = False
    folders = {norm_key(p) for p in parts[:-1]}
    # a folder named exactly like the artist ("Music\Fjaak\Live\03 Spirit.flac") counts only when the file
    # name itself gives no artist, as in the download (plan D10): 'Adam Beyer\Adam Port - Rush.flac' is
    # Adam Port's file
    name_has_no_artist = first.from_folder or not artist
    if name_has_no_artist and any(norm_key(c) in folders for c in row_artists(row) if norm_key(c)):
        art, same_artist = 100.0, True
    problems: list[str] = []
    ext = _ext(filename)
    if fmt.formats and ext not in fmt.formats:
        problems.append(f"formato {ext or '?'} no pedido en esta pasada")
    ok_v, why_v = versions_compatible(row.version, version)
    if not ok_v:
        problems.append(f"otra versión ({why_v})")
    d = 0.75
    if row.expected_duration_s and duration:
        diff = abs(duration - row.expected_duration_s)
        d = 1.0 if diff <= 3 else (0.5 if diff <= 10 else 0.0)
        if diff > 10:
            problems.append(f"duración {duration:.0f} s (se esperaban {row.expected_duration_s} s)")
    if fmt.min_bitrate and bitrate is not None and ext == "mp3" and bitrate < fmt.min_bitrate:
        problems.append(f"{bitrate} kbps (se piden {fmt.min_bitrate})")
    score = round(0.35 * art + 0.45 * title + 20 * d, 1)
    if art < 60:
        problems.append(f"artista distinto ({art:.0f}%)")
    elif not same_artist:
        problems.append(f"otro artista con un nombre parecido ('{artist}', {art:.0f}%)")
    if title < 70:
        problems.append(f"título distinto ({title:.0f}%)" if numbers_ok else "título con otros números (otra pista)")
    # the name only fits after leaving words out (or cutting without ' - '): the duration the result reports
    # must confirm it, within 3 s of the row's, as the verification asks of the file (Addendum 10)
    unconfirmed = bool(guess) and art >= 60 and same_artist and title >= 70 \
        and not duration_confirms(row.expected_duration_s, duration)
    if unconfirmed:
        problems.append(f"{guess}, sin una duración que lo confirme")
    identity_doubt = not ok_v or art < 60 or not same_artist or title < 70 or d == 0.0 or unconfirmed
    if identity_doubt:
        score = min(score, HARD_DOUBT_MAX_SCORE)    # same rule as the verifier (DECISIONES N.6)
    if problems:
        return score, False, "rechazado: " + "; ".join(problems)
    if score < ACCEPT_SCORE:
        return score, False, f"rechazado: confianza {score:.0f}/100"
    return score, True, f"aceptable: confianza {score:.0f}/100"


def _parse_json_line(stdout_path: Path) -> list[dict] | None:
    if not stdout_path.is_file():
        return None
    arr = None
    for line in stdout_path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("["):
            try:
                v = json.loads(s)
            except ValueError:
                continue
            if isinstance(v, list):
                arr = v
    return arr


def _search(row: TrackRow, query: SearchQuery | None, i: int, k: int, root: Path, fmt: FormatPass,
            settings: Settings | None, runner: EngineRunner, creds: Credentials, on_event: Callable | None,
            cancel: threading.Event) -> tuple[list | None, str | None, bool]:
    """One search-only engine process for a row (or one of its spellings): (results, error, fatal).
    results None = the engine gave no answer; fatal = stop the whole Diagnóstico (engine missing, ban)."""
    work = Path(tempfile.mkdtemp(prefix=f"d{i:02d}{'v' + str(k) if k else ''}-", dir=root))
    try:
        artist = query.artist if query is not None else engine_artist(row)
        title = query.title if query is not None else engine_title(row)
        item = ManifestItem(1, row.uid, row.pos, artist, title,
                            int(row.expected_duration_s) if row.expected_duration_s else None)
        job = EngineJob(work, fmt, bool(item.length), int(settings.listen_port) if settings else 49998,
                        print_json_all=True, input_override=keyed_input(row, query))
        try:
            res = runner.run(job, [item], creds, on_event or (lambda e: None), cancel)
        except EngineError as e:
            return None, e.msg_es, True
        if res.banned:
            return None, "Soulseek cortó la sesión durante la búsqueda.", True
        arr = res.json_all if res.json_all is not None else _parse_json_line(res.stdout_path)
        if arr is None:
            return None, ("El motor no devolvió resultados (sin conexión, usuario o contraseña incorrectos, "
                          "o búsqueda cancelada)."), False
        return [c for c in arr if isinstance(c, dict)], None, False
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _judge_all(d: DiagRow, row: TrackRow, fmt: FormatPass, arr: list[dict]) -> None:
    """Judge every result against the ROW (also when another spelling found it: its aliases count)."""
    accepted_one = False
    shown: dict[tuple, CandidateLine] = {}
    for c in arr:
        user = str((c.get("User") or {}).get("Username") or "?")
        f = c.get("File") or {}
        filename = str(f.get("Filename") or "")
        parts = [p for p in filename.replace("/", "\\").split("\\") if p]
        tail = "\\".join(parts[-2:])
        dur = f.get("Length")
        dur = float(dur) if dur else None
        br = f.get("Bitrate")
        score, ok, why = judge_candidate(row, fmt, filename, dur, br)
        # what the line will show, before 'elegido'/'aceptable, pero...': the same file of the same peer
        # listed again (another share folder, the same folder twice) is one line with «(×N)»
        key = (user, tail, mb_text(f.get("Size")), br, mmss_text(dur), round(score), ok, why)
        if key in shown:
            shown[key].repeats += 1
            continue
        if len(d.candidates) >= MAX_CANDIDATES:
            continue
        if ok and accepted_one:
            why = "aceptable, pero el motor se queda con el primero que cumple"
            ok = False
        if ok:
            accepted_one = True
            why = "elegido: " + why
        shown[key] = CandidateLine(user, tail, f.get("Size"), br, dur, score, ok, why, f.get("SampleRate"))
        d.candidates.append(shown[key])


def run_diagnostic(rows: list[TrackRow], runner: EngineRunner, creds: Credentials, *, download: bool = False,
                   max_rows: int = 5, on_event: Callable | None = None, cancel: threading.Event | None = None,
                   fmt: FormatPass | None = None, settings: Settings | None = None,
                   paths: AppPaths | None = None) -> list[DiagRow]:
    paths = paths or app_paths()
    cancel = cancel or threading.Event()
    fmt = fmt or build_preset((settings.preset_id if settings else "lossless"),
                              settings.custom_preset if settings else None).passes[0]
    chosen = [r for r in sorted(rows, key=lambda x: x.pos) if r.download and (r.title or "").strip()][:max_rows]
    out: list[DiagRow] = []
    root = paths.work_dir / "diagnostico"
    root.mkdir(parents=True, exist_ok=True)
    stop = False
    for i, row in enumerate(chosen, start=1):
        if cancel.is_set():
            break
        d = DiagRow(row)
        out.append(d)
        # the row as written, then (Addendum 5) its other spellings while nothing is found: the same
        # row_variants() the download uses, at most MAX_VARIANTS more searches, each inside the search
        # budget (runner.run waits for it). No --desperate here: the report says «Reintentar fallos» runs it.
        spellings: list[SearchQuery | None] = [None] + list(row_variants(row)[:MAX_VARIANTS])
        for k, query in enumerate(spellings):
            if cancel.is_set():
                break
            arr, error_es, fatal = _search(row, query, i, k, root, fmt, settings, runner, creds, on_event, cancel)
            if fatal:
                d.error_es = error_es
                stop = True
                break
            if arr is None:
                d.error_es = error_es
                break
            if arr:
                d.error_es = None
                d.found_by = query_text(row, query) if query is not None else None
                _judge_all(d, row, fmt, arr)
                break
            d.tried.append(query_text(row, query))
            d.error_es = NO_RESULTS_ES
        if stop:
            break
    if download and chosen and not cancel.is_set() and settings is not None:
        from tracklister.pipeline.session import SetSession
        tmp_root = Path(tempfile.mkdtemp(prefix="diag-set-", dir=root))
        s = SetSession.create("Diagnostico", [TrackRow.from_dict(r.to_dict()) for r in chosen], [], settings,
                              tmp_root, paths)
        s.run(runner, creds, on_event or (lambda e: None), cancel, lambda rs: set())
        for d in out:
            res = s.doc.results.get(d.row.uid)
            if res is not None:
                d.result_es = f"{res.state}: " + "; ".join(res.reasons[:2])
    return out
