"""Install the 1.0.0 fixtures (tests/fixtures/v100, written by the 1.0.0 code) in a temp folder. 1.0.1, R8.

SPDX-License-Identifier: GPL-3.0-or-later

The JSON and text files are copied with {ROOT} turned into the temp folder (local_path: with this system's
separator, 1.1b); 'settings-1.0.0.json' and 'library-1.0.0.json' get their real names (the repo's .gitignore
hides those). The audio is written
again with the very parameters the 1.0.0 fake engine used (tests/fakes/fake_engine.py of 9191dd6,
write_audio), and its SHA-256 is compared with the one 1.0.0 recorded.
"""
from __future__ import annotations

import hashlib
import json
import os
import zlib
from dataclasses import dataclass
from pathlib import Path

from tests.fakes import synth

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "v100"
SET_NAME = "Set casa 1.0.0"


@dataclass
class V100:
    root: Path
    home: Path
    set_dir: Path
    library_root: Path
    network: Path            # the fake network of the 1.0.0 run (a copy that tests may extend)
    audio: list[dict]        # path, sha256 (1.0.0), net_index, state, same_bytes (regenerated == 1.0.0)
    keyring: dict            # the 1.0.0 keyring layout: service, account_key


LONG_PREFIX = "\\\\?\\"


def local_path(text: str, root: str, sep: str = os.sep) -> str:
    """{ROOT} -> the temp folder, as THIS system writes paths. Tracklister 1.0.0 only ever ran on Windows, so its
    files hold Windows paths: on Windows they are installed byte for byte as before. Anywhere else (the macOS
    runner) a path that starts at {ROOT}, with or without the \\\\?\\ prefix 1.0.0 put on long paths, gets this
    system's separator and no prefix, as if it had been written here (brief mac-1b). The Soulseek paths
    ('@@x\\...', 'Musica Inventada\\...') never start at {ROOT}: they keep their backslashes everywhere."""
    if sep == "\\" or "{ROOT}" not in text:
        return text.replace("{ROOT}", root)
    head, _, tail = text.partition("{ROOT}")
    if head not in ("", LONG_PREFIX):
        return text.replace("{ROOT}", root)
    return root + tail.replace("\\", sep)


def _subst(obj, root: str):
    if isinstance(obj, str):
        return local_path(obj, root)
    if isinstance(obj, list):
        return [_subst(x, root) for x in obj]
    if isinstance(obj, dict):
        return {k: _subst(v, root) for k, v in obj.items()}
    return obj


def write_audio_100(f: dict, dst: Path) -> None:
    """tests/fakes/fake_engine.py::write_audio of 1.0.0 (9191dd6), for files that carry artist and title."""
    a = f.get("audio") or {}
    tags = None
    if a.get("tags", True):
        tags = {"artist": a.get("tag_artist") or f.get("artist"), "title": a.get("tag_title") or f.get("title")}
        if a.get("cover"):
            tags["cover"] = synth.tiny_png()
    ext = f["path"].rsplit(".", 1)[-1].lower()
    synth.make_track(dst, fmt=f.get("format") or ext, seconds=float(f.get("duration_s") or 20),
                     samplerate=int(f.get("samplerate") or 44100), bitdepth=int(f.get("bitdepth") or 16),
                     lowpass_hz=a.get("lowpass_hz"), mp3_kbps=f.get("real_kbps") or f.get("bitrate_kbps"),
                     vbr=bool(f.get("vbr")), tags=tags, truncate_to_s=a.get("truncate_to_s"),
                     seed=int(a.get("seed", zlib.crc32(f["path"].encode("utf-8")) % 1000)),
                     float_pcm=bool(a.get("float_pcm")), low_treble=bool(a.get("low_treble")),
                     mp3_info_frame=not bool(a.get("no_info_frame")), subtype=a.get("subtype"),
                     channels=int(a.get("channels") or 2))


def install_v100(root: Path, monkeypatch) -> V100:
    root = Path(root)
    src_root = FIXTURES / "root"
    for src in sorted(src_root.rglob("*")):
        if not src.is_file():
            continue
        dst = root / src.relative_to(src_root)
        if dst.name.endswith("-1.0.0.json"):
            dst = dst.with_name(dst.name[:-len("-1.0.0.json")] + ".json")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == ".json":
            data = _subst(json.loads(src.read_text(encoding="utf-8")), str(root))
            dst.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            dst.write_text(src.read_text(encoding="utf-8").replace("{ROOT}", str(root)), encoding="utf-8")
    net = json.loads((FIXTURES / "network.json").read_text(encoding="utf-8"))
    net_path = root / "network.json"
    net_path.write_text(json.dumps(net, ensure_ascii=False, indent=1), encoding="utf-8")
    audio = json.loads((FIXTURES / "audio.json").read_text(encoding="utf-8"))
    for a in audio:
        dst = root / a["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        write_audio_100(net["files"][a["net_index"]], dst)
        a["same_bytes"] = hashlib.sha256(dst.read_bytes()).hexdigest() == a["sha256"]
    monkeypatch.setenv("TRACKLISTER_HOME", str(root / "home"))
    keyring = json.loads((FIXTURES / "keyring.json").read_text(encoding="utf-8"))
    return V100(root, root / "home", root / "biblioteca" / SET_NAME, root / "biblioteca", net_path, audio, keyring)
