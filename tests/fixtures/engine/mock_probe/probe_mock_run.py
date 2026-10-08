"""One-off E-0 probe: run the REAL pinned engines in MOCK mode only (no Soulseek, no network).

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Why this is safe (proven from the pinned sources, see third_party/engines/ENGINE-FACTS.md, item 6):
- Sockseek 3.0.5: SoulseekClientManager.CreateClientInstance returns LocalFilesSoulseekClient when
  --mock-files-dir is set; its ConnectAsync/SetSharedCountsAsync are no-ops. The real
  Soulseek.SoulseekClient (the only Soulseek network code) is built only in the other branch.
- sldl 2.6.0: same structure (SoulseekClientManager.cs CreateClientInstance -> MockSoulseekClient,
  compiled into sldl.exe by slsk-batchdl.csproj; ConnectAsync is a no-op).
- CSV input never uses the HTTP extractors (Bandcamp/MusicBrainz/YouTube), and neither --remote
  nor --yt-dlp is passed. --no-config: no config file is read.
Dummy credentials only. This script refuses to run any argv without --mock-files-dir.

Usage: .venv\\Scripts\\python.exe tests\\fixtures\\engine\\mock_probe\\probe_mock_run.py
Writes the captured outputs to tests/fixtures/engine/mock-run/<engine_id>/.
"""
from __future__ import annotations

import json
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
from tracklister.engine.csvwriter import write_engine_csv  # noqa: E402
from tracklister.engine.presets import build_preset  # noqa: E402
from tracklister.engine.spec import ENGINE_PINS, EngineSpec  # noqa: E402

DUMMY = Credentials("usuario-prueba", "clave-prueba")
EXES = {
    "sockseek-3.0.5": REPO / "third_party/engines/bin/x/sockseek_3.0.5_win-x64/sockseek.exe",
    "sldl-2.6.0": REPO / "third_party/engines/bin/x/sldl_win-x86_self-contained/sldl.exe",
}
CREATE_NO_WINDOW = 0x08000000


def rows() -> list[TrackRow]:
    def r(pos, artist, title, version=None, length=None):
        return TrackRow(pos=pos, title=title, artists=[artist], artist_display=artist,
                        version=version, expected_duration_s=length)
    return [
        r(1, "Fjaak", "Spirit", length=20),
        r(2, "Chris Liebing", "Higher Things", "FJAAK Remix", length=25),
        r(3, "Nobody Known", "Nonexistent Track"),
        r(4, "A1", "Same Name"),
        r(5, "A2", "Same Name"),
        r(6, "Comma, Artist", "Say, Hi"),
        r(7, 'Quote "Q" Artist', "Not Here"),
    ]


def make_mock_dir(root: Path) -> None:
    make_track(root / "peerA/Music/Fjaak/Fjaak - Spirit.flac", fmt="flac", seconds=20,
               tags={"artist": "Fjaak", "title": "Spirit"})
    make_track(root / "peerA/Music/Fjaak/Fjaak - Spirit (Some Remix).flac", fmt="flac", seconds=31,
               tags={"artist": "Fjaak", "title": "Spirit (Some Remix)"})
    make_track(root / "peerB/Techno/Chris Liebing - Higher Things (FJAAK Remix).flac", fmt="flac",
               seconds=25, tags={"artist": "Chris Liebing", "title": "Higher Things (FJAAK Remix)"})
    make_track(root / "peerC/A1/Same Name.flac", fmt="flac", seconds=12, tags=None, seed=1)
    make_track(root / "peerC/A2/Same Name.flac", fmt="flac", seconds=13, tags=None, seed=2)
    make_track(root / "peerD/Comma, Artist - Say, Hi.wav", fmt="wav", seconds=10, tags=None)


def run(engine_id: str, out_root: Path) -> None:
    exe = EXES[engine_id]
    pin = ENGINE_PINS[engine_id]
    spec = EngineSpec(engine_id, pin.dialect, (str(exe),))
    out = out_root / engine_id
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="tlprobe-") as td:
        td = Path(td)
        mock = td / "mock"
        make_mock_dir(mock)
        work = td / "w" / "p01"
        work.mkdir(parents=True)
        manifest = write_engine_csv(rows(), work / "input.csv")
        fmt = build_preset("lossless").passes[0]
        job = EngineJob(work_dir=work, fmt=fmt, has_lengths=True, listen_port=49998, concurrent=2)
        argv = build_command(spec, job, DUMMY)
        extra = ["--mock-files-dir", str(mock)]
        if pin.dialect == "sockseek3":
            extra.append("--no-listen")
        argv = argv + extra
        assert "--mock-files-dir" in argv, "refusing: mock mode only"
        p = subprocess.run(argv, cwd=td, capture_output=True, timeout=600, creationflags=CREATE_NO_WINDOW)
        stdout = p.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")
        def scrub(s: str) -> str:
            # Temp dir and user profile in every spelling (plain, forward slashes, JSON-escaped):
            # nothing personal may land in the repo.
            for path, label in ((str(td), "<TMP>"), (str(Path.home()), "%USERPROFILE%")):
                for variant in (path, path.replace("\\", "/"), path.replace("\\", "\\\\")):
                    s = s.replace(variant, label)
            return s

        (out / "argv.txt").write_text(scrub("\n".join(redact_argv(argv[1:]))) + "\n", encoding="utf-8")
        (out / "stdout.txt").write_text(scrub(stdout), encoding="utf-8")
        (out / "stderr.txt").write_text(scrub(p.stderr.decode("utf-8", errors="replace")), encoding="utf-8")
        (out / "exit_code.txt").write_text(str(p.returncode) + "\n", encoding="utf-8")
        (out / "input.csv").write_bytes((work / "input.csv").read_bytes())
        (out / "manifest.json").write_text(json.dumps([m.to_dict() for m in manifest], indent=1,
                                                      ensure_ascii=False), encoding="utf-8")
        for name, dst in (("index.csv", "index.csv"), ("playlist.m3u", "playlist.m3u"),
                          ("engine.log", "engine-log.txt")):
            src = work / name
            if src.exists():
                (out / dst).write_text(scrub(src.read_text(encoding="utf-8", errors="replace")),
                                       encoding="utf-8")
        tree = sorted(str(f.relative_to(work)).replace("\\", "/") + f"  {f.stat().st_size}"
                      for f in work.rglob("*") if f.is_file())
        (out / "tree.txt").write_text("\n".join(tree) + "\n", encoding="utf-8")

        # Search-only JSON shape (Diagnostico): keyed string input + --print json-all.
        job2 = EngineJob(work_dir=td / "w" / "p02", fmt=fmt, has_lengths=True, listen_port=49998,
                         print_json_all=True, input_override="artist=Fjaak, title=Spirit, length=20")
        (td / "w" / "p02").mkdir(parents=True)
        argv2 = build_command(spec, job2, DUMMY) + extra
        assert "--mock-files-dir" in argv2
        p2 = subprocess.run(argv2, cwd=td, capture_output=True, timeout=600, creationflags=CREATE_NO_WINDOW)
        (out / "json-all.stdout.txt").write_text(
            scrub(p2.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")), encoding="utf-8")
        (out / "json-all.exit_code.txt").write_text(str(p2.returncode) + "\n", encoding="utf-8")
        print(engine_id, "exit", p.returncode, "json-all exit", p2.returncode)


if __name__ == "__main__":
    target = REPO / "tests" / "fixtures" / "engine" / "mock-run"
    for eid in (sys.argv[1:] or list(EXES)):
        run(eid, target)
