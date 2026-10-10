"""Headless screenshots of the REAL window in both themes, plus one overview sheet.

SPDX-License-Identifier: GPL-3.0-or-later

    .\\.venv\\Scripts\\python.exe tools\\screenshots.py [--out DIR] [--themes hormigon,noche] [--only a,b] [--keep]

Fully offline and safe for the corporate laptop:
- TRACKLISTER_HOME -> a scratch dir (nothing touches the real %APPDATA%/%LOCALAPPDATA%);
- an in-memory keyring with a dummy account (never the Windows Credential Manager);
- the FAKE engine (tests/fakes/fake_engine.py) with tests/fakes/scenarios.py networks: no Soulseek;
- enrichment ON (the app default) but answered from the recorded tests/fixtures/http files
  (ReplayTransport, no request leaves the machine); no update check, no Downloads watcher.
The 'nuevo set' and 'reordenar' captures import the sample trackid.net CSV
(tests/fixtures/inputs/) with the REAL importer (tracklister.inputs.importer).
The scratch data (settings, library, set folders) lives under the repo's git-ignored .tmp\\, so
the paths shown in the screens carry no Windows account name; it is deleted at the end unless
--keep is given.

Screens: 01 primer inicio (+ 01b scrolled down), 02 nuevo set, 03 descargando, 04 resultados
(every state), 05 duplicado, 06 lossy, 07 reordenar, 08 diagnostico, 09 ajustes (+ 09b scrolled
down); 00-vista-general-1.png, -2.png... put them side by side (pages of at most 1568 px).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
(REPO / ".tmp").mkdir(exist_ok=True)
_HOME = Path(tempfile.mkdtemp(prefix="capturas-", dir=REPO / ".tmp"))
os.environ["TRACKLISTER_HOME"] = str(_HOME / "home")


def _offscreen_platform() -> str:
    """Offscreen Qt on a 1920x1080 virtual screen at 96 dpi, the usual home PC: Qt sizes a message box
    from the screen (its default 800x600 one squeezes them). The plugin splits its options on ':', so the
    config file goes as a relative path; on another drive the plain default screen is used."""
    import json
    cfg = _HOME / "pantalla.json"
    cfg.write_text(json.dumps({"screens": [{"name": "capturas", "x": 0, "y": 0, "width": 1920, "height": 1080,
                                             "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}), encoding="utf-8")
    try:
        rel = os.path.relpath(cfg).replace("\\", "/")
    except ValueError:
        return "offscreen"
    return "offscreen" if ":" in rel else f"offscreen:configfile={rel}"


os.environ["QT_QPA_PLATFORM"] = _offscreen_platform()
for p in (REPO / "src", REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import keyring  # noqa: E402
import keyring.backend  # noqa: E402

DEFAULT_OUT = Path(r"c:\projects\ABLETON\.agents\tasks\tracklister-v2\construccion\capturas")
SAMPLE_CSV = REPO / "tests" / "fixtures" / "inputs" / "fjaak-techno-dj-set-section-may-2026.csv"
HTTP_FIXTURES = REPO / "tests" / "fixtures" / "http"
SCREENS = ("primer-inicio", "primer-inicio-abajo", "nuevo-set", "descargando", "progreso", "resultados", "combinar",
           "duplicado", "lossy", "reordenar", "diagnostico", "ajustes", "ajustes-abajo")
SCREEN_LABELS_ES = {
    "primer-inicio": "Primer inicio", "primer-inicio-abajo": "Primer inicio (final de la página)",
    "nuevo-set": "Nuevo set (CSV de trackid.net de muestra)", "descargando": "Descargando",
    "progreso": "Descargando: progreso de cada pista", "resultados": "Resultados (todos los estados)",
    "combinar": "Combinar con un set ya descargado", "duplicado": "Pista repetida",
    "lossy": "Pistas que solo están en MP3", "reordenar": "Reordenar carpeta existente",
    "diagnostico": "Diagnóstico", "ajustes": "Ajustes", "ajustes-abajo": "Ajustes (final de la página)",
}
MB = 1024 * 1024
# R11 capture: public tracklist data of his set (06), each row in one running state of the Estado column
PROGRESS_ROWS = (("Komplex aka Jeroen Search", "Inject", None, 261), ("Red Rooms", "Trip", None, 305),
                 ("Kwartz", "Show me that light", "Cleric Remix", 385), ("Phil Berg", "Seiko", None, 332),
                 ("Vkn.modular", "Hidden Reason", None, 333), ("Rene Wise", "Dynamic", None, 319),
                 ("Orbe", "Velocity", None, 385))
DUMMY_USER, DUMMY_PASS = "usuario-prueba", "clave-prueba"


class _MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        import keyring.errors
        if (service, username) not in self.store:
            raise keyring.errors.PasswordDeleteError(username)
        del self.store[(service, username)]


keyring.set_keyring(_MemoryKeyring())

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QScrollArea  # noqa: E402

import tracklister.gui.pages.first_run as first_run_page  # noqa: E402
import tracklister.gui.pages.settings as settings_page  # noqa: E402
from tests.fakes.scenarios import build_scenario  # noqa: E402
from tests.gui.fakes import FakeServices, ScriptedPrompter  # noqa: E402
from tracklister.core.model import DuplicateChoice, ResultState, RowResult, SourceRef, TrackRow  # noqa: E402
from tracklister.engine.credentials import CredentialStore, Credentials  # noqa: E402
from tracklister.gui.app import build_window, create_app  # noqa: E402
from tracklister.gui.dialogs import DuplicateDialog, LossyDialog, Prompter  # noqa: E402
from tracklister.gui.pages.new_set import (  # noqa: E402
    MERGE_INSERT_ES, MERGE_KEEP_ES, MERGE_TITLE_ES, merge_question_es,
)
from tracklister.gui.services import Services  # noqa: E402
from tracklister.net.http import HttpClient, ReplayTransport  # noqa: E402
from tracklister.pipeline.session import SessionEvent  # noqa: E402


def wait_until(app, cond, timeout_s: float = 60.0) -> bool:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    app.processEvents()
    return bool(cond())


def settle(app, ms: int = 300) -> None:
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


class CaptureServices(FakeServices):
    """FakeServices (fake engine, no network, no desktop side effects) with the REAL importer and the
    REAL enrichment over the recorded iTunes/Deezer/MusicBrainz answers of tests/fixtures/http
    (ReplayTransport only reads files: no request leaves the machine)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._http = HttpClient(ReplayTransport(HTTP_FIXTURES), sleep=lambda s: None)

    def import_source(self, source):
        self.import_calls.append(source)
        return Services.import_source(self, source)

    def enrich(self, rows, on_progress=None, cancel=None):
        self.enrich_calls += 1
        return Services.enrich(self, rows, on_progress=on_progress, cancel=cancel)


def sample_csv() -> Path:
    if not SAMPLE_CSV.is_file():
        raise SystemExit(f"Falta la tracklist de muestra: {SAMPLE_CSV}")
    return SAMPLE_CSV


def sample_rows(services) -> tuple[list[TrackRow], str]:
    """The sample trackid CSV through the real importer."""
    csv_path = sample_csv()
    res = Services.import_source(services, csv_path)
    if not getattr(res, "rows", None):
        raise SystemExit(f"El importador no ha leído {csv_path.name}: {getattr(res, 'message_es', '')}")
    return list(res.rows), csv_path.name


def new_services(lib_root: Path, *, ready: bool = True, network: Path | None = None) -> CaptureServices:
    s = CaptureServices(library_root=lib_root, network=network)
    s.settings.enrichment_enabled = True          # the app default; answers come from the recorded fixtures
    s.settings.watch_downloads_folder = False
    if ready:
        s.settings.first_run_done = True
        s.settings.legal_notice_accepted = True
        s.settings.share_notice_shown = True
        CredentialStore().set(Credentials(DUMMY_USER, DUMMY_PASS))
    else:
        s.settings.library_root = None
        CredentialStore().clear()
    s.save_settings()
    return s


def make_window(app, services, prompter=None, theme: str = "hormigon"):
    services.settings.theme = theme
    w = build_window(services, app=app, prompter=prompter or ScriptedPrompter())
    w.themes.apply(theme)
    w.resize(1280, 820)
    w.show()
    settle(app, 200)
    return w


def close_window(app, w) -> None:
    w.pool.cancel_all()
    w.pool.wait_all(10000)
    if w.worker is not None:
        w.worker.stop()
        w.worker.wait(30000)
    w.close()
    w.deleteLater()
    settle(app, 100)


def save(img: QImage, out: Path, name: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{name}.png"
    img.save(str(p))
    return p


def scroll_to_bottom(app, page) -> None:
    """Long pages (primer inicio, ajustes) are scroll areas: show their last part too."""
    sa = page.findChild(QScrollArea)
    if sa is not None:
        bar = sa.verticalScrollBar()
        bar.setValue(bar.maximum())
    settle(app, 200)


def use_library_root_as_default(lib: Path) -> None:
    """The first-run and Ajustes pages propose the user's Music folder; in the captures they
    propose the scratch library this run really uses."""
    first_run_page.default_library_root = lambda: lib
    settings_page.default_library_root = lambda: lib


def run_previous_set(services, root: Path, tmp: Path) -> None:
    """'Anterior': the correcto scenario finalized, so the library has two tracks."""
    rows, net = build_scenario("correcto", tmp / "net-anterior")
    s = services.create_session("Anterior", rows, [SourceRef("tabla", "anterior.csv")])
    runner = services.make_runner()
    runner.env["TRACKLISTER_FAKE_NETWORK"] = str(net)
    s.run(runner, Credentials(DUMMY_USER, DUMMY_PASS), lambda e: None, threading.Event(), lambda r: set())
    s.finalize(services.library())


def capture_progress(app, services, out: Path, theme: str) -> Path:
    """R11: the Descarga screen in the middle of a pass, one row in each running state. The fake engine
    downloads one row at a time, so the page gets the same SessionEvents a running session sends (no engine):
    Sockseek 3.0.5 (the default) does not say the size, so its bar moves and the text gives the MB; sldl 2.6.0
    says it, so the bar fills with the percentage. Both are shown."""
    rows = [TrackRow(pos=i, title=t, artists=[a], artist_display=a, version=v, expected_duration_s=d,
                     source="trackid_csv") for i, (a, t, v, d) in enumerate(PROGRESS_ROWS, start=1)]
    sess = services.create_session("SetAOC Mass Danza Futura 2026", rows, [SourceRef("trackid_csv", "set.csv")])
    w = make_window(app, services, theme=theme)
    w.session = sess
    page = w.results
    page.show_session(sess, running=True)
    w.go("results")
    on = page.on_session_event
    total = len(rows)
    on(SessionEvent("pass_started", message_es="Pasada 1: lossless: 7 pistas.", total=total), None)
    for r in rows:
        on(SessionEvent("row_state", r.uid, ResultState.EN_CURSO, "En cola", total=total), None)
    u = [r.uid for r in sess.doc.rows]
    done = RowResult(uid=u[0], pos=1, state=ResultState.VERIFICADO, score=100, format="flac", samplerate=44100,
                     bitdepth=16, file="01 - Komplex aka Jeroen Search - Inject.flac",
                     reasons=["Coincide: artista, título y duración (4:21).",
                              "Encontrado buscando «Jeroen Search - Inject»."])
    on(SessionEvent("row_state", u[0], ResultState.VERIFICADO, done.reasons[0], 1, total), done)
    states = [("comprobando", None, None), ("descargando", int(33.6 * MB), int(41.0 * MB)),
              ("descargando", int(25.0 * MB), int(67.6 * MB)), ("descargando", int(25.9 * MB), None),
              ("cola", None, None), ("buscando", None, None)]
    for uid, (phase, got, size) in zip(u[1:], states):
        page.model._last_emit.clear()                   # one capture: no throttle between these
        on(SessionEvent("row_progress", uid, ResultState.EN_CURSO, total=total, phase=phase, bytes_done=got,
                        bytes_total=size), None)
    settle(app, 450)
    path = save(w.grab().toImage(), out, f"03b-progreso-{theme}")
    page.set_running(False)
    close_window(app, w)
    return path


def capture_theme(app, theme: str, out: Path, only: set[str]) -> dict[str, Path]:
    shots: dict[str, Path] = {}
    work = _HOME / theme
    work.mkdir(parents=True, exist_ok=True)
    os.environ["TRACKLISTER_HOME"] = str(work / "home")     # own settings + library per theme
    lib = work / "Música" / "Tracklister"
    use_library_root_as_default(lib)

    def want(name):
        return not only or name in only

    if want("primer-inicio") or want("primer-inicio-abajo"):
        s = new_services(lib, ready=False)
        w = make_window(app, s, theme=theme)
        if want("primer-inicio"):
            shots["primer-inicio"] = save(w.grab().toImage(), out, f"01-primer-inicio-{theme}")
        if want("primer-inicio-abajo"):
            scroll_to_bottom(app, w.first_run)
            shots["primer-inicio-abajo"] = save(w.grab().toImage(), out, f"01b-primer-inicio-abajo-{theme}")
        close_window(app, w)

    s = new_services(lib)
    if want("nuevo-set"):
        w = make_window(app, s, theme=theme)
        w.new_set.import_source(sample_csv())
        # import, then the automatic 'Completar datos' fills Versión/Duración from the recorded answers
        wait_until(app, lambda: not w.new_set._busy and w.new_set.model.rowCount() > 0
                   and "Datos completados" in w.new_set.banner.message(), 60)
        settle(app, 300)
        shots["nuevo-set"] = save(w.grab().toImage(), out, f"02-nuevo-set-{theme}")
        close_window(app, w)

    if want("descargando"):
        # peerB answers slowly, so the pass is still running when the capture is taken. The files are
        # verified when the engine pass ends, so the screen shows the engine's live progress lines.
        rows, net = build_scenario("correcto", work / "net-slow")
        import json
        data = json.loads(net.read_text(encoding="utf-8"))
        data["peers"] = {"peerB": {"slow": True, "slow_s": 60}}
        net.write_text(json.dumps(data), encoding="utf-8")
        s2 = new_services(lib, network=net)
        w = make_window(app, s2, theme=theme)
        w.start_download("Descargando", rows, [SourceRef("tabla", "set.csv")])
        if not wait_until(app, lambda: w.results.model.counts().get(ResultState.EN_CURSO, 0) >= len(rows), 30):
            print(f"aviso ({theme}): la pasada no llegó a 'en curso' a tiempo en 'descargando'")
        settle(app, 2500)                     # the fake engine prints its search/download lines
        if w.results.model.counts().get(ResultState.VERIFICADO, 0):
            print(f"aviso ({theme}): la pasada terminó antes de la captura de 'descargando'")
        shots["descargando"] = save(w.grab().toImage(), out, f"03-descargando-{theme}")
        w.cancel_run()
        wait_until(app, lambda: not w.worker_running(), 60)
        close_window(app, w)

    if want("progreso"):
        shots["progreso"] = capture_progress(app, s, out, theme)

    if want("resultados") or want("duplicado"):
        run_previous_set(s, lib, work)
    if want("resultados"):
        # 1.0.1: every state, with «Verificado · revisar calidad» (row 8) apart from «Dudoso»
        rows, net = build_scenario("todos_los_estados_101", work / "net-todos")
        s.network = net
        pr = ScriptedPrompter()
        pr.duplicates = [(DuplicateChoice.DOWNLOAD, None, False), (DuplicateChoice.REUSE, "first", False)]
        pr.lossy = set()
        w = make_window(app, s, pr, theme=theme)
        w.start_download("Todos los estados", rows, [SourceRef("tabla", "todos.csv")])
        wait_until(app, lambda: not w.worker_running() and w.results.phase.text() == "Terminado.", 120)
        settle(app, 300)
        shots["resultados"] = save(w.grab().toImage(), out, f"04-resultados-{theme}")
        close_window(app, w)

    if want("combinar"):
        # 1.0.1 R2 / D8: the question shown when the other source would change numbers of a downloaded set
        w = make_window(app, s, theme=theme)
        box, _ = Prompter(w, lambda: w.themes.theme).choose_box(
            MERGE_TITLE_ES, merge_question_es("SetAOC Mass Danza Futura 2026", 1, 9),
            [MERGE_KEEP_ES, MERGE_INSERT_ES.format(n="9 pistas")], default=0)
        box.show()
        settle(app, 400)
        shots["combinar"] = save(box.grab().toImage(), out, f"04b-combinar-{theme}")
        box.close()
        close_window(app, w)

    if want("duplicado") or want("lossy"):
        w = make_window(app, s, theme=theme)
        if want("duplicado"):
            rows, _ = build_scenario("duplicado_entre_sets", work / "net-dup")
            sess = s.create_session("Con repetidas", rows, [])
            hits = sess.find_duplicates(s.library())
            if hits:
                dlg = DuplicateDialog(hits[0], w.themes.theme, index=1, total=max(2, len(hits)), parent=w)
                dlg.show()
                settle(app, 300)
                shots["duplicado"] = save(dlg.grab().toImage(), out, f"05-duplicado-{theme}")
                dlg.close()
        if want("lossy"):
            rows, _ = build_scenario("todos_los_estados", work / "net-lossy")
            preset = s.create_session("Lossy", rows, []).preset
            dlg = LossyDialog([r for r in rows if r.pos in (2, 3, 5)], preset, parent=w)
            dlg.show()
            settle(app, 300)
            shots["lossy"] = save(dlg.grab().toImage(), out, f"06-lossy-{theme}")
            dlg.close()
        close_window(app, w)

    if want("reordenar"):
        rows, origin = sample_rows(s)
        old = work / "Música" / "Sets antiguos" / "Fjaak mayo 2026"
        old.mkdir(parents=True, exist_ok=True)
        names = ["Blasha & Allatt - 8AM in Salford.mp3", "phara - grey ribbon (original mix).flac",
                 "05. Justyn Nell - Visions.mp3", "Roll Dann - The Red House (Original Mix).mp3",
                 "DJ Dextro - Covil dos Abutres.aif", "Axel Karakasis - Last Ray.MP3",
                 "plug_trax_-_zoned_out.mp3", "Ferdinger - I'm Still Here.mp3", "STIPP - Corrie.mp3",
                 "Klint - Gunslingers.wav", "Lewis Fautzi - Zona Neutra.mp3", "Duffy - Mercy.mp3",
                 "Chris Liebing - Higher Things (Original Mix).mp3",
                 "Chris Liebing - Higher Things (FJAAK Remix).mp3"]
        for n in names:
            (old / n).write_bytes(n.encode("utf-8"))
        w = make_window(app, s, theme=theme)
        w.go("reorder")
        w.reorder.folder.setText(str(old))
        w.reorder.set_tracklist(rows, origin)
        w.reorder.propose()
        wait_until(app, lambda: w.reorder.model.rowCount() > 0, 30)
        settle(app, 300)
        shots["reordenar"] = save(w.grab().toImage(), out, f"07-reordenar-{theme}")
        close_window(app, w)

    if want("diagnostico"):
        rows, net = build_scenario("correcto", work / "net-diag")
        s.network = net
        w = make_window(app, s, theme=theme)
        w.go("diagnostic")
        w.diagnostic.set_tracklist(rows, "set.csv")
        w.diagnostic.start()
        wait_until(app, lambda: bool(w.diagnostic.report) or w.diagnostic.task is None, 90)
        settle(app, 300)
        shots["diagnostico"] = save(w.grab().toImage(), out, f"08-diagnostico-{theme}")
        close_window(app, w)

    if want("ajustes") or want("ajustes-abajo"):
        w = make_window(app, s, theme=theme)
        w.go("settings")
        settle(app, 500)
        if want("ajustes"):
            shots["ajustes"] = save(w.grab().toImage(), out, f"09-ajustes-{theme}")
        if want("ajustes-abajo"):
            scroll_to_bottom(app, w.settings_page)
            shots["ajustes-abajo"] = save(w.grab().toImage(), out, f"09b-ajustes-abajo-{theme}")
        close_window(app, w)
    return shots


OVERVIEW_MAX_SIDE = 1568      # every overview page fits an image viewer / review tool without downscaling


def overview(shots: dict[str, dict[str, Path]], out: Path) -> list[Path]:
    """Overview pages 00-vista-general-1.png, -2.png...: one row per screen, one column per theme,
    every capture at the same scale (dialogs keep their real size relative to the window), Spanish
    labels; no page is longer than OVERVIEW_MAX_SIDE px on either side."""
    themes = list(shots)
    screens = [s for s in SCREENS if any(s in shots[t] for t in themes)]
    window_w, cell_w, pad, label_h, head_h = 1280, 600, 16, 30, 40
    scale = cell_w / window_w

    def size_of(path: Path) -> tuple[int, int]:
        img = QImage(str(path))
        return max(1, round(img.width() * scale)), max(1, round(img.height() * scale))

    heights = {sc: max((size_of(shots[t][sc])[1] for t in themes if sc in shots[t]), default=0) for sc in screens}
    width = pad + len(themes) * (cell_w + pad)
    assert width <= OVERVIEW_MAX_SIDE, width
    pages: list[list[str]] = [[]]
    used = pad + head_h
    for sc in screens:
        need = heights[sc] + label_h + pad
        if pages[-1] and used + need > OVERVIEW_MAX_SIDE:
            pages.append([])
            used = pad + head_h
        pages[-1].append(sc)
        used += need
    for old in out.glob("00-vista-general*.png"):          # never leave a stale or oversized sheet behind
        old.unlink()
    return [_overview_page(shots, themes, page, heights, out / f"00-vista-general-{n}.png", width=width,
                           cell_w=cell_w, pad=pad, label_h=label_h, head_h=head_h, size_of=size_of)
            for n, page in enumerate(pages, start=1) if page]


def _overview_page(shots, themes, screens, heights, target: Path, *, width, cell_w, pad, label_h, head_h,
                   size_of) -> Path:
    rows = [heights[sc] for sc in screens]
    height = pad + head_h + sum(h + label_h + pad for h in rows)
    sheet = QImage(width, height, QImage.Format.Format_RGB32)
    sheet.fill(QColor("#e9e9e7"))
    p = QPainter(sheet)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    f = QFont("Inter")
    f.setPixelSize(16)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#161616"))
    for i, t in enumerate(themes):
        p.drawText(QRect(pad + i * (cell_w + pad), pad, cell_w, 30), Qt.AlignmentFlag.AlignLeft,
                   {"hormigon": "Hormigón (claro)", "noche": "Noche (oscuro)"}.get(t, t))
    y = pad + head_h
    f.setPixelSize(13)
    f.setBold(False)
    p.setFont(f)
    for sc, h in zip(screens, rows):
        for i, t in enumerate(themes):
            x = pad + i * (cell_w + pad)
            p.setPen(QColor("#161616"))
            p.drawText(QRect(x, y, cell_w, label_h - 6), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                       SCREEN_LABELS_ES.get(sc, sc))
            path = shots[t].get(sc)
            if path:
                iw, ih = size_of(path)
                ix = x + (cell_w - iw) // 2
                p.drawImage(QRect(ix, y + label_h, iw, ih), QImage(str(path)))
                p.drawRect(QRect(ix, y + label_h, iw - 1, ih - 1))
        y += h + label_h + pad
    p.end()
    sheet.save(str(target))
    return target


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--themes", default="hormigon,noche")
    ap.add_argument("--only", default="", help="comma-separated subset of: " + ",".join(SCREENS))
    ap.add_argument("--keep", action="store_true", help="keep the scratch data (settings, library, sets)")
    args = ap.parse_args(argv)
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    app = create_app(["screenshots"])
    shots = {}
    try:
        for theme in [t.strip() for t in args.themes.split(",") if t.strip()]:
            shots[theme] = capture_theme(app, theme, args.out, only)
            print(f"{theme}: {len(shots[theme])} capturas")
        for sheet in overview(shots, args.out):
            print(f"vista general: {sheet}")
    finally:
        if args.keep:
            print(f"datos de las capturas: {_HOME}")
        else:
            settle(app, 300)
            shutil.rmtree(_HOME, ignore_errors=True)
            if _HOME.exists():
                print(f"no se pudo borrar del todo {_HOME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
