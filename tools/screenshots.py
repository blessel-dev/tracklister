"""Headless screenshots of the REAL window in both themes, plus one overview sheet.

SPDX-License-Identifier: GPL-3.0-or-later

    .\\.venv\\Scripts\\python.exe tools\\screenshots.py [--out DIR] [--themes hormigon,noche] [--only a,b]

Fully offline and safe for the corporate laptop:
- TRACKLISTER_HOME -> a temp dir (nothing touches the real %APPDATA%/%LOCALAPPDATA%);
- an in-memory keyring with a dummy account (never the Windows Credential Manager);
- the FAKE engine (tests/fakes/fake_engine.py) with tests/fakes/scenarios.py networks: no Soulseek;
- no enrichment, no update check, no Downloads watcher.
The 'nuevo set' and 'reordenar' captures import the sample trackid.net CSV
(tests/fixtures/inputs/) with the REAL importer (tracklister.inputs.importer).

Screens: 01 primer inicio, 02 nuevo set, 03 descargando, 04 resultados (every state), 05 duplicado,
06 lossy, 07 reordenar, 08 diagnostico, 09 ajustes; 00-vista-general.png puts them side by side.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
_HOME = Path(tempfile.mkdtemp(prefix="tl-capturas-"))
os.environ["TRACKLISTER_HOME"] = str(_HOME)
REPO = Path(__file__).resolve().parents[1]
for p in (REPO / "src", REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import keyring  # noqa: E402
import keyring.backend  # noqa: E402

DEFAULT_OUT = Path(r"c:\projects\ABLETON\.agents\tasks\tracklister-v2\construccion\capturas")
SAMPLE_CSV = REPO / "tests" / "fixtures" / "inputs" / "fjaak-techno-dj-set-section-may-2026.csv"
SCREENS = ("primer-inicio", "nuevo-set", "descargando", "resultados", "duplicado", "lossy", "reordenar",
           "diagnostico", "ajustes")
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

from tests.fakes.scenarios import build_scenario  # noqa: E402
from tests.gui.fakes import FakeServices, ScriptedPrompter  # noqa: E402
from tracklister.core.model import DuplicateChoice, SourceRef, TrackRow  # noqa: E402
from tracklister.core.paths import app_paths  # noqa: E402
from tracklister.engine.credentials import CredentialStore, Credentials  # noqa: E402
from tracklister.gui.app import build_window, create_app  # noqa: E402
from tracklister.gui.dialogs import DuplicateDialog, LossyDialog  # noqa: E402
from tracklister.gui.services import Services  # noqa: E402


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
    """FakeServices (fake engine, no network, no desktop side effects) with the REAL importer."""

    def import_source(self, source):
        self.import_calls.append(source)
        return Services.import_source(self, source)


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
    s.settings.enrichment_enabled = False
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


def run_previous_set(services, root: Path, tmp: Path) -> None:
    """'Anterior': the correcto scenario finalized, so the library has two tracks."""
    rows, net = build_scenario("correcto", tmp / "net-anterior")
    s = services.create_session("Anterior", rows, [SourceRef("tabla", "anterior.csv")])
    runner = services.make_runner()
    runner.env["TRACKLISTER_FAKE_NETWORK"] = str(net)
    s.run(runner, Credentials(DUMMY_USER, DUMMY_PASS), lambda e: None, threading.Event(), lambda r: set())
    s.finalize(services.library())


def capture_theme(app, theme: str, out: Path, only: set[str]) -> dict[str, Path]:
    shots: dict[str, Path] = {}
    work = Path(tempfile.mkdtemp(prefix=f"tl-{theme}-", dir=_HOME))
    os.environ["TRACKLISTER_HOME"] = str(work / "home")     # own settings + library per theme
    lib = work / "biblioteca"

    def want(name):
        return not only or name in only

    if want("primer-inicio"):
        s = new_services(lib, ready=False)
        w = make_window(app, s, theme=theme)
        shots["primer-inicio"] = save(w.grab().toImage(), out, f"01-primer-inicio-{theme}")
        close_window(app, w)

    s = new_services(lib)
    if want("nuevo-set"):
        w = make_window(app, s, theme=theme)
        w.new_set.import_source(sample_csv())
        wait_until(app, lambda: not w.new_set._busy and w.new_set.model.rowCount() > 0, 30)
        settle(app, 300)
        shots["nuevo-set"] = save(w.grab().toImage(), out, f"02-nuevo-set-{theme}")
        close_window(app, w)

    if want("descargando"):
        rows, net = build_scenario("correcto", work / "net-slow")
        import json
        data = json.loads(net.read_text(encoding="utf-8"))
        data["peers"] = {"peerB": {"slow": True, "slow_s": 60}}
        net.write_text(json.dumps(data), encoding="utf-8")
        s2 = new_services(work / "biblioteca-descargando", network=net)
        w = make_window(app, s2, theme=theme)
        w.start_download("Descargando", rows, [SourceRef("tabla", "set.csv")])
        wait_until(app, lambda: w.results.model.counts().get("en_curso", 0) >= len(rows), 30)
        settle(app, 2500)                     # the fake engine prints its search/download lines
        shots["descargando"] = save(w.grab().toImage(), out, f"03-descargando-{theme}")
        w.cancel_run()
        wait_until(app, lambda: not w.worker_running(), 60)
        close_window(app, w)

    if want("resultados") or want("duplicado"):
        run_previous_set(s, lib, work)
    if want("resultados"):
        rows, net = build_scenario("todos_los_estados", work / "net-todos")
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
        old = work / "carpeta-antigua"
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

    if want("ajustes"):
        w = make_window(app, s, theme=theme)
        w.go("settings")
        settle(app, 500)
        shots["ajustes"] = save(w.grab().toImage(), out, f"09-ajustes-{theme}")
        close_window(app, w)
    return shots


def overview(shots: dict[str, dict[str, Path]], out: Path) -> Path:
    """One sheet: one row per screen, one column per theme, with labels."""
    themes = list(shots)
    screens = [s for s in SCREENS if any(s in shots[t] for t in themes)]
    cell_w, scale, pad, label_h = 560, 560 / 1280, 16, 30
    rows = []
    for sc in screens:
        h = 0
        for t in themes:
            p = shots[t].get(sc)
            if p:
                img = QImage(str(p))
                h = max(h, int(img.height() * cell_w / max(1, img.width())))
        rows.append(h)
    width = pad + len(themes) * (cell_w + pad)
    height = pad + 40 + sum(h + label_h + pad for h in rows)
    sheet = QImage(width, height, QImage.Format.Format_RGB32)
    sheet.fill(QColor("#e9e9e7"))
    p = QPainter(sheet)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    f = QFont("Inter")
    f.setPixelSize(15)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#161616"))
    for i, t in enumerate(themes):
        p.drawText(QRect(pad + i * (cell_w + pad), pad, cell_w, 30), Qt.AlignmentFlag.AlignLeft,
                   {"hormigon": "Hormigón (claro)", "noche": "Noche (oscuro)"}.get(t, t))
    y = pad + 40
    f.setPixelSize(12)
    f.setBold(False)
    p.setFont(f)
    for sc, h in zip(screens, rows):
        for i, t in enumerate(themes):
            x = pad + i * (cell_w + pad)
            p.drawText(QRect(x, y, cell_w, label_h - 6), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, sc)
            path = shots[t].get(sc)
            if path:
                img = QImage(str(path))
                ih = int(img.height() * cell_w / max(1, img.width()))
                p.drawImage(QRect(x, y + label_h, cell_w, ih), img)
                p.setPen(QColor("#161616"))
                p.drawRect(QRect(x, y + label_h, cell_w - 1, ih - 1))
        y += h + label_h + pad
    p.end()
    target = out / "00-vista-general.png"
    sheet.save(str(target))
    _ = scale
    return target


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--themes", default="hormigon,noche")
    ap.add_argument("--only", default="", help="comma-separated subset of: " + ",".join(SCREENS))
    args = ap.parse_args(argv)
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    app = create_app(["screenshots"])
    shots = {}
    for theme in [t.strip() for t in args.themes.split(",") if t.strip()]:
        shots[theme] = capture_theme(app, theme, args.out, only)
        print(f"{theme}: {len(shots[theme])} capturas")
    sheet = overview(shots, args.out)
    print(f"vista general: {sheet}")
    print(f"TRACKLISTER_HOME temporal: {app_paths().config_dir.parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
