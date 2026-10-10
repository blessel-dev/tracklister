"""Write the 1.0.0 fixtures of tests/fixtures/v100 WITH THE 1.0.0 CODE (commit 9191dd6). 1.0.1, R8.

SPDX-License-Identifier: GPL-3.0-or-later

Run from the repo root, with the 1.0.0 code checked out in a temporary worktree:

    git worktree add .tmp\\wt-100 9191dd6
    .\\.venv\\Scripts\\python.exe tests\\fixtures\\v100\\make_fixtures.py --code .tmp\\wt-100 --out .tmp\\v100-gen
    git worktree remove .tmp\\wt-100

It downloads one set with the 1.0.0 SetSession and its FAKE engine (invented files, no connection: the
keyring is in memory and sockets are blocked), finalizes it (library.json) and saves a settings.json.
Then it copies the JSON and text files it wrote to <out>/root/, every absolute path written as {ROOT},
plus network.json (the fake network) and audio.json (each audio file of the set with its SHA-256 and the
network file it came from: tests/pipeline/v100.py writes the same bytes again, so no audio is stored).
The rows are tracks of the user's public set; folders and peers are invented.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import sys
import threading
from pathlib import Path

SECONDS = 12
NAME = "Set casa 1.0.0"


def _file(peer, path, artist, title, dur=SECONDS, **audio):
    d = {"peer": peer, "path": path, "artist": artist, "title": title, "duration_s": dur, "format": "flac",
         "samplerate": 44100, "bitdepth": 16, "bitrate_kbps": None, "vbr": False,
         "audio": {"lowpass_hz": None, "truncate_to_s": None, "tags": True, "tag_title": None, "tag_artist": None}}
    for k in ("announce_length",):
        if k in audio:
            d[k] = audio.pop(k)
    d["audio"].update(audio)
    return d


# (pos, artist_display, artists, title, version, expected, is_id, network file or None)
ROWS = [
    (1, "Komplex aka Jeroen Search", ["Komplex aka Jeroen Search"], "Inject", None, SECONDS, False, None),
    (2, "Red Rooms", ["Red Rooms"], "Trip", None, SECONDS, False,
     _file("peerA", "@@inventado\\Red_Rooms-Blind_Spot-(PHORUM004)-16BIT-WEB-FLAC-2026-PTC\\04-red_rooms-trip.flac",
           "Red Rooms", "Trip", tags=False)),
    (3, "Kwartz", ["Kwartz"], "Show Me That Light", "Cleric Remix", SECONDS, False,
     _file("peerB", "@@inventado\\Musica Inventada\\Kwartz - Show Me That Light (Cleric Remix).flac", "Kwartz",
           "Show Me That Light (Cleric Remix)")),
    (4, "Rene Wise", ["Rene Wise"], "Dynamic", None, SECONDS, False,
     _file("peerC", "@@inventado\\Musica Inventada\\Rene Wise - Dynamic.flac", "Rene Wise", "Dynamic",
           lowpass_hz=19000)),
    (5, "Justine Perry", ["Justine Perry"], "Nova Voyager", None, SECONDS, False,
     _file("peerC", "@@inventado\\Musica Inventada\\Justine Perry - Nova Voyager.flac", "Justine Perry",
           "Nova Voyager", lowpass_hz=20500)),
    (6, "Border One", ["Border One"], "Spectral Tension", None, SECONDS, False,
     _file("peerD", "@@inventado\\Otra Carpeta\\Border One - Spectral Tension.flac", "Border One",
           "Spectral Tension", lowpass_hz=16500)),
    (7, "GCOD & KYSH Records", ["GCOD", "KYSH Records"], "Incentive Systems", None, SECONDS, False,
     _file("peerB", "@@inventado\\Musica Inventada\\GCOD & KYSH Records - Incentive Systems.flac",
           "GCOD & KYSH Records", "Incentive Systems")),
    (8, "ID", [], "ID", None, None, True, None),
    (9, "13130 Space Project", ["13130 Space Project"], "Talitha", None, SECONDS, False,
     _file("peerE", "@@inventado\\Musica Inventada\\13130 Space Project - Talitha (Original Mix).flac",
           "13130 Space Project", "Talitha", tag_title="Talitha (Original Mix) electronicfresh.com")),
    (10, "Confusion & Tino Machauer", ["Confusion", "Tino Machauer"], "Interchange III", None, SECONDS, False,
     _file("peerF", "@@inventado\\Musica Inventada\\Confusion & Tino Machauer - Interchange III (Radio Edit).flac",
           "Confusion & Tino Machauer", "Interchange III (Radio Edit)", dur=5, announce_length=False)),
    (11, "Miss Kittin & The Hacker", ["Miss Kittin", "The Hacker"], "1982", None, SECONDS, False,
     _file("peerB", "@@inventado\\Musica Inventada\\Miss Kittin & The Hacker - 1982.flac", "Miss Kittin & The Hacker",
           "1982")),
    (12, "Fjaak", ["Fjaak"], "Spirit", "Radio Edit - Kai Remix", SECONDS, False,
     _file("peerG", "@@inventado\\Musica Inventada\\Fjaak - Spirit (Kai Remix) (Radio Edit).flac", "Fjaak",
           "Spirit (Kai Remix) (Radio Edit)")),
]


def _guard_sockets() -> None:
    def refuse(self, address):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise RuntimeError(f"network blocked while writing fixtures: {address!r}")
        return real(self, address)
    real = socket.socket.connect
    socket.socket.connect = refuse


def _memory_keyring() -> None:
    import keyring
    import keyring.backend

    class Memory(keyring.backend.KeyringBackend):
        priority = 1

        def __init__(self):
            super().__init__()
            self.store = {}

        def get_password(self, service, username):
            return self.store.get((service, username))

        def set_password(self, service, username, password):
            self.store[(service, username)] = password

        def delete_password(self, service, username):
            self.store.pop((service, username), None)

    keyring.set_keyring(Memory())


def _redact(obj, root: str):
    pat = re.compile(re.escape(root), re.I)
    if isinstance(obj, str):
        return pat.sub("{ROOT}", obj)
    if isinstance(obj, list):
        return [_redact(x, root) for x in obj]
    if isinstance(obj, dict):
        return {k: _redact(v, root) for k, v in obj.items()}
    return obj


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True, help="checkout of commit 9191dd6 (Tracklister 1.0.0)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    code, out = Path(args.code).resolve(), Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    root = out / "gen"
    (root / "home").mkdir(parents=True)
    os.environ["TRACKLISTER_HOME"] = str(root / "home")
    sys.path[:0] = [str(code / "src"), str(code)]
    _guard_sockets()
    _memory_keyring()

    import tracklister
    from tracklister import config
    from tracklister.core.model import RowStatus, SourceRef, TrackRow
    from tracklister.core.paths import app_paths
    from tracklister.core.settings import Settings, save_settings
    from tracklister.engine.credentials import Credentials
    from tracklister.engine.ratelimit import SearchBudget
    from tracklister.engine.runner import EngineRunner
    from tracklister.engine.spec import fake_engine_spec
    from tracklister.library.index import LibraryIndex
    from tracklister.pipeline.session import SetSession

    if tracklister.__version__ != "1.0.0" or not str(Path(tracklister.__file__)).startswith(str(code)):
        raise SystemExit(f"this must run the 1.0.0 code of {code}, not {tracklister.__file__}")
    paths = app_paths().ensure()
    lib_root = root / "biblioteca"
    net = {"schema": "tracklister.fakenet/1", "search_delay_ms": 0, "ban_after_searches": None, "peers": {},
           "files": [f for *_, f in ROWS if f]}
    net_path = out / "network.json"
    net_path.write_text(json.dumps(net, ensure_ascii=False, indent=1), encoding="utf-8")
    rows = []
    for pos, display, artists, title, version, dur, is_id, _ in ROWS:
        rows.append(TrackRow(pos=pos, title=title, artists=list(artists), artist_display=display, version=version,
                             expected_duration_s=dur, source="youtube_comment", is_id=is_id,
                             status=RowStatus.ID if is_id else RowStatus.OK, download=not is_id,
                             confidence=0.0 if is_id else 0.9))
    settings = Settings(theme="noche", preset_id="lossless", library_root=str(lib_root), first_run_done=True,
                        share_notice_shown=True, legal_notice_accepted=True, listen_port=49998)
    save_settings(paths.settings_file, settings)
    s = SetSession.create(NAME, rows, [SourceRef("youtube_comment", "comentario.txt", detail="youtube_comment:@ejemplo")],
                          settings, lib_root, paths)
    runner = EngineRunner(fake_engine_spec(), SearchBudget(paths.search_budget_file),
                          env={"TRACKLISTER_FAKE_NETWORK": str(net_path)})
    events = []
    s.run(runner, Credentials("usuario-prueba", "clave-prueba"), events.append, threading.Event(), lambda r: set())
    library = LibraryIndex(paths.library_file)
    s.finalize(library)

    rel = lambda p: Path(p).resolve().relative_to(root).as_posix()     # noqa: E731
    dst = out / "root"
    for p in [paths.settings_file, paths.library_file] + sorted(x for x in s.set_dir.rglob("*")
                                                                if x.is_file() and x.suffix in (".json", ".txt")):
        target = dst / rel(p)
        if p in (paths.settings_file, paths.library_file):       # .gitignore hides settings.json/library.json
            target = target.with_name(target.stem + "-1.0.0.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix == ".json":
            target.write_text(json.dumps(_redact(json.loads(p.read_text(encoding="utf-8")), str(root)),
                                         ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            target.write_text(re.sub(re.escape(str(root)), "{ROOT}", p.read_text(encoding="utf-8"), flags=re.I),
                              encoding="utf-8")
    audio = []
    net_index = {}
    for pos, *_, f in ROWS:
        if f:
            net_index[pos] = net["files"].index(f)
    for uid, res in s.doc.results.items():
        if not res.file:
            continue
        p = s.set_dir / res.file
        audio.append({"path": rel(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                      "net_index": net_index[res.pos], "state": str(res.state)})
    (out / "audio.json").write_text(json.dumps(sorted(audio, key=lambda a: a["path"]), ensure_ascii=False, indent=2)
                                    + "\n", encoding="utf-8")
    (out / "keyring.json").write_text(json.dumps({"service": config.KEYRING_SERVICE,
                                                  "account_key": config.KEYRING_ACCOUNT_KEY}, indent=2) + "\n",
                                      encoding="utf-8")
    (out / "README.txt").write_text(
        "Written by tests/fixtures/v100/make_fixtures.py with Tracklister 1.0.0 (commit 9191dd6).\n"
        "Absolute paths are {ROOT}. Audio is regenerated by tests/pipeline/v100.py (same bytes, checked).\n",
        encoding="utf-8")
    for uid, res in sorted(s.doc.results.items(), key=lambda kv: kv[1].pos):
        print(f"{res.pos:02d} {res.state:<18} {res.doubt or '':<10} {res.file or ''}")
    print("library entries:", len(library.entries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
