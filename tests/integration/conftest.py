"""Integration fixtures: the REAL gui.services.Services wired to the fake engine and recorded HTTP.

SPDX-License-Identifier: GPL-3.0-or-later

Everything real except three things, so nothing leaves this machine:
- the engine is the FAKE engine (tests/fakes/fake_engine.py) with a scenario network: never Soulseek;
- HTTP (iTunes/Deezer/MusicBrainz/GitHub) answers come from tests/fixtures/http (ReplayTransport);
- opening links/folders and the clipboard are recorded instead of touching the desktop.
The account is the dummy one, stored through engine.credentials in the in-memory keyring of
tests/conftest.py. TRACKLISTER_HOME is a temp dir (tests/conftest.py).
"""
from __future__ import annotations

import gc
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from tests.gui.fakes import ScriptedPrompter  # noqa: E402
from tracklister.engine.credentials import CredentialStore, Credentials  # noqa: E402
from tracklister.engine.ratelimit import SearchBudget  # noqa: E402
from tracklister.engine.runner import EngineRunner  # noqa: E402
from tracklister.engine.spec import fake_engine_spec  # noqa: E402
from tracklister.gui.services import Services  # noqa: E402
from tracklister.net.http import HttpClient, ReplayTransport  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "fixtures"
SAMPLE_CSV = FIX / "inputs" / "fjaak-techno-dj-set-section-may-2026.csv"
USER, PASSWORD = "usuario-prueba", "clave-prueba"


class IntegrationServices(Services):
    """gui.services.Services itself; only the engine, the HTTP transport and the desktop differ."""

    def __init__(self, *, library_root: Path, http: HttpClient | None = None, network: Path | None = None):
        super().__init__(http=http)
        self.settings.library_root = str(library_root)
        self.network = network
        self.opened_urls: list[str] = []
        self.opened_paths: list[Path] = []
        self.copied: list[str] = []

    def make_runner(self) -> EngineRunner:
        env = {"TRACKLISTER_FAKE_NETWORK": str(self.network)} if self.network else {}
        return EngineRunner(fake_engine_spec(), SearchBudget(self.paths.search_budget_file), env=env)

    def open_url(self, url: str) -> None:
        self.opened_urls.append(url)

    def open_path(self, path) -> None:
        self.opened_paths.append(Path(path))

    def copy_text(self, text: str) -> None:
        self.copied.append(text)


def replay(*parts: str) -> tuple[HttpClient, ReplayTransport]:
    """An HttpClient over recorded answers (no sleeping: the spacing itself is unit-tested)."""
    rt = ReplayTransport(FIX.joinpath("http", *parts))
    return HttpClient(rt, sleep=lambda s: None), rt


def no_network_http() -> HttpClient:
    def refuse(req):
        raise AssertionError(f"unexpected HTTP request: {req.method} {req.url}")
    return HttpClient(refuse, sleep=lambda s: None)


def make_services(tmp_path: Path, *, http: HttpClient | None = None, network: Path | None = None,
                  enrichment: bool = False) -> IntegrationServices:
    s = IntegrationServices(library_root=tmp_path / "biblioteca", http=http or no_network_http(), network=network)
    s.settings.first_run_done = True
    s.settings.legal_notice_accepted = True
    s.settings.share_notice_shown = True
    s.settings.enrichment_enabled = enrichment
    s.settings.watch_downloads_folder = False
    s.save_settings()
    CredentialStore().set(Credentials(USER, PASSWORD))
    return s


@pytest.fixture
def app(qapp):
    from tracklister.gui.app import prepare_app
    return prepare_app(qapp)


@pytest.fixture(autouse=True)
def _collect_garbage_in_the_gui_thread():
    """Same rule as tests/gui: Qt objects are only collected in the GUI thread."""
    yield
    gc.collect()


@pytest.fixture(scope="package", autouse=True)
def _restore_automatic_gc():
    yield
    from tracklister.gui import gcguard
    gcguard.uninstall()


@pytest.fixture
def prompter() -> ScriptedPrompter:
    return ScriptedPrompter()


@pytest.fixture
def open_window(qtbot, app, prompter):
    """open_window(services) -> a shown MainWindow; workers and tasks are stopped at teardown."""
    from tracklister.gui.app import build_window
    made = []

    def _open(services):
        w = build_window(services, app=app, prompter=prompter)
        qtbot.addWidget(w)
        w.resize(1280, 820)
        w.show()
        qtbot.waitExposed(w)
        made.append(w)
        return w

    yield _open
    for w in made:
        w.pool.cancel_all()
        w.pool.wait_all(10000)
        if w.worker is not None:
            w.worker.stop()
            w.worker.wait(30000)
