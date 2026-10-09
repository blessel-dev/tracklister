"""Shared data model and on-disk JSON shapes. Owner: core (FROZEN during the parallel phase).

Every branch (inputs, engine/verify/organize/library/pipeline, gui) imports these types.
A branch that needs a change writes the request to its FEAT notes instead of editing this
file; the integration step applies it. All dataclasses serialise with to_dict()/from_dict()
to plain JSON (UTF-8, ensure_ascii=False) through tracklister.core.jsonio.

Normalised row fields follow 02-fuentes-tracklists.md section 4 ("Fila normalizada interna"),
plus `uid` (stable link between a row and its results across edits and re-runs).
"""
from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

SET_SCHEMA = "tracklister.set/1"
LIBRARY_SCHEMA = "tracklister.library/1"
JOURNAL_SCHEMA = "tracklister.journal/1"
SETTINGS_SCHEMA = "tracklister.settings/1"


class RowStatus(StrEnum):
    """Input-review status of a row (02 section 4)."""
    OK = "ok"
    REVISAR = "revisar"            # partial parse; unchecked unless enrichment confirms
    ID = "id"                      # unidentified track or "ID (hueco)"; unchecked
    YA_EN_BIBLIOTECA = "ya_en_biblioteca"
    DESCARGADA = "descargada"
    FALLIDA = "fallida"


class ResultState(StrEnum):
    """Per-row outcome of a download run (brief section 10 + addendum 6)."""
    PENDIENTE = "pendiente"
    EN_CURSO = "en_curso"
    VERIFICADO = "verificado"
    DUDOSO = "dudoso"                      # see RowResult.doubt for where the file is
    NO_ENCONTRADO = "no_encontrado"
    NO_CUMPLE_FORMATO = "no_cumple_formato"  # downloaded but fails the preset (e.g. MP3 < 320)
    FALLIDA = "fallida"                    # engine error, peer timeout, ban, cancelled
    YA_EN_BIBLIOTECA = "ya_en_biblioteca"  # copied from a previous set ("Usar el que ya tengo")
    OMITIDA = "omitida"                    # download=False (ID rows, unchecked rows)


class DoubtKind(StrEnum):
    IDENTIDAD = "identidad"   # other song / artist          -> file goes to _dudosos\
    VERSION = "version"       # other version (remix vs original, radio edit) -> _dudosos\
    DURACION = "duracion"     # duration off by > review tolerance             -> _dudosos\
    ESPECTRO = "espectro"     # possible fake lossless only -> stays in the set folder, marked
    REVISAR = "revisar"       # score 50-79 without identity failure -> stays in the set, marked


QUARANTINE_DOUBTS = frozenset({DoubtKind.IDENTIDAD, DoubtKind.VERSION, DoubtKind.DURACION})


class VersionKind(StrEnum):
    ORIGINAL = "original"
    EXTENDED = "extended"
    REMIX = "remix"
    RADIO_EDIT = "radio_edit"
    EDIT = "edit"
    DUB = "dub"
    LIVE = "live"
    OTHER = "other"


class DuplicateChoice(StrEnum):
    REUSE = "reuse"        # "Usar el que ya tengo (copiar a este set)"
    DOWNLOAD = "download"  # "Descargar de nuevo en este set"


def new_uid() -> str:
    return uuid.uuid4().hex[:12]


def _from_dict(cls, data: dict[str, Any]):
    """Build a dataclass from a dict, ignoring unknown keys (forward compatible)."""
    names = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class TrackIds:
    isrc: str | None = None
    itunes: str | None = None
    deezer: str | None = None
    mbid: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "TrackIds":
        return _from_dict(cls, d or {})


@dataclass
class TrackRow:
    """One track of a tracklist. `pos` is the ROW INDEX (1..n, table order, ID rows included)
    and is the ONLY source of the NN file-name prefix."""
    pos: int
    title: str = ""                        # base title, no version, no label: "Dust 1"
    artists: list[str] = field(default_factory=list)   # ["Blasha", "Allatt"]
    artist_display: str = ""               # "Blasha & Allatt"
    version: str | None = None             # "Kai Van Dongen Remix"; None = original
    feat: str | None = None
    label: str | None = None
    ts_start: int | None = None            # seconds into the set
    ts_end: int | None = None
    expected_duration_s: int | None = None # from enrichment
    ids: TrackIds = field(default_factory=TrackIds)
    source: str = "texto"                  # "trackid_csv", "youtube_comment:@x", "texto", "tabla", ...
    source_url: str | None = None
    confidence: float = 0.7                # 0-1, rules in 02 section 4
    is_id: bool = False
    status: RowStatus = RowStatus.OK
    notes: list[str] = field(default_factory=list)
    raw: str = ""                          # original line, for auditing
    download: bool = True                  # checkbox in the review table
    enrich_source: str | None = None       # "itunes" | "deezer" | "musicbrainz" | None
    uid: str = field(default_factory=new_uid)

    # ---- derived helpers (pure; no I/O) ----
    @property
    def search_artist(self) -> str:
        """Primary artist sent to the engine (full list is kept for verification)."""
        return self.artists[0] if self.artists else self.artist_display

    @property
    def title_with_version(self) -> str:
        return f"{self.title} ({self.version})" if self.version else self.title

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["status"] = str(self.status)
        d["ids"] = self.ids.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TrackRow":
        row = _from_dict(cls, d)
        row.ids = TrackIds.from_dict(d.get("ids"))
        row.status = RowStatus(d.get("status", "ok"))
        row.artists = list(d.get("artists") or [])
        row.notes = list(d.get("notes") or [])
        return row


@dataclass
class RowResult:
    """Outcome for one row in one set. `file` is relative to the set folder."""
    uid: str
    pos: int
    state: ResultState = ResultState.PENDIENTE
    doubt: DoubtKind | None = None
    score: int | None = None               # 0-100 confidence score of the accepted file
    reasons: list[str] = field(default_factory=list)   # Spanish, user-facing
    flags: list[str] = field(default_factory=list)     # machine tags: "posible_falso_lossless",
    #   "convertido_aiff", "reducido_48k_24b", "sin_tags", "truncado", "mp3_vbr", ...
    file: str | None = None                # e.g. "03 - DJ Dextro - Covil dos Abutres.flac" or "_dudosos/..."
    original_file: str | None = None       # e.g. "_originales/03 - ....flac" (CDJ preset)
    source_path_tail: str | None = None    # last 2 path parts on Soulseek (local only)
    peer: str | None = None                # Soulseek peer name (LOCAL ONLY; redacted in Diagnostico)
    format: str | None = None              # real container: flac|wav|aiff|mp3|...
    duration_s: float | None = None
    bitrate_kbps: int | None = None
    samplerate: int | None = None
    bitdepth: int | None = None
    pass_name: str | None = None
    attempts: int = 0
    updated_at: str | None = None          # ISO-8601 local time
    rejected_peers: list[str] = field(default_factory=list)   # peers whose file went to _dudosos (LOCAL
    #   ONLY): "Reintentar fallos" passes them to the engine as --banned-users

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["state"] = str(self.state)
        d["doubt"] = str(self.doubt) if self.doubt else None
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RowResult":
        r = _from_dict(cls, d)
        r.state = ResultState(d.get("state", "pendiente"))
        r.doubt = DoubtKind(d["doubt"]) if d.get("doubt") else None
        r.reasons = list(d.get("reasons") or [])
        r.flags = list(d.get("flags") or [])
        r.rejected_peers = list(d.get("rejected_peers") or [])
        return r


@dataclass
class SourceRef:
    kind: str                              # InputKind value, see tracklister.inputs.detect
    ref: str                               # file name (no directories), URL or "texto"
    detail: str | None = None              # "youtube_comment:@travo1001 (22 pistas)"
    imported_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SourceRef":
        return _from_dict(cls, d)


@dataclass
class PassRecord:
    index: int                             # 1-based pass counter within the set
    name: str                              # FormatPass.name, e.g. "lossless", "mp3_320"
    engine: str                            # engine id, e.g. "sockseek-3.0.5" or "fake:sockseek-3.0.5"
    uids: list[str] = field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    work_dir: str | None = None            # absolute, under %LOCALAPPDATA%\Tracklister\work

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PassRecord":
        return _from_dict(cls, d)


@dataclass
class SetDoc:
    """<set folder>/.tracklister/set.json"""
    set_id: str
    name: str
    preset_id: str
    rows: list[TrackRow] = field(default_factory=list)
    results: dict[str, RowResult] = field(default_factory=dict)   # by uid
    sources: list[SourceRef] = field(default_factory=list)
    passes: list[PassRecord] = field(default_factory=list)
    lossy_approved: list[str] = field(default_factory=list)       # uids allowed to fall back to MP3 320
    duplicate_choices: dict[str, str] = field(default_factory=dict)  # uid -> DuplicateChoice value
    preset_snapshot: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
    app_version: str | None = None
    schema: str = SET_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema, "set_id": self.set_id, "name": self.name,
            "preset_id": self.preset_id, "preset_snapshot": self.preset_snapshot,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "app_version": self.app_version,
            "sources": [s.to_dict() for s in self.sources],
            "rows": [r.to_dict() for r in self.rows],
            "results": {k: v.to_dict() for k, v in self.results.items()},
            "passes": [p.to_dict() for p in self.passes],
            "lossy_approved": list(self.lossy_approved),
            "duplicate_choices": dict(self.duplicate_choices),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SetDoc":
        if d.get("schema") != SET_SCHEMA:
            raise ValueError(f"esquema de set desconocido: {d.get('schema')!r}")
        return cls(
            set_id=d["set_id"], name=d["name"], preset_id=d["preset_id"],
            rows=[TrackRow.from_dict(r) for r in d.get("rows", [])],
            results={k: RowResult.from_dict(v) for k, v in (d.get("results") or {}).items()},
            sources=[SourceRef.from_dict(s) for s in d.get("sources", [])],
            passes=[PassRecord.from_dict(p) for p in d.get("passes", [])],
            lossy_approved=list(d.get("lossy_approved") or []),
            duplicate_choices=dict(d.get("duplicate_choices") or {}),
            preset_snapshot=dict(d.get("preset_snapshot") or {}),
            created_at=d.get("created_at"), updated_at=d.get("updated_at"),
            app_version=d.get("app_version"),
        )


@dataclass
class LibraryEntry:
    """One verified file of a previous set (entries of %APPDATA%\\Tracklister\\library.json)."""
    key: str                  # library_key(): "<artist_norm>|<title_norm>|<version_norm or 'original'>"
    artist_norm: str
    title_norm: str
    version_kind: str         # VersionKind value
    path: str                 # absolute path of the file in its set folder
    set_id: str
    set_name: str
    pos: int
    duration_s: float | None = None
    format: str | None = None
    size: int | None = None
    added_at: str | None = None
    flags: list[str] = field(default_factory=list)   # marks of the source file that a reuse must keep,
    #   e.g. "posible_falso_lossless" (optional: library.json files without it still load)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LibraryEntry":
        e = _from_dict(cls, d)
        e.flags = list(d.get("flags") or [])
        return e


@dataclass
class JournalOp:
    """One reversible file operation (rename/move/copy). Paths are absolute."""
    op: str                   # "move" | "copy" | "mkdir"
    src: str
    dst: str
    uid: str | None = None
    done_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "JournalOp":
        return _from_dict(cls, d)
