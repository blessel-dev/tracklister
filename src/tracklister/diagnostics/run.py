"""Diagnostico: search a few rows WITHOUT downloading and explain every candidate.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Search-only by default: one `--print json-all` engine process per row (keyed string input).
Downloads happen only when the user opted in; then a normal SetSession runs on a temporary set.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Callable

from rapidfuzz import fuzz

from tracklister.core.model import TrackRow
from tracklister.core.paths import AppPaths, app_paths
from tracklister.core.settings import Settings
from tracklister.core.textnorm import norm_key, split_title_version, versions_compatible
from tracklister.engine.cli import EngineJob
from tracklister.engine.credentials import Credentials
from tracklister.engine.csvwriter import ManifestItem, engine_artist, engine_title
from tracklister.engine.presets import FormatPass, build_preset
from tracklister.engine.runner import EngineError, EngineRunner
from tracklister.verify.identity import parse_name

MAX_CANDIDATES = 15


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


@dataclass
class DiagRow:
    row: TrackRow
    candidates: list[CandidateLine] = field(default_factory=list)
    error_es: str | None = None
    result_es: str | None = None     # only when the user asked to download


def keyed_input(row: TrackRow) -> str:
    s = f"artist={engine_artist(row)}, title={engine_title(row)}"
    if row.expected_duration_s:
        s += f", length={int(row.expected_duration_s)}"
    return s


def _ext(filename: str) -> str:
    base = filename.replace("/", "\\").rsplit("\\", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def judge_candidate(row: TrackRow, fmt: FormatPass, filename: str, duration: float | None,
                    bitrate: int | None) -> tuple[float, bool, str]:
    """Score a search result from its path alone (no audio yet) and say why it passes or not."""
    parts = [p for p in PureWindowsPath(filename.replace("/", "\\")).parts if p not in ("\\",)]
    name = parts[-1] if parts else filename
    parent = parts[-2] if len(parts) >= 2 else None
    artist, title_full = parse_name(name, parent)
    base, version = split_title_version(title_full)
    want_t, got_t = norm_key(row.title), norm_key(base)
    title = max(fuzz.ratio(want_t, got_t), fuzz.token_sort_ratio(want_t, got_t)) if want_t and got_t else 0.0
    art = 0.0
    hay = norm_key(" ".join(parts))
    for c in [row.artist_display] + list(row.artists or []):
        k = norm_key(c)
        if k:
            art = max(art, fuzz.token_set_ratio(k, norm_key(artist)), 100.0 if f" {k} " in f" {hay} " else 0.0)
    problems: list[str] = []
    ext = _ext(filename)
    if fmt.formats and ext not in fmt.formats:
        problems.append(f"formato {ext or '?'} no pedido en esta pasada")
    ok_v, why_v = versions_compatible(row.version, version)
    if not ok_v:
        problems.append(f"otra version ({why_v})")
    d = 0.75
    if row.expected_duration_s and duration:
        diff = abs(duration - row.expected_duration_s)
        d = 1.0 if diff <= 3 else (0.5 if diff <= 10 else 0.0)
        if diff > 10:
            problems.append(f"duracion {duration:.0f} s (se esperaban {row.expected_duration_s} s)")
    if fmt.min_bitrate and bitrate is not None and ext == "mp3" and bitrate < fmt.min_bitrate:
        problems.append(f"{bitrate} kbps (se piden {fmt.min_bitrate})")
    score = round(0.35 * art + 0.45 * title + 20 * d, 1)
    if art < 60:
        problems.append(f"artista distinto ({art:.0f}%)")
    if title < 70:
        problems.append(f"titulo distinto ({title:.0f}%)")
    if problems:
        return score, False, "rechazado: " + "; ".join(problems)
    if score < 80:
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
    for i, row in enumerate(chosen, start=1):
        if cancel.is_set():
            break
        d = DiagRow(row)
        out.append(d)
        work = Path(tempfile.mkdtemp(prefix=f"d{i:02d}-", dir=root))
        item = ManifestItem(1, row.uid, row.pos, engine_artist(row), engine_title(row),
                            int(row.expected_duration_s) if row.expected_duration_s else None)
        job = EngineJob(work, fmt, bool(item.length), int(settings.listen_port) if settings else 49998,
                        print_json_all=True, input_override=keyed_input(row))
        try:
            res = runner.run(job, [item], creds, on_event or (lambda e: None), cancel)
        except EngineError as e:
            d.error_es = e.msg_es
            break
        if res.banned:
            d.error_es = "Soulseek corto la sesion durante la busqueda."
            break
        arr = _parse_json_line(res.stdout_path)
        if arr is None:
            d.error_es = ("El motor no devolvio resultados (sin conexion, usuario o contrasena incorrectos, "
                          "o busqueda cancelada).")
        else:
            accepted_one = False
            for c in arr[:MAX_CANDIDATES]:
                user = (c.get("User") or {}).get("Username") or "?"
                f = c.get("File") or {}
                filename = f.get("Filename") or ""
                parts = [p for p in filename.replace("/", "\\").split("\\") if p]
                tail = "\\".join(parts[-2:])
                dur = f.get("Length")
                br = f.get("Bitrate")
                score, ok, why = judge_candidate(row, fmt, filename, float(dur) if dur else None, br)
                if ok and accepted_one:
                    why = "aceptable, pero el motor se queda con el primero que cumple"
                    ok = False
                if ok:
                    accepted_one = True
                    why = "elegido: " + why
                d.candidates.append(CandidateLine(user, tail, f.get("Size"), br, float(dur) if dur else None,
                                                  score, ok, why, f.get("SampleRate")))
            if not arr:
                d.error_es = "Sin resultados en Soulseek para esta busqueda."
        shutil.rmtree(work, ignore_errors=True)
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
