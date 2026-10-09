"""Headless set session: what the GUI calls to turn a reviewed table into a set folder.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

One engine process per set and per pass. After each pass every file is verified against its
row, converted for "CDJ antiguos" when needed, placed with its NN name through the journal, and
the set document is saved after every row. Lossy (MP3 320) passes only run for the rows the user
approved (each row is asked about once per set, before the first lossy pass).
"""
from __future__ import annotations

import logging
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
from tracklister.core.layout import DUDOSOS, ORIGINALES, REPORT_TEMPLATE, TRACKLIST_TEMPLATE, set_doc_path
from tracklister.core.model import (
    QUARANTINE_DOUBTS, DuplicateChoice, LibraryEntry, PassRecord, ResultState, RowResult, SetDoc, SourceRef,
    TrackRow,
)
from tracklister.core.paths import AppPaths
from tracklister.core.settings import Settings
from tracklister.engine.cli import EngineJob, PASS_JSON, bannable_peer
from tracklister.engine.credentials import Credentials
from tracklister.engine.csvwriter import write_engine_csv
from tracklister.engine.outputs import EngineEvent
from tracklister.engine.presets import FormatPass, Preset, build_preset, relaxed
from tracklister.engine.runner import EngineError, EngineRunner
from tracklister.library.index import CARRIED_FLAGS, LibraryIndex, row_key
from tracklister.organize.finalize import place_verified, rel_to_set, stray_audio_files, sync_names
from tracklister.organize.journal import Journal, same_file_content
from tracklister.organize.naming import pad_width, safe_component, track_filename, win_long
from tracklister.pipeline import report as report_mod
from tracklister.verify.audioinfo import AudioInfo, probe
from tracklister.verify.convert import to_aiff_pcm
from tracklister.verify.quality import QualityCheck, check_quality
from tracklister.verify.verifier import verify_file

log = logging.getLogger("tracklister.pipeline")

GOOD = (ResultState.VERIFICADO, ResultState.YA_EN_BIBLIOTECA)
MISSING = (ResultState.PENDIENTE, ResultState.EN_CURSO, ResultState.NO_ENCONTRADO,
           ResultState.NO_CUMPLE_FORMATO, ResultState.FALLIDA)
RETRYABLE = (ResultState.NO_ENCONTRADO, ResultState.FALLIDA, ResultState.NO_CUMPLE_FORMATO)

NOT_RETRIED_ES = (f"No se ha vuelto a buscar: no se sabe de qué usuario de Soulseek vino este archivo, así que "
                  f"volvería el mismo. Revisa el archivo en {DUDOSOS}, o corrige artista, título o versión en "
                  "la tabla de Nuevo set y vuelve a descargar.")
NOT_RETRIED_FORMAT_ES = ("No se ha vuelto a buscar: no se sabe de qué usuario de Soulseek vino el archivo que no "
                         "cumplía el formato, así que volvería el mismo. Corrige artista, título o versión en la "
                         "tabla de Nuevo set y vuelve a descargar.")
REUSE_LABEL = "Usar el que ya tengo"
REUSE_CONVERT_FAILED_ES = ("No se pudo convertir a AIFF para CDJ antiguos el archivo de tu biblioteca ({err}): "
                           "se descarga de nuevo.")
REUSE_NOT_FIT_ES = "El archivo de tu biblioteca ya no vale para el formato de este set: se descarga de nuevo."
REUSE_COPY_FAILED_ES = "No se pudo copiar a este set el archivo de tu biblioteca ({err}): se descarga de nuevo."
SAME_FILE_ES = (f"Ha vuelto el mismo archivo que ya estaba en {DUDOSOS} (idéntico byte a byte): por ahora no "
                "hay en Soulseek otra copia mejor de esta pista.")
CONVERT_FAILED_ES = ("No se pudo convertir a AIFF para CDJ antiguos ({err}): el archivo está dañado o incompleto. "
                     "No se pone en el set; pulsa «Reintentar fallos» para volver a descargarla.")


def _row_error_es(e: BaseException) -> str:
    """Spanish reason for an unexpected error while processing ONE downloaded file."""
    if isinstance(e, OSError):
        what = f"No se pudo mover o guardar el archivo descargado ({e.strerror or type(e).__name__})."
    else:
        what = f"Error inesperado al comprobar el archivo descargado ({type(e).__name__})."
    return what + " Pulsa «Reintentar fallos» para volver a intentarlo."

REASON_ES = {
    "NoSearchResults": "Soulseek no devolvió ningún resultado para esta búsqueda.",
    "NoMatchingResults": "Hubo resultados, pero ninguno cumple los filtros (formato, título, artista o duración).",
    "NoSuitableFileFound": "Hubo resultados, pero ninguno cumple los filtros (formato, título, artista o duración).",
    "AllDownloadsFailed": "Se encontró, pero ninguna descarga terminó (usuarios desconectados o sin respuesta).",
    "OutOfDownloadRetries": "Se encontró, pero se agotaron los reintentos de descarga.",
    "Cancelled": "Cancelado.",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _write_text(path: Path, text: str) -> None:
    """A UTF-8 text file in the set folder, also past Windows' 260-character MAX_PATH on a PC whose
    LongPathsEnabled is 0 (the default): the path goes through win_long()."""
    with open(win_long(path), "w", encoding="utf-8") as f:
        f.write(text)


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
               library_root: Path, paths: AppPaths, *, persist: bool = True) -> "SetSession":
        """persist=False writes nothing yet (no set folder): the GUI first asks about the tracks already
        in the library, and only saves when the user answered every question (save())."""
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
        if persist:
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
    def _mp3_allowed(self, row: TrackRow) -> bool:
        """May this row end up as an MP3 in this set? When MP3 is one of the preset's own formats (Solo MP3
        320, Personalizado with MP3), or when the user already said yes to MP3 for this row in the
        once-per-set question (Lossless / CDJ antiguos: MP3 only if there is no lossless, after asking)."""
        return any("mp3" in p.formats and (not p.lossy or row.uid in self.doc.lossy_approved)
                   for p in self.preset.passes)

    def library_check(self, row: TrackRow, entry: LibraryEntry) -> tuple[AudioInfo, QualityCheck] | None:
        """Can this library file go into THIS set? The same format rule as a download with this set's
        preset, on the file's headers (it was fully verified when it entered the library). None = it
        cannot (a FLAC in "Solo MP3 320", an MP3 in "Lossless" before the MP3 question, an MP3 under the
        preset's kbps...). needs_conversion = "CDJ antiguos" turns it into AIFF, like a downloaded FLAC."""
        try:
            info = probe(Path(win_long(entry.path)), decode=False)
        except Exception as e:  # noqa: BLE001 - an unreadable library file is simply not offered
            log.warning("library file unreadable (%s): not offered", type(e).__name__)
            return None
        quality = check_quality(info, self.preset.accept, lossy_allowed=self._mp3_allowed(row))
        return (info, quality) if quality.ok else None

    def find_duplicates(self, library: LibraryIndex) -> list[DuplicateHit]:
        """Tracks of this set already in the library, each with ONLY the copies its preset accepts."""
        hits = []
        for r in sorted(self.doc.rows, key=lambda x: x.pos):
            if not r.download or not (r.title or "").strip() or self._res(r.uid).state in GOOD:
                continue
            entries = [e for e in library.find(r, exclude_set_id=self.doc.set_id)
                       if self.library_check(r, e) is not None]
            if entries:
                hits.append(DuplicateHit(r, entries))
        return hits

    def apply_duplicate_choice(self, uid: str, choice: DuplicateChoice, entry: LibraryEntry | None) -> None:
        choice = DuplicateChoice(choice)
        self.doc.duplicate_choices[uid] = str(choice)
        if choice == DuplicateChoice.REUSE:
            if entry is None:
                raise ValueError("falta el archivo de la biblioteca")
            self._reuse(self._row(uid), self._res(uid), entry)
        self.save()

    def _download_instead(self, row: TrackRow, res: RowResult, reason_es: str) -> None:
        self.doc.duplicate_choices[row.uid] = str(DuplicateChoice.DOWNLOAD)
        res.reasons = [reason_es]
        res.updated_at = _now()

    def _reuse_copy_failed(self, row: TrackRow, res: RowResult, bid: str | None, e: OSError) -> None:
        """Audit round 3, N2: the library file could not be copied into this set (locked, gone, a full
        disk...). Only this row is affected: what its batch already copied is reverted (no half file,
        no stray copy in _originales) and the track is downloaded instead."""
        log.warning("row %s: library file not copied into the set: %s", row.pos, type(e).__name__)
        if bid is not None:
            try:
                self.journal.discard(bid)
            except (OSError, KeyError) as e2:
                log.warning("row %s: the failed copy could not be reverted: %s", row.pos, type(e2).__name__)
        self._download_instead(row, res, REUSE_COPY_FAILED_ES.format(err=e.strerror or type(e).__name__))

    def _reuse(self, row: TrackRow, res: RowResult, entry: LibraryEntry) -> None:
        """'Usar el que ya tengo': copy the library file into this set with its own NN name.

        Under "CDJ antiguos" a FLAC (or a WAV/AIFF over 48 kHz/24 bits, AIFF-C, float) becomes AIFF
        exactly like a download, and a copy of the original goes to _originales; the library file itself
        is never touched. A file that no longer fits the preset, cannot be converted, or cannot be
        copied into the set (an OSError: round 3, N2) is downloaded again instead (the row stays pending,
        with the reason); the other rows and the run are not affected."""
        check = self.library_check(row, entry)
        if check is None:
            self._download_instead(row, res, REUSE_NOT_FIT_ES)
            return
        info, quality = check
        src = Path(entry.path)
        width = self._width()
        reasons = [f"Copiado de tu biblioteca: set '{entry.set_name}', pista {entry.pos}."]
        flags = ["reutilizado"]
        original_rel = None
        container, samplerate, bitdepth = info.container, info.samplerate, info.bitdepth
        if quality.needs_conversion:
            tmp = self.paths.work_dir / self.doc.set_id[:8] / "reuse"
            try:
                tmp.mkdir(parents=True, exist_ok=True)
                local = tmp / f"{row.uid}{src.suffix.lower()}"
                shutil.copyfile(win_long(src), win_long(local))      # short path: libsndfile always opens it
                acc = self.preset.accept
                conv = to_aiff_pcm(local, tmp / f"{row.uid}.aiff", max_samplerate=acc.max_samplerate or 48000,
                                   max_bitdepth=acc.max_bitdepth or 24)
            except Exception as e:  # noqa: BLE001 - a damaged library file: download the track instead
                log.warning("row %s: library file not converted to AIFF: %s", row.pos, type(e).__name__)
                shutil.rmtree(win_long(tmp), ignore_errors=True)
                self._download_instead(row, res, REUSE_CONVERT_FAILED_ES.format(err=type(e).__name__))
                return
            bid = None
            try:
                bid = self.journal.begin(REUSE_LABEL)
                orig_dst = self.set_dir / ORIGINALES / track_filename(row, src.suffix, width)
                if os.path.exists(win_long(orig_dst)) and same_file_content(src, orig_dst):
                    real_orig = orig_dst
                else:
                    real_orig = self.journal.copy(bid, src, orig_dst, uid=row.uid)
                real = self.journal.copy(bid, conv.dst, self.set_dir / track_filename(row, ".aiff", width),
                                         uid=row.uid)
                self.journal.commit(bid)
            except OSError as e:
                self._reuse_copy_failed(row, res, bid, e)
                return
            finally:
                shutil.rmtree(win_long(tmp), ignore_errors=True)
            original_rel = rel_to_set(self.set_dir, real_orig)
            container, samplerate, bitdepth = "aiff", conv.samplerate, conv.bitdepth
            flags += ["convertido_aiff"] + [f for f in quality.flags if f in ("reducido_48k_24b", "aiff_c_o_float")]
            reasons.append(conv.warning_es or f"Convertido a AIFF para CDJ antiguos (mismo sample rate y bits). "
                                              f"El original está en {ORIGINALES}.")
        else:
            dst = self.set_dir / track_filename(row, src.suffix, width)
            bid = None
            try:
                if os.path.exists(win_long(dst)) and same_file_content(src, dst):
                    real = dst
                else:
                    bid = self.journal.begin(REUSE_LABEL)
                    real = self.journal.copy(bid, src, dst, uid=row.uid)
                    self.journal.commit(bid)
            except OSError as e:
                self._reuse_copy_failed(row, res, bid, e)
                return
        res.state, res.doubt, res.score = ResultState.YA_EN_BIBLIOTECA, None, None
        res.file, res.original_file = rel_to_set(self.set_dir, real), original_rel
        res.format, res.duration_s = container, entry.duration_s
        res.samplerate, res.bitdepth = samplerate, bitdepth
        res.bitrate_kbps = info.bitrate_kbps if container == "mp3" else None
        carried = [f for f in CARRIED_FLAGS if f in (entry.flags or [])]
        if "posible_falso_lossless" in carried:
            reasons.append(f"Marca que trae del set '{entry.set_name}': posible lossless falso (sacado de "
                           "un MP3). Escúchalo antes de pincharlo.")
        res.reasons, res.flags = reasons, flags + carried
        res.updated_at = _now()

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
        self._passes(runner, creds, on_event, cancel, ask_lossy, [(todo, ())], relaxed_mode=False)

    def _rejected(self, res: RowResult) -> bool:
        """Its last file was rejected: in _dudosos (other song, version or duration) or not in format."""
        return self._quarantined(res) or res.state == ResultState.NO_CUMPLE_FORMATO

    def retry_failed(self, runner: EngineRunner, creds: Credentials, on_event: Callable[[SessionEvent], None],
                     cancel: threading.Event) -> None:
        """'Reintentar fallos': relaxed passes (no --strict-artist) for the rows that are missing.

        A row whose last file was rejected (in _dudosos, or "no cumple formato": an MP3 VBR or under
        320 kbps, a FLAC that could not be converted...) goes in a relaxed pass with --banned-users <the
        peers that gave its rejected files>: otherwise the engine would pick the same first candidate and
        bring the same file back. Those peers stay banned for the row in later retries too, whatever its
        state. A rejected row whose peer is unknown (or cannot be banned) is not sent again: it keeps its
        state, with a Spanish reason saying why and what to do."""
        normal: set[str] = set()
        with_bans: set[str] = set()
        banned: list[str] = []
        for r in self.doc.rows:
            if not (r.download and (r.title or "").strip()):
                continue
            res = self._res(r.uid)
            rejected = self._rejected(res)
            if not (rejected or res.state in RETRYABLE + (ResultState.PENDIENTE, ResultState.EN_CURSO)):
                continue
            if rejected and not bannable_peer(res.peer, creds.username):
                note = NOT_RETRIED_ES if self._quarantined(res) else NOT_RETRIED_FORMAT_ES
                if note not in res.reasons:
                    res.reasons = res.reasons + [note]
                    on_event(SessionEvent("row_state", r.uid, res.state, note, 1, 1))
                continue
            peers = [p for p in dict.fromkeys(res.rejected_peers + ([res.peer] if rejected else []))
                     if bannable_peer(p, creds.username)]
            if peers:
                with_bans.add(r.uid)
                banned += [p for p in peers if p not in banned]
            else:
                normal.add(r.uid)
        self.save()
        groups = [(normal, ())] if normal else []
        if with_bans:
            groups.append((with_bans, tuple(banned)))
        self._passes(runner, creds, on_event, cancel, lambda rows: set(), groups, relaxed_mode=True)

    def _passes(self, runner, creds, on_event, cancel, ask_lossy, groups: list[tuple[set[str], tuple[str, ...]]],
                relaxed_mode: bool) -> None:
        """Every preset pass, one engine process per group of rows (a group = rows + the peers banned for
        them). Rows are never left 'en curso', whatever happens."""
        self.engine_id = runner.spec.engine_id
        asked = False
        todo: set[str] = set().union(*(uids for uids, _ in groups)) if groups else set()
        total = len(todo)
        try:
            stop = None
            for p in self.preset.passes:
                if cancel.is_set() or stop:
                    break
                for uids, banned in groups:
                    if cancel.is_set():
                        break
                    if p.lossy:
                        cands = [r for r in self.lossy_candidates() if r.uid in uids]
                        if not cands:
                            continue
                        # asked once per SET: a row already shown in the question (approved or not) is
                        # never asked about again, also in a later run of the same set
                        new = [r for r in cands
                               if r.uid not in self.doc.lossy_approved and r.uid not in self.doc.lossy_asked]
                        if new and not asked and not relaxed_mode:
                            asked = True
                            approved = set(ask_lossy(new) or set())
                            if cancel.is_set():          # closing the question by cancelling is not an answer
                                break
                            self.doc.lossy_asked += [r.uid for r in new if r.uid not in self.doc.lossy_asked]
                            self.approve_lossy(u for u in approved if u in {c.uid for c in new})
                        rows = [r for r in cands if r.uid in self.doc.lossy_approved]
                    else:
                        rows = [r for r in sorted(self.doc.rows, key=lambda x: x.pos)
                                if r.uid in uids and self._needs_file(r)]
                    if not rows:
                        continue
                    stop = self._run_pass(relaxed(p) if relaxed_mode else p, rows, runner, creds, on_event, cancel,
                                          total, banned)
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
        finally:
            for u in todo:
                if self._res(u).state == ResultState.EN_CURSO:
                    self._res(u).state = ResultState.PENDIENTE
            self.save()
        on_event(SessionEvent("finished", message_es="Listo.", done=total, total=total))

    def _run_pass(self, fmt: FormatPass, rows: list[TrackRow], runner: EngineRunner, creds: Credentials,
                  on_event: Callable[[SessionEvent], None], cancel: threading.Event, total: int,
                  banned: tuple[str, ...] = ()) -> str | None:
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
        if banned:
            label += " sin los usuarios de los archivos rechazados"
        on_event(SessionEvent("pass_started", message_es=f"{label}: {len(rows)} pistas.", total=total))
        was_quarantined = {r.uid for r in rows if self._quarantined(self._res(r.uid))}
        for r in rows:
            if r.uid in was_quarantined:
                # its file in _dudosos and its doubt stay until a better file arrives (also if the pass is
                # cancelled or fails): only the screen shows it "en curso"
                on_event(SessionEvent("row_state", r.uid, ResultState.EN_CURSO, "En cola", total=total))
            else:
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
                        int(self.settings.searches_renew_s), banned_users=tuple(banned))
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
        try:
            for n, m in enumerate(manifest, start=1):
                row, res = self._row(m.uid), self._res(m.uid)
                outcome = result.outcomes.get(m.snum)
                res.attempts += 1
                res.pass_name = fmt.name
                had_quarantined = m.uid in was_quarantined
                try:
                    self._settle_row(row, res, outcome, result, fmt, label, lossy_ok, width, bid, had_quarantined)
                except Exception as e:  # noqa: BLE001 - one bad file marks its row, never stops the pass
                    log.exception("row %s: processing the downloaded file failed", row.pos)
                    if had_quarantined:
                        res.reasons = res.reasons + [_row_error_es(e)]
                    else:
                        res.state, res.doubt, res.file, res.score = ResultState.FALLIDA, None, None, None
                        res.reasons = [_row_error_es(e)]
                res.updated_at = _now()
                on_event(SessionEvent("row_state", row.uid, res.state, "; ".join(res.reasons[:1]), n, len(manifest)))
                self.save()
        finally:
            self.journal.commit(bid)
        shutil.rmtree(win_long(work / "in"), ignore_errors=True)
        on_event(SessionEvent("pass_finished", message_es=f"{label}: terminada.", total=total))
        if result.banned:
            return ("Soulseek cortó la sesión (posible exceso de búsquedas o la misma cuenta abierta en otro "
                    "programa). Espera 30 minutos y pulsa «Reintentar fallos».")
        if result.fatal_es and not any(o.engine_state != "unknown" for o in result.outcomes.values()):
            return result.fatal_es
        return None

    def _settle_row(self, row: TrackRow, res: RowResult, outcome, result, fmt: FormatPass, label: str,
                    lossy_ok: bool, width: int, bid: str, had_quarantined: bool) -> None:
        """The outcome of one row after a pass: its file verified and placed, or why there is none.
        A row whose file is in _dudosos keeps it (and its doubt) unless a new file arrives."""
        if outcome is not None and outcome.file is not None:
            self._handle_file(row, res, outcome, fmt, lossy_ok, width, bid, had_quarantined)
        elif had_quarantined:
            if result.cancelled:
                note = "Cancelado antes de terminar esta pista."
            elif (result.banned or result.fatal_es) and (outcome is None or outcome.engine_state == "unknown"):
                note = result.fatal_es or "Soulseek cortó la sesión antes de llegar a esta pista."
            else:
                note = f"{label}: no apareció nada mejor."
            res.reasons = res.reasons + [note]
        elif result.cancelled:
            res.state = ResultState.PENDIENTE
            res.reasons = ["Cancelado antes de terminar esta pista."]
        elif result.banned and (outcome is None or outcome.engine_state == "unknown"):
            res.state = ResultState.FALLIDA
            res.reasons = ["Soulseek cortó la sesión antes de llegar a esta pista."]
        elif result.fatal_es and (outcome is None or outcome.engine_state == "unknown"):
            res.state, res.doubt, res.file = ResultState.FALLIDA, None, None
            res.reasons = [result.fatal_es]
        elif outcome is not None and outcome.engine_state == "not_found":
            res.state, res.doubt, res.file = ResultState.NO_ENCONTRADO, None, None
            res.reasons = [REASON_ES.get(outcome.reason or "", "No se encontró en Soulseek.") +
                           f" (formatos: {', '.join(fmt.formats)})"]
        else:
            reason = outcome.reason if outcome is not None else None
            res.state, res.doubt, res.file = ResultState.FALLIDA, None, None
            res.reasons = [REASON_ES.get(reason or "", f"El motor no pudo descargarla ({reason or 'sin motivo'}).")]

    def _handle_file(self, row: TrackRow, res: RowResult, outcome, fmt: FormatPass, lossy_ok: bool, width: int,
                     bid: str, had_quarantined: bool) -> None:
        src = Path(outcome.file)
        # a retry that brings back exactly the file already in _dudosos must say so (DECISIONES R.1)
        came_back = bool(had_quarantined and res.file and same_file_content(src, self.set_dir / res.file))
        verdict = verify_file(row, src, self.preset.accept, lossy_allowed=lossy_ok,
                              source_path_tail=outcome.source_path_tail,
                              duration_ok_s=int(self.settings.duration_ok_s),
                              duration_review_s=int(self.settings.duration_review_s),
                              spectral=bool(self.settings.spectral_check_enabled))
        info = verdict.info
        if verdict.state == ResultState.NO_CUMPLE_FORMATO:
            self._not_in_format(res, outcome, verdict.reasons_es, verdict.flags, info, had_quarantined)
            return
        reasons, flags = list(verdict.reasons_es), list(verdict.flags)
        samplerate, bitdepth, container = info.samplerate, info.bitdepth, info.container
        original_rel = None
        quarantine = verdict.doubt in QUARANTINE_DOUBTS
        if verdict.needs_conversion and not quarantine:
            acc = self.preset.accept
            try:
                conv = to_aiff_pcm(src, src.parent / "__convertido.aiff",
                                   max_samplerate=acc.max_samplerate or 48000, max_bitdepth=acc.max_bitdepth or 24)
            except Exception as e:  # noqa: BLE001 - libsndfile/OS errors of a damaged download
                log.warning("row %s: AIFF conversion failed: %s", row.pos, type(e).__name__)
                self._not_in_format(res, outcome, [CONVERT_FAILED_ES.format(err=type(e).__name__)],
                                    verdict.flags + ["conversion_fallida"], info, had_quarantined)
                return
            orig_dst = self.set_dir / ORIGINALES / track_filename(row, src.suffix, width)
            real_orig = self.journal.move(bid, src, orig_dst, uid=row.uid)
            original_rel = rel_to_set(self.set_dir, real_orig)
            src = conv.dst
            samplerate, bitdepth, container = conv.samplerate, conv.bitdepth, "aiff"
            flags.append("convertido_aiff")
            reasons.append(conv.warning_es or "Convertido a AIFF para CDJ antiguos (mismo sample rate y bits). "
                                              "El original está en _originales.")
        elif verdict.needs_conversion:
            # identity/version/duration doubt (truncated files too): the download goes as it is to _dudosos,
            # never converted (a damaged FLAC would not convert anyway) and with no copy in _originales
            flags.append("sin_convertir")
            reasons.append(f"No se convierte a AIFF: es dudoso y va tal cual a {DUDOSOS}.")
        res.file = place_verified(self.set_dir, row, src, verdict, width, self.journal, bid)
        if came_back:
            reasons.append(SAME_FILE_ES)
        res.state, res.doubt, res.score = verdict.state, verdict.doubt, verdict.score
        res.reasons, res.flags = reasons, flags
        res.original_file = original_rel
        res.format, res.samplerate, res.bitdepth = container, samplerate, bitdepth
        res.duration_s = info.decoded_duration_s or info.duration_s
        res.bitrate_kbps = info.bitrate_kbps if container == "mp3" else None
        res.source_path_tail, res.peer = outcome.source_path_tail, outcome.peer
        if quarantine and outcome.peer and outcome.peer not in res.rejected_peers:
            res.rejected_peers = res.rejected_peers + [outcome.peer]

    @staticmethod
    def _not_in_format(res: RowResult, outcome, reasons_es: list[str], flags: list[str], info,
                       had_quarantined: bool) -> None:
        """The download does not meet the preset (or could not be converted): it is not placed. Its peer
        is remembered, so 'Reintentar fallos' bans it (--banned-users) instead of getting the same file."""
        if outcome.peer and outcome.peer not in res.rejected_peers:
            res.rejected_peers = res.rejected_peers + [outcome.peer]
        if had_quarantined:
            res.reasons = res.reasons + list(reasons_es)
            return
        res.state, res.doubt, res.file, res.score = ResultState.NO_CUMPLE_FORMATO, None, None, None
        res.reasons, res.flags = list(reasons_es), list(flags)
        res.format, res.bitrate_kbps = info.container, info.bitrate_kbps
        res.source_path_tail, res.peer = outcome.source_path_tail, outcome.peer

    # ---- finishing ------------------------------------------------------------------------
    def finalize(self, library: LibraryIndex) -> None:
        sync_names(self.set_dir, self.doc.rows, self.doc.results, self.journal)
        self.save()
        name = safe_component(self.doc.name)
        # next to the music: a long set name takes these past Windows' 260 characters (win_long)
        _write_text(self.set_dir / REPORT_TEMPLATE.format(name=name), self.report_text())
        _write_text(self.set_dir / TRACKLIST_TEMPLATE.format(name=name), self.tracklist_text())
        library.load()
        library.add_from_set(self.set_dir, self.doc)
        library.save()

    def report_text(self) -> str:
        return report_mod.report_text(self.doc, preset_label=self.preset.label_es, engine_id=self.engine_id,
                                      stray_files=stray_audio_files(self.set_dir, self.doc.results.values()))

    def tracklist_text(self) -> str:
        return report_mod.tracklist_text(self.doc)
