"""1.0.1 (R4) probe: the REAL pinned engines in MOCK mode only (no Soulseek, no network), on his three
no-result rows, their search variants and --desperate.

Owner: ENGINE branch (C).
SPDX-License-Identifier: GPL-3.0-or-later

Why this is safe: the same proof as probe_mock_run.py (third_party/engines/ENGINE-FACTS.md, item 6).
With --mock-files-dir both engines build their local mock client (3.x LocalFilesSoulseekClient, 2.x
MockSoulseekClient), whose ConnectAsync is a no-op; the real Soulseek client is never constructed.
--desperate only adds searches through that same client (3.x Sockseek.Core/Search/Searcher.cs:596-648,
2.x Services/Searcher.cs:739-811). CSV input, --no-config, dummy credentials, --no-listen (3.x).
This script refuses to run any argv without --mock-files-dir.

The mock clients match every query word as a substring of the file path (3.x LocalFilesSoulseekClient.cs
:199, 2.x MockSoulseekClient.cs:151-152), so 'vkn.modular' never finds 'VKN Modular - ...'. What this
shows about the REAL engine code: its query cleaning, its strict artist/title filters and its desperate
searches. What it cannot show: how real Soulseek peers match words.

Usage: .venv\\Scripts\\python.exe tests\\fixtures\\engine\\mock_probe\\probe_r4_variants.py
Writes tests/fixtures/engine/mock-run-r4/<engine_id>/<run>/{argv.txt,stdout.txt,index.csv,exit_code.txt,
tree.txt,input.csv}.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from tests.fakes.synth import make_track  # noqa: E402
from tracklister.core.model import TrackRow  # noqa: E402
from tracklister.engine.cli import EngineJob, build_command, redact_argv  # noqa: E402
from tracklister.engine.credentials import Credentials  # noqa: E402
from tracklister.engine.csvwriter import SearchQuery, write_engine_csv  # noqa: E402
from tracklister.engine.presets import build_preset, relaxed  # noqa: E402
from tracklister.engine.spec import ENGINE_PINS, EngineSpec  # noqa: E402

DUMMY = Credentials("usuario-prueba", "clave-prueba")
EXES = {
    "sockseek-3.0.5": REPO / "third_party/engines/bin/x/sockseek_3.0.5_win-x64/sockseek.exe",
    "sldl-2.6.0": REPO / "third_party/engines/bin/x/sldl_win-x86_self-contained/sldl.exe",
}
CREATE_NO_WINDOW = 0x08000000

# (peer, path inside the peer's share, seconds). Invented folders; his rows' public artist and title.
MOCK_FILES = [
    ("peerA", "Musica/Jeroen Search/Jeroen Search - Inject.flac", 20),
    ("peerB", "Musica/Vkn Modular/VKN Modular - Hidden Reason.flac", 20),
    ("peerC", "Musica/TR-440/TR-440 - Somewhen.flac", 20),
    ("peerD", "Musica/Red Rooms/Red Rooms - Trip.flac", 26),      # 6 s longer than the row says
]


def his_rows() -> list[TrackRow]:
    def r(pos, artist, title, length):
        return TrackRow(pos=pos, title=title, artists=[artist], artist_display=artist, expected_duration_s=length,
                        uid=f"r{pos}")
    return [r(1, "Komplex aka Jeroen Search", "Inject", 20), r(2, "Vkn.modular", "Hidden Reason", 20),
            r(3, "TR440", "Somewhen", 20), r(4, "Red Rooms", "Trip", 20), r(5, "Nobody Real", "Trip", None)]


# run name -> (row uids, queries by uid, relaxed, desperate)
RUNS = {
    "1-base": (["r1", "r2", "r3", "r4", "r5"], {}, False, False),
    "2-variante-1": (["r1", "r2", "r3"], {"r1": SearchQuery("Komplex", "Inject"),
                                           "r2": SearchQuery("Vkn modular", "Hidden Reason"),
                                           "r3": SearchQuery("TR 440", "Somewhen")}, False, False),
    "3-variante-2": (["r1", "r3"], {"r1": SearchQuery("Jeroen Search", "Inject"),
                                    "r3": SearchQuery("TR-440", "Somewhen")}, False, False),
    "4-desesperado": (["r1", "r2", "r3", "r4", "r5"], {}, True, True),
}


def make_mock_dir(root: Path) -> None:
    for peer, rel, seconds in MOCK_FILES:
        make_track(root / peer / rel, fmt="flac", seconds=seconds, tags=None, seed=len(rel))


def run(engine_id: str, out_root: Path) -> None:
    exe = EXES[engine_id]
    pin = ENGINE_PINS[engine_id]
    spec = EngineSpec(engine_id, pin.dialect, (str(exe),))
    out = out_root / engine_id
    if out.exists():
        shutil.rmtree(out)
    with tempfile.TemporaryDirectory(prefix="tlprobe-") as td:
        td = Path(td)
        mock = td / "mock"
        make_mock_dir(mock)

        def scrub(s: str) -> str:
            for path, label in ((str(td), "<TMP>"), (str(Path.home()), "%USERPROFILE%")):
                for variant in (path, path.replace("\\", "/"), path.replace("\\", "\\\\")):
                    s = s.replace(variant, label)
            return s

        rows = {r.uid: r for r in his_rows()}
        for name, (uids, queries, relax, desperate) in RUNS.items():
            work = td / "w" / name
            work.mkdir(parents=True)
            write_engine_csv([rows[u] for u in uids], work / "input.csv", queries=queries)
            fmt = build_preset("lossless").passes[0]
            job = EngineJob(work_dir=work, fmt=relaxed(fmt) if relax else fmt, has_lengths=True,
                            listen_port=49998, concurrent=2, desperate=desperate)
            extra = ["--mock-files-dir", str(mock)] + (["--no-listen"] if pin.dialect == "sockseek3" else [])
            argv = build_command(spec, job, DUMMY) + extra
            assert "--mock-files-dir" in argv, "refusing: mock mode only"
            p = subprocess.run(argv, cwd=td, capture_output=True, timeout=600, creationflags=CREATE_NO_WINDOW)
            dst = out / name
            dst.mkdir(parents=True)
            (dst / "argv.txt").write_text(scrub("\n".join(redact_argv(argv[1:]))) + "\n", encoding="utf-8")
            (dst / "stdout.txt").write_text(scrub(p.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")),
                                            encoding="utf-8")
            (dst / "exit_code.txt").write_text(f"{p.returncode}\n", encoding="utf-8")
            (dst / "input.csv").write_bytes((work / "input.csv").read_bytes())
            if (work / "index.csv").exists():
                (dst / "index.csv").write_text(scrub((work / "index.csv").read_text(encoding="utf-8")),
                                               encoding="utf-8")
            tree = sorted(str(f.relative_to(work)).replace("\\", "/") for f in work.rglob("*")
                          if f.is_file() and "/in/" in "/" + str(f.relative_to(work)).replace("\\", "/"))
            (dst / "tree.txt").write_text("\n".join(tree) + "\n", encoding="utf-8")
            print(engine_id, name, "exit", p.returncode, "files", tree)


if __name__ == "__main__":
    target = REPO / "tests" / "fixtures" / "engine" / "mock-run-r4"
    for eid in (sys.argv[1:] or list(EXES)):
        run(eid, target)
