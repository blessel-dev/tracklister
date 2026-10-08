"""Headless set session: what the GUI calls to turn a reviewed table into a set folder.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

One engine process per set and per pass. After each pass every file is verified against its
row, converted for "CDJ antiguos" when needed, placed with its NN name through the journal, and
the set document is saved after every row. Lossy (MP3 320) passes only run for the rows the user
approved (asked at most once per run, before the first lossy pass).
"""
from __future__ import annotations

import os
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from tracklister import config
from tracklister.core.jsonio import read_json, write_json
from tracklister.core.layout import ORIGINALES, REPORT_TEMPLATE, TRACKLIST_TEMPLATE, set_doc_path
from tracklister.core.model import (
    QUARANTINE_DOUBTS, DuplicateChoice, LibraryEntry, PassRecord, ResultState, RowResult, SetDoc, SourceRef,
    TrackRow,
)
from tracklister.core.paths import AppPaths
from tracklister.core.settings import Settings
from tracklister.engine.cli import EngineJob, PASS_JSON
from tracklister.engine.credentials import Credentials
from tracklister.engine.csvwriter import write_engine_csv
from tracklister.engine.outputs import EngineEvent
from tracklister.engine.presets import FormatPass, Preset, build_preset, relaxed
from tracklister.engine.runner import EngineError, EngineRunner
from tracklister.library.index import LibraryIndex, row_key
from tracklister.organize.finalize import place_verified, rel_to_set, sync_names
from tracklister.organize.journal import Journal, same_file_content
from tracklister.organize.naming import pad_width, safe_component, track_filename, win_long
from tracklister.pipeline import report as report_mod
from tracklister.verify.convert import to_aiff_pcm
from tracklister.verify.verifier import verify_file

GOOD = (ResultState.VERIFICADO, ResultState.YA_EN_BIBLIOTECA)
MISSING = (ResultState.PENDIENTE, ResultState.EN_CURSO, ResultState.NO_ENCONTRADO,
           ResultState.NO_CUMPLE_FORMATO, ResultState.FALLIDA)
RETRYABLE = (ResultState.NO_ENCONTRADO, ResultState.FALLIDA, ResultState.NO_CUMPLE_FORMATO)

REASON_ES = {
    "NoSearchResults": "Soulseek no devolvio ningun resultado para esta busqueda.",
    "NoMatchingResults": "Hubo resultados, pero ninguno cumple los filtros (formato, titulo, artista o duracion).",
    "NoSuitableFileFound": "Hubo resultados, pero ninguno cumple los filtros (formato, titulo, artista o duracion).",
    "AllDownloadsFailed": "Se encontro, pero ninguna descarga termino (usuarios desconectados o sin respuesta).",
    "OutOfDownloadRetries": "Se encontro, pero se agotaron los reintentos de descarga.",
    "Cancelled": "Cancelado.",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass(frozen=True)
class SessionEvent:
    kind: str            # "pass_started" | "row_state" | "log" | "pass_finished" | "finished" | "error"
    uid: str | None = None
    state: ResultState | None = None
    message_es: str = ""
    done: int = 0
    total: int = 0


@dataclass(frozen=True)
class DuplicateHit:
    row: TrackRow
    entries: list[LibraryEntry] = field(default_factory=list)


def _merge_rows(old: SetDoc, rows: list[TrackRow]) -> None:
    """Re-run: carry the old uid (and so the old results) over to the same track in the new table."""
    by_key_pos = {(row_key(r), r.pos): r for r in old.rows}
    by_key: dict[str, list[TrackRow]] = {}
    for r in old.rows:
        by_key.setdefault(row_key(r), []).append(r)
    used: set[str] = set()
    for r in rows:
        k = row_key(r)
        cand = by_key_pos.get((k, r.pos))
        if cand is None or cand.uid in used:
            cand = next((c for c in by_key.get(k, []) if c.uid not in used), None)
        if cand is not None and (r.title or "").strip():
            r.uid = cand.uid
            used.add(cand.uid)
    keep = {r.uid for r in rows}
    old.results = {u: res for u, res in old.results.items() if u in keep}
    old.rows = list(rows)


class SetSession:
    def __init__(self, set_dir: Path, doc: SetDoc, preset: Preset, settings: Settings, paths: AppPaths):
        self.set_dir = Path(set_dir)
        self.doc = doc
        self.preset = preset
        self.settings = settings
        self.paths = paths
        self.journal = Journal(self.set_dir)
        self.engine_id: str | None = None

    # ---- construction ---------------------------------------------------------------------
    @classmethod
    def create(cls, name: str, rows: list[TrackRow], sources: list[SourceRef], settings: Settings,
               library_root: Path, paths: AppPaths) -> "SetSession":
        set_dir = Path(library_root) / safe_component(name)
        preset = build_preset(settings.preset_id, settings.custom_preset)
        doc_path = set_doc_path(set_dir)
        if doc_path.is_file():
            doc = SetDoc.from_dict(read_json(doc_path))
            _merge_rows(doc, list(rows))
            doc.sources = list(doc.sources) + [s for s in sources if s not in doc.sources]
        else:
            doc = SetDoc(set_id=uuid.uuid4().hex[:12], name=name, preset_id=str(preset.id), rows=list(rows),
                         sources=list(sources), created_at=_now(), app_version=config.APP_VERSION)
        doc.preset_id = str(preset.id)
        doc.preset_snapshot = preset.to_snapshot()
        for r in doc.rows:
            doc.results.setdefault(r.uid, RowResult(uid=r.uid, pos=r.pos))
            doc.results[r.uid].pos = r.pos
        s = cls(set_dir, doc, preset, settings, paths)
        s._refresh_missing_files()
        s.save()
        return s

    @classmethod
    def load(cls, set_dir: Path, settings: Settings, paths: AppPaths) -> "SetSession":
        doc = SetDoc.from_dict(read_json(set_doc_path(Path(set_dir))))
        preset = build_preset(doc.preset_id, settings.custom_preset)
        s = cls(Path(set_dir), doc, preset, settings, paths)
        s._refresh_missing_files()
        return s

    def save(self) -> None:
        self.doc.updated_at = _now()
        self.doc.app_version = config.APP_VERSION
        write_json(set_doc_path(self.set_dir), self.doc.to_dict())

    # ---- helpers --------------------------------------------------------------------------
    def _row(self, uid: str) -> TrackRow:
        return next(r for r in self.doc.rows if r.uid == uid)

    def _res(self, uid: str) -> RowResult:
        r = self.doc.results.get(uid)
        if r is None:
            r = self.doc.results[uid] = RowResult(uid=uid, pos=self._row(uid).pos)
        return r

    def _width(self) -> int:
        return pad_width(len(self.doc.rows))

    def _refresh_missing_files(self) -> None:
        """A good result whose file was deleted outside the app goes back to PENDIENTE."""
        for r in self.doc.rows:
            res = self._res(r.uid)
            if res.state in GOOD and (not res.file or not os.path.exists(win_long(self.set_dir / res.file))):
                res.state, res.file, res.doubt = ResultState.PENDIENTE, None, None
                res.reasons = ["El archivo ya no estaba en la carpeta: se vuelve a buscar."]

    def _set_state(self, uid: str, state: ResultState, on_event, msg: str = "", done: int = 0, total: int = 0):
        self._res(uid).state = state
        self._res(uid).updated_at = _now()
        if on_event:
            on_event(SessionEvent("row_state", uid, state, msg, done, total))

    def _quarantined(self, res: RowResult) -> bool:
        return res.state == ResultState.DUDOSO and res.doubt in QUARANTINE_DOUBTS

    def _needs_file(self, row: TrackRow) -> bool:
        res = self._res(row.uid)
        return row.download and (res.state in MISSING or self._quarantined(res))

    # ---- duplicates -----------------------------------------------------------------------
    def find_duplicates(self, library: LibraryIndex) -> list[DuplicateHit]:
        hits = []
        for r in sorted(self.doc.rows, key=lambda x: x.pos):
            if not r.download or not (r.title or "").strip() or self._res(r.uid).state in GOOD:
                continue
            entries = library.find(r, exclude_set_id=self.doc.set_id)
            if entries:
                hits.append(DuplicateHit(r, entries))
        return hits

    def apply_duplicate_choice(self, uid: str, choice: DuplicateChoice, entry: LibraryEntry | None) -> None:
        choice = DuplicateChoice(choice)
        self.doc.duplicate_choices[uid] = str(choice)
        if choice == DuplicateChoice.REUSE:
            if entry is None:
                raise ValueError("falta el archivo de la biblioteca")
            row, res = self._row(uid), self._res(uid)
            src = Path(entry.path)
            dst = self.set_dir / track_filename(row, src.suffix, self._width())
            if os.path.exists(win_long(dst)) and same_file_content(src, dst):
                real = dst
            else:
                bid = self.journal.begin("Usar el que ya tengo")
                real = self.journal.copy(bid, src, dst, uid=uid)
                self.journal.commit(bid)
            res.state, res.doubt, res.file = ResultState.YA_EN_BIBLIOTECA, None, rel_to_set(self.set_dir, real)
            res.format, res.duration_s = entry.format, entry.duration_s
            res.reasons = [f"Copiado de tu biblioteca: set '{entry.set_name}', pista {entry.pos}."]
            res.flags = ["reutilizado"]
            res.updated_at = _now()
        self.save()

    # ---- what to download -----------------------------------------------------------------
    def pending_rows(self) -> list[TrackRow]:
        return [r for r in sorted(self.doc.rows, key=lambda x: x.pos)
                if r.download and (r.title or "").strip()
                and self._res(r.uid).state in (ResultState.PENDIENTE, ResultState.EN_CURSO)
                and self.doc.duplicate_choices.get(r.uid) != str(DuplicateChoice.REUSE)]

    def lossy_candidates(self) -> list[TrackRow]:
        return [r for r in sorted(self.doc.rows, key=lambda x: x.pos)
                if r.download and (r.title or "").strip()
                and (self._res(r.uid).state in (ResultState.NO_ENCONTRADO, ResultState.NO_CUMPLE_FORMATO,
                                                ResultState.FALLIDA) or self._quarantined(self._res(r.uid)))]

    def approve_lossy(self, uids: Iterable[str]) -> None:
        for u in uids:
            if u not in self.doc.lossy_approved:
                self.doc.lossy_approved.append(u)
        self.save()

    # ---- running --------------------------------------------------------------------------
    def run(self, runner: EngineRunner, creds: Credentials, on_event: Callable[[SessionEvent], None],
            cancel: threading.Event, ask_lossy: Callable[[list[TrackRow]], set[str]]) -> None:
        for r in self.doc.rows:
            res = self._res(r.uid)
            if not r.download and res.state not in GOOD:
                res.state, res.doubt = ResultState.OMITIDA, None
                res.reasons = ["Fila desmarcada (ID o revisar): no se descarga."]
        self.save()
        todo = {r.uid for r in self.pending_rows()}
        self._passes(runner, creds, on_event, cancel, ask_lossy, todo, relaxed_mode=False)

    def retry_failed(self, runner: EngineRunner, creds: Credentials, on_event: Callable[[SessionEvent], None],
                     cancel: threading.Event) -> None:
        todo = {r.uid for r in self.doc.rows if r.download and (r.title or "").strip()
                and (self._res(r.uid).state in RETRYABLE + (ResultState.PENDIENTE, ResultState.EN_CURSO)
                     or self._quarantined(self._res(r.uid)))}
        self._passes(runner, creds, on_event, cancel, lambda rows: set(), todo, relaxed_mode=True)

    def _passes(self, runner, creds, on_event, cancel, ask_lossy, todo: set[str], relaxed_mode: bool) -> None:
        self.engine_id = runner.spec.engine_id
        asked = False
        total = len(todo)
        try:
            for p in self.preset.passes:
                if cancel.is_set():
                    break
                if p.lossy:
                    cands = [r for r in self.lossy_candidates() if r.uid in todo]
                    if not cands:
                        continue
                    if not asked and not relaxed_mode:
                        asked = True
                        approved = set(ask_lossy(cands) or set())
                        self.approve_lossy(u for u in approved if u in {c.uid for c in cands})
                    rows = [r for r in cands if r.uid in self.doc.lossy_approved]
                else:
                    rows = [r for r in sorted(self.doc.rows, key=lambda x: x.pos)
                            if r.uid in todo and self._needs_file(r)]
                if not rows:
                    continue
                stop = self._run_pass(relaxed(p) if relaxed_mode else p, rows, runner, creds, on_event, cancel,
                                      total)
                if stop:
                    on_event(SessionEvent("error", message_es=stop))
                    break
        except EngineError as e:
            for u in todo:
                if self._res(u).state in (ResultState.PENDIENTE, ResultState.EN_CURSO):
                    self._res(u).state = ResultState.FALLIDA
                    self._res(u).reasons = [e.msg_es]
            self.save()
            on_event(SessionEvent("error", message_es=e.msg_es))
        for u in todo:
            if self._res(u).state == ResultState.EN_CURSO:
                self._res(u).state = ResultState.PENDIENTE
        self.save()
        on_event(SessionEvent("finished", message_es="Listo.", done=total, total=total))

    def _run_pass(self, fmt: FormatPass, rows: list[TrackRow], runner: EngineRunner, creds: Credentials,
                  on_event: Callable[[SessionEvent], None], cancel: threading.Event, total: int) -> str | None:
        """Run one pass; returns a Spanish message when the remaining passes must not run."""
        index = len(self.doc.passes) + 1
        work = self.paths.work_dir / self.doc.set_id[:8] / f"p{index:02d}"
        if work.exists():
            shutil.rmtree(win_long(work), ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)
        manifest = write_engine_csv(rows, work / "input.csv")
        by_snum = {m.snum: m for m in manifest}
        started = _now()
        pass_doc = {"schema": "tracklister.pass/1", "set_id": self.doc.set_id, "index": index, "name": fmt.name,
                    "engine": runner.spec.engine_id, "items": [m.to_dict() for m in manifest], "argv_redacted": [],
                    "started_at": started, "finished_at": None, "exit_code": None}
        write_json(work / PASS_JSON, pass_doc)
        label = f"Pasada {index}: {fmt.name}" + ("" if fmt.strict_artist else " (relajada)")
        on_event(SessionEvent("pass_started", message_es=f"{label}: {len(rows)} pistas.", total=total))
        for r in rows:
            self._set_state(r.uid, ResultState.EN_CURSO, on_event, "En cola", total=total)
        self.save()

        def on_engine(ev: EngineEvent) -> None:
            uid = by_snum[ev.snum].uid if ev.snum in by_snum else None
            if ev.kind == "searching" and uid:
                on_event(SessionEvent("row_state", uid, ResultState.EN_CURSO, "Buscando...", total=total))
            elif ev.kind == "downloading" and uid:
                on_event(SessionEvent("row_state", uid, ResultState.EN_CURSO, "Descargando...", total=total))
            else:
                on_event(SessionEvent("log", uid, None, ev.text, total=total))

        job = EngineJob(work, fmt, any(m.length for m in manifest), int(self.settings.listen_port),
                        int(self.settings.concurrent_downloads), int(self.settings.searches_per_time),
                        int(self.settings.searches_renew_s))
        result = runner.run(job, manifest, creds, on_engine, cancel)
        self.doc.passes.append(PassRecord(index=index, name=fmt.name + ("" if fmt.strict_artist else "-relajada"),
                                          engine=runner.spec.engine_id, uids=[m.uid for m in manifest],
                                          started_at=started, finished_at=_now(), exit_code=result.exit_code,
                                          work_dir=str(work)))
        pass_doc.update(argv_redacted=result.argv_redacted, finished_at=_now(), exit_code=result.exit_code)
        write_json(work / PASS_JSON, pass_doc)

        bid = self.journal.begin(label)
        lossy_ok = "mp3" in fmt.formats
        width = self._width()
        for n, m in enumerate(manifest, start=1):
            row, res = self._row(m.uid), self._res(m.uid)
            outcome = result.outcomes.get(m.snum)
            res.attempts += 1
            res.pass_name = fmt.name
            had_quarantined = self._quarantined(res)
            if outcome is not None and outcome.file is not None:
                self._handle_file(row, res, outcome, fmt, lossy_ok, width, bid, had_quarantined)
            elif had_quarantined:
                res.reasons = res.reasons + [f"{label}: no aparecio nada mejor."]
            elif result.cancelled:
                res.state = ResultState.PENDIENTE
                res.reasons = ["Cancelado antes de terminar esta pista."]
            elif result.banned and (outcome is None or outcome.engine_state == "unknown"):
                res.state = ResultState.FALLIDA
                res.reasons = ["Soulseek corto la sesion antes de llegar a esta pista."]
            elif result.fatal_es and (outcome is None or outcome.engine_state == "unknown"):
                res.state, res.doubt, res.file = ResultState.FALLIDA, None, None
                res.reasons = [result.fatal_es]
            elif outcome is not None and outcome.engine_state == "not_found":
                res.state, res.doubt, res.file = ResultState.NO_ENCONTRADO, None, None
                res.reasons = [REASON_ES.get(outcome.reason or "", "No se encontro en Soulseek.") +
                               f" (formatos: {', '.join(fmt.formats)})"]
            else:
                reason = outcome.reason if outcome is not None else None
                res.state, res.doubt, res.file = ResultState.FALLIDA, None, None
                res.reasons = [REASON_ES.get(reason or "", f"El motor no pudo descargarla ({reason or 'sin motivo'}).")]
            res.updated_at = _now()
            on_event(SessionEvent("row_state", row.uid, res.state, "; ".join(res.reasons[:1]), n, len(manifest)))
            self.save()
        self.journal.commit(bid)
        shutil.rmtree(win_long(work / "in"), ignore_errors=True)
        on_event(SessionEvent("pass_finished", message_es=f"{label}: terminada.", total=total))
        if result.banned:
            return ("Soulseek corto la sesion (posible exceso de busquedas o la misma cuenta abierta en otro "
                    "programa). Espera 30 minutos y pulsa Reintentar fallos.")
        if result.fatal_es and not any(o.engine_state != "unknown" for o in result.outcomes.values()):
            return result.fatal_es
        return None

    def _handle_file(self, row: TrackRow, res: RowResult, outcome, fmt: FormatPass, lossy_ok: bool, width: int,
                     bid: str, had_quarantined: bool) -> None:
        verdict = verify_file(row, outcome.file, self.preset.accept, lossy_allowed=lossy_ok,
                              source_path_tail=outcome.source_path_tail,
                              duration_ok_s=int(self.settings.duration_ok_s),
                              duration_review_s=int(self.settings.duration_review_s),
                              spectral=bool(self.settings.spectral_check_enabled))
        info = verdict.info
        if verdict.state == ResultState.NO_CUMPLE_FORMATO:
            if had_quarantined:
                res.reasons = res.reasons + verdict.reasons_es
                return
            res.state, res.doubt, res.file, res.score = ResultState.NO_CUMPLE_FORMATO, None, None, None
            res.reasons, res.flags = list(verdict.reasons_es), list(verdict.flags)
            res.format, res.bitrate_kbps = info.container, info.bitrate_kbps
            res.source_path_tail, res.peer = outcome.source_path_tail, outcome.peer
            return
        reasons, flags = list(verdict.reasons_es), list(verdict.flags)
        src = Path(outcome.file)
        samplerate, bitdepth, container = info.samplerate, info.bitdepth, info.container
        original_rel = None
        if verdict.needs_conversion:
            acc = self.preset.accept
            conv = to_aiff_pcm(src, src.parent / "__convertido.aiff", max_samplerate=acc.max_samplerate or 48000,
                               max_bitdepth=acc.max_bitdepth or 24)
            orig_dst = self.set_dir / ORIGINALES / track_filename(row, src.suffix, width)
            real_orig = self.journal.move(bid, src, orig_dst, uid=row.uid)
            original_rel = rel_to_set(self.set_dir, real_orig)
            src = conv.dst
            samplerate, bitdepth, container = conv.samplerate, conv.bitdepth, "aiff"
            flags.append("convertido_aiff")
            reasons.append(conv.warning_es or "Convertido a AIFF para CDJ antiguos (mismo sample rate y bits). "
                                              "El original esta en _originales.")
        res.file = place_verified(self.set_dir, row, src, verdict, width, self.journal, bid)
        res.state, res.doubt, res.score = verdict.state, verdict.doubt, verdict.score
        res.reasons, res.flags = reasons, flags
        res.original_file = original_rel
        res.format, res.samplerate, res.bitdepth = container, samplerate, bitdepth
        res.duration_s = info.decoded_duration_s or info.duration_s
        res.bitrate_kbps = info.bitrate_kbps if container == "mp3" else None
        res.source_path_tail, res.peer = outcome.source_path_tail, outcome.peer

    # ---- finishing ------------------------------------------------------------------------
    def finalize(self, library: LibraryIndex) -> None:
        sync_names(self.set_dir, self.doc.rows, self.doc.results, self.journal)
        self.save()
        name = safe_component(self.doc.name)
        (self.set_dir / REPORT_TEMPLATE.format(name=name)).write_text(self.report_text(), encoding="utf-8")
        (self.set_dir / TRACKLIST_TEMPLATE.format(name=name)).write_text(self.tracklist_text(), encoding="utf-8")
        library.load()
        library.add_from_set(self.set_dir, self.doc)
        library.save()

    def report_text(self) -> str:
        return report_mod.report_text(self.doc, preset_label=self.preset.label_es, engine_id=self.engine_id)

    def tracklist_text(self) -> str:
        return report_mod.tracklist_text(self.doc)
