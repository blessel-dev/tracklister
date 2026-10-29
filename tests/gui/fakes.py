"""Fakes for the GUI tests: services without network, a scripted prompter, canned import results.

SPDX-License-Identifier: GPL-3.0-or-later

FakeImport/FakeCandidate mirror the attribute names of inputs.importer.ImportResult and
CandidateView (plan.md section 6) WITHOUT importing them: the GUI only relies on those names.
The engine is the FAKE engine (tests/fakes/fake_engine.py) driven by a scenario network file.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication, QEvent

from tracklister.core.model import RowStatus, SourceRef, TrackRow
from tracklister.engine.ratelimit import SearchBudget
from tracklister.engine.runner import EngineRunner
from tracklister.engine.spec import fake_engine_spec
from tracklister.gui.services import Services


def flush_deferred_deletes() -> None:
    """Delete now the objects whose deleteLater() is pending. pytest-qt closes each test's windows with close()
    + deleteLater() and then calls processEvents(), which outside an event loop never delivers DeferredDelete:
    the closed windows of a module piled up (thousands of live widgets) and every new window polished them all."""
    if QCoreApplication.instance() is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@dataclass
class FakeCandidate:
    label_es: str
    n_rows: int
    has_times: bool = True
    likes: int | None = None
    rows: list | None = None
    source_ref: SourceRef | None = None


@dataclass
class FakeImport:
    kind: str = "trackid_csv"
    rows: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    message_es: str = ""
    warnings_es: list = field(default_factory=list)
    candidates: list = field(default_factory=list)
    chosen: int | None = None
    suggested_name: str | None = None
    links: list = field(default_factory=list)


@dataclass
class FakeOutcome:
    uid: str
    provider: str | None
    accepted: bool
    changed: tuple = ()
    note_es: str = ""


@dataclass
class FakeUpdate:
    latest: str
    url: str
    name_es: str


def sample_rows() -> list[TrackRow]:
    """A small trackid-like table: strong rows, a partial one and an ID gap."""
    return [
        TrackRow(pos=1, title="Spirit", artists=["Fjaak"], artist_display="Fjaak", ts_start=0, source="trackid_csv",
                 label="Monkeytown"),
        TrackRow(pos=2, title="Higher Things", artists=["Chris Liebing"], artist_display="Chris Liebing",
                 version="FJAAK Remix", ts_start=312, source="trackid_csv"),
        TrackRow(pos=3, title="ID (hueco)", artists=[], artist_display="", ts_start=640, is_id=True,
                 status=RowStatus.ID, download=False, confidence=0.0, source="trackid_csv"),
        TrackRow(pos=4, title="Mercy Dub", artists=["Roll Dann"], artist_display="Roll Dann", ts_start=905,
                 status=RowStatus.REVISAR, download=False, confidence=0.4, source="trackid_csv",
                 raw="Roll Dann Mercy Dub"),
    ]


def fake_import(rows: list[TrackRow] | None = None, **kw) -> FakeImport:
    rows = sample_rows() if rows is None else rows
    kw.setdefault("sources", [SourceRef("trackid_csv", "set.csv")])
    kw.setdefault("message_es", f"{len(rows)} pistas leídas del CSV de trackid.net.")
    kw.setdefault("suggested_name", "Set de prueba")
    return FakeImport(rows=rows, **kw)


class FakeServices(Services):
    """Real settings/account/library/sessions; fake inputs, enrichment, updates, yt-dlp and desktop."""

    def __init__(self, *, library_root: Path | None = None, network: Path | None = None):
        super().__init__()
        if library_root is not None:
            self.settings.library_root = str(library_root)
        self.network = network
        self.imports: list[Any] = []          # queue of results for import_source
        self.import_calls: list[Any] = []
        self.merge_calls = 0
        self.enrich_calls = 0
        self.enrich_duration = 300
        self.update_info: FakeUpdate | None = None
        self.update_calls: list[bool] = []
        self.ytdlp_updates = 0
        self.opened_urls: list[str] = []
        self.opened_paths: list[Path] = []
        self.copied: list[str] = []
        self.real_gaps = False                # 1.0.1 R1: tests of the gap hook turn the real inputs.gaps on
        self.gap_calls: list[list] = []

    # inputs / enrichment / updates
    def import_source(self, source):
        self.import_calls.append(source)
        if self.imports:
            return self.imports.pop(0)
        return fake_import()

    def merge_rows(self, base, extra):
        self.merge_calls += 1
        return list(base) + [r for r in extra if not r.is_id]

    def recompute_gaps(self, rows, dismissed=()):
        """The fake tables carry no End times, so by default the gaps are left as they are."""
        self.gap_calls.append(list(dismissed))
        if self.real_gaps:
            return Services.recompute_gaps(self, rows, dismissed)
        from types import SimpleNamespace
        return SimpleNamespace(rows=rows, added=0, removed=0, changed=False)

    def is_trackid_csv(self, path):
        return "trackid" in Path(path).name.lower()

    def enrich(self, rows, on_progress=None, cancel=None):
        self.enrich_calls += 1
        out = []
        for i, r in enumerate(rows, start=1):
            if on_progress:
                on_progress(i, len(rows))
            if r.is_id:
                out.append(FakeOutcome(r.uid, None, False))
                continue
            r.expected_duration_s = self.enrich_duration
            r.enrich_source = "itunes"
            out.append(FakeOutcome(r.uid, "itunes", True, ("expected_duration_s",)))
        return out

    def check_for_update(self, force=False):
        self.update_calls.append(force)
        return self.update_info

    def ytdlp_version(self):
        return "2026.09.30"

    def update_ytdlp(self):
        self.ytdlp_updates += 1
        return True, "yt-dlp actualizado a 2026.10.07."

    def ensure_ytdlp(self):
        return None

    # engine: the fake engine with a scenario network
    def make_runner(self):
        env = {"TRACKLISTER_FAKE_NETWORK": str(self.network)} if self.network else {}
        return EngineRunner(fake_engine_spec(), SearchBudget(self.paths.search_budget_file), env=env)

    # desktop
    def open_url(self, url):
        self.opened_urls.append(url)

    def open_path(self, path):
        self.opened_paths.append(Path(path))

    def copy_text(self, text):
        self.copied.append(text)


class ScriptedPrompter:
    """Answers every modal question from queues and records what was asked."""

    def __init__(self):
        self.duplicates: list = []     # answers for ask_duplicate: (choice, entry|None|"first", apply_all) or None
        self.lossy: set[str] | None = None
        self.confirm_answer = True
        self.choose_answers: list = []
        self.choose_texts: list[str] = []
        self.choose_defaults: list = []
        self.folders: list = []
        self.files: list = []
        self.calls: list[tuple] = []

    def inform(self, title, text):
        self.calls.append(("inform", title, text))

    def error(self, title, text):
        self.calls.append(("error", title, text))

    def confirm(self, title, text, ok="Sí", cancel="Cancelar"):
        self.calls.append(("confirm", title, text))
        return self.confirm_answer

    def choose(self, title, text, options, default=None):
        self.calls.append(("choose", title, tuple(options)))
        self.choose_texts.append(text)
        self.choose_defaults.append(default)
        return self.choose_answers.pop(0) if self.choose_answers else None

    def pick_folder(self, title, start=None):
        self.calls.append(("pick_folder", title))
        return self.folders.pop(0) if self.folders else None

    def pick_file(self, title, start=None, filters=None):
        self.calls.append(("pick_file", title))
        return self.files.pop(0) if self.files else None

    def ask_duplicate(self, hit, index, total):
        self.calls.append(("ask_duplicate", hit.row.pos, index, total))
        if not self.duplicates:
            return None
        ans = self.duplicates.pop(0)
        if ans is None:
            return None
        choice, entry, apply_all = ans
        if entry == "first":
            entry = hit.entries[0]
        return choice, entry, apply_all

    def ask_lossy(self, rows, preset):
        self.calls.append(("ask_lossy", tuple(r.pos for r in rows)))
        return set(self.lossy or set())

    def kinds(self) -> list[str]:
        return [c[0] for c in self.calls]
