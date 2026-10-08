"""Named offline scenarios: tracklist rows + a fake Soulseek network for tests/fakes/fake_engine.py.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

build_scenario(name, tmp_dir) -> (rows, network_json_path). Durations are short (tens of seconds)
so synthetic audio stays fast; each row's expected_duration_s matches its "right" file.

Fake network JSON (tracklister.fakenet/1). Optional per-file extensions used here:
`announce_length`/`announce_samplerate` (False = the peer does not broadcast it, so the engine
cannot filter on it), `real_kbps` (actual MP3 bitrate when the announced `bitrate_kbps` is null),
`audio.cover`, `audio.low_treble`, `audio.float_pcm`, `audio.seed`.
"""
from __future__ import annotations

import json
from pathlib import Path

from tracklister.core.model import RowStatus, TrackRow

SCENARIOS = (
    "correcto", "version_equivocada", "radio_edit", "flac_transcodificado", "truncado", "sin_tags",
    "sin_resultados", "peer_timeout", "duplicado_entre_sets", "rerun", "nombres_raros", "ban",
    "mp3_vbr", "mp3_256", "cdj_flac_96k", "todos_los_estados", "login_falla",
)

# Preset each scenario is meant to run with (default "lossless").
SCENARIO_PRESET = {"mp3_vbr": "solo_mp3_320", "mp3_256": "solo_mp3_320", "cdj_flac_96k": "cdj_antiguos"}


def row(pos: int, artist: str, title: str, version: str | None = None, dur: int | None = None,
        **kw) -> TrackRow:
    artists = kw.pop("artists", None) or [a.strip() for a in artist.replace(" & ", "&").split("&")]
    return TrackRow(pos=pos, title=title, artists=artists, artist_display=artist, version=version,
                    expected_duration_s=dur, source="tabla", **kw)


def file(peer: str, path: str, artist: str, title: str, dur: float | None, fmt: str = "flac", **kw) -> dict:
    audio = kw.pop("audio", {})
    d = {"peer": peer, "path": path, "artist": artist, "title": title, "duration_s": dur, "format": fmt,
         "samplerate": kw.pop("samplerate", 44100), "bitdepth": kw.pop("bitdepth", 16),
         "bitrate_kbps": kw.pop("bitrate_kbps", None), "vbr": kw.pop("vbr", False),
         "audio": {"lowpass_hz": None, "truncate_to_s": None, "tags": True, "tag_title": None,
                   "tag_artist": None, **audio}}
    d.update(kw)
    return d


def _net(files: list[dict], *, peers: dict | None = None, ban_after: int | None = None,
         delay_ms: int = 0) -> dict:
    return {"schema": "tracklister.fakenet/1", "search_delay_ms": delay_ms, "ban_after_searches": ban_after,
            "peers": peers or {}, "files": files}


def _base_good() -> tuple[list[TrackRow], list[dict]]:
    rows = [row(1, "Fjaak", "Spirit", dur=30),
            row(2, "Chris Liebing", "Higher Things", "FJAAK Remix", dur=32)]
    files = [file("peerA", "@@musica\\Fjaak\\Live 2026\\Fjaak - Spirit.flac", "Fjaak", "Spirit", 30),
             file("peerB", "@@techno\\Chris Liebing\\Remixes\\Chris Liebing - Higher Things (FJAAK Remix).flac",
                  "Chris Liebing", "Higher Things (FJAAK Remix)", 32)]
    return rows, files


def _scenario(name: str, tmp: Path) -> tuple[list[TrackRow], dict]:
    if name in ("correcto", "rerun"):
        rows, files = _base_good()
        return rows, _net(files)
    if name == "login_falla":
        rows, files = _base_good()
        net = _net(files)
        net["login_fails"] = True
        return rows, net
    if name == "version_equivocada":
        return ([row(1, "Fjaak", "Spirit", dur=30)],
                _net([file("peerA", "@@x\\Fjaak\\Fjaak - Spirit (Kai Van Dongen Remix).flac", "Fjaak",
                           "Spirit (Kai Van Dongen Remix)", 30)]))
    if name == "radio_edit":
        return ([row(1, "Blasha & Allatt", "Dust 1", dur=40)],
                _net([file("peerA", "@@x\\Blasha\\Blasha & Allatt - Dust 1 (Radio Edit).flac", "Blasha & Allatt",
                           "Dust 1 (Radio Edit)", 18, announce_length=False)]))
    if name == "flac_transcodificado":
        return ([row(1, "DJ Dextro", "Covil dos Abutres", dur=30)],
                _net([file("peerA", "@@x\\DJ Dextro\\DJ Dextro - Covil dos Abutres.flac", "DJ Dextro",
                           "Covil dos Abutres", 30, audio={"lowpass_hz": 16000})]))
    if name == "truncado":
        return ([row(1, "Roll Dann", "Mercy", dur=30)],
                _net([file("peerA", "@@x\\Roll Dann\\Roll Dann - Mercy.flac", "Roll Dann", "Mercy", 30,
                           audio={"truncate_to_s": 12})]))
    if name == "sin_tags":
        return ([row(1, "Sigur R\u00f3s", "Gla\u00f0ur", dur=26)],
                _net([file("peerA", "@@x\\Sigur R\u00f3s\\Sigur R\u00f3s - Gla\u00f0ur.flac", "Sigur R\u00f3s",
                           "Gla\u00f0ur", 26, audio={"tags": False})]))
    if name == "sin_resultados":
        return [row(1, "Nadie Conocido", "Tema Inexistente", dur=30)], _net([])
    if name == "peer_timeout":
        return ([row(1, "Fjaak", "Spirit", dur=30)],
                _net([file("lento", "@@x\\Fjaak\\Fjaak - Spirit.flac", "Fjaak", "Spirit", 30)],
                     peers={"lento": {"timeout": True}}))
    if name == "duplicado_entre_sets":
        rows = [row(1, "Fjaak", "Spirit", dur=30), row(2, "Kobosil", "Aggression", dur=28)]
        _, files = _base_good()
        files.append(file("peerC", "@@x\\Kobosil\\Kobosil - Aggression.flac", "Kobosil", "Aggression", 28))
        return rows, _net(files)
    if name == "nombres_raros":
        long_title = "Una Cancion Con Un Titulo Larguisimo " * 6
        long_title = long_title.strip()
        rows = [row(1, "AC/DC", 'What? <Live>: "Raw"', dur=24),
                row(2, "\u00d1u Sound", "Canci\u00f3n del Ni\u00f1o", dur=25),
                row(3, "CON", "AUX", dur=22),
                row(4, "Larga", long_title, dur=21)]
        files = [file("peerA", "@@x\\ACDC\\AC-DC - What? <Live>: \"Raw\".flac", "AC/DC", 'What? <Live>: "Raw"', 24),
                 file("peerA", "@@x\\Nu\\\u00d1u Sound - Canci\u00f3n del Ni\u00f1o.flac", "\u00d1u Sound",
                      "Canci\u00f3n del Ni\u00f1o", 25),
                 file("peerA", "@@x\\CON\\CON - AUX.flac", "CON", "AUX", 22),
                 file("peerA", f"@@x\\Larga\\Larga - {long_title}.flac", "Larga", long_title, 21)]
        return rows, _net(files)
    if name == "ban":
        rows, files = _base_good()
        rows.append(row(3, "Kobosil", "Aggression", dur=28))
        files.append(file("peerC", "@@x\\Kobosil\\Kobosil - Aggression.flac", "Kobosil", "Aggression", 28))
        return rows, _net(files, ban_after=1)
    if name == "mp3_vbr":
        return ([row(1, "Fjaak", "Spirit", dur=30)],
                _net([file("peerA", "@@x\\Fjaak\\Fjaak - Spirit.mp3", "Fjaak", "Spirit", 30, fmt="mp3",
                           vbr=True)]))
    if name == "mp3_256":
        return ([row(1, "Fjaak", "Spirit", dur=30)],
                _net([file("peerA", "@@x\\Fjaak\\Fjaak - Spirit.mp3", "Fjaak", "Spirit", 30, fmt="mp3",
                           real_kbps=256)]))
    if name == "cdj_flac_96k":
        return ([row(1, "Fjaak", "Spirit", dur=20)],
                _net([file("peerA", "@@x\\Fjaak\\Fjaak - Spirit.flac", "Fjaak", "Spirit", 20, samplerate=96000,
                           bitdepth=24, announce_samplerate=False, audio={"cover": True})]))
    if name == "todos_los_estados":
        rows = [row(1, "Fjaak", "Spirit", dur=30),
                row(2, "Fjaak", "Raw", dur=30),
                row(3, "Nadie Conocido", "Tema Inexistente", dur=30),
                row(4, "Kobosil", "Aggression", dur=28),
                row(5, "Roll Dann", "Mercy", dur=30),
                row(6, "Chris Liebing", "Higher Things", "FJAAK Remix", dur=32),
                row(7, "ID", "ID", is_id=True, status=RowStatus.ID, download=False, confidence=0.0)]
        files = [file("peerA", "@@x\\Fjaak\\Fjaak - Spirit.flac", "Fjaak", "Spirit", 30),
                 file("peerA", "@@x\\Fjaak\\Fjaak - Raw (Kai Van Dongen Remix).flac", "Fjaak",
                      "Raw (Kai Van Dongen Remix)", 30),
                 # an MP3 renamed .flac: the engine trusts the extension, the app reads the header
                 file("peerC", "@@x\\Kobosil\\Kobosil - Aggression.flac", "Kobosil", "Aggression", 28, fmt="mp3",
                      real_kbps=320),
                 file("lento", "@@x\\Roll Dann\\Roll Dann - Mercy.flac", "Roll Dann", "Mercy", 30),
                 file("peerB", "@@x\\Chris Liebing\\Chris Liebing - Higher Things (FJAAK Remix).flac",
                      "Chris Liebing", "Higher Things (FJAAK Remix)", 32)]
        return rows, _net(files, peers={"lento": {"timeout": True}})
    raise KeyError(name)


def build_scenario(name: str, tmp_dir: Path) -> tuple[list[TrackRow], Path]:
    tmp_dir = Path(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    rows, net = _scenario(name, tmp_dir)
    p = tmp_dir / f"fakenet-{name}.json"
    p.write_text(json.dumps(net, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows, p
