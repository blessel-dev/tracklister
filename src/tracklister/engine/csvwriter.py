"""The engine's input CSV: exactly the artist/title/length strings the app wants searched.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Format (01 section 6.3, ENGINE-FACTS.md): header "Artist","Title","Length"; every field quoted;
UTF-8 without BOM; "\\n" line ends. Never an id/url/uri column (the engine reads those as links),
never an empty title (the engine would turn the row into an album/artist-only search).
`snum` is the 1-based data-row number the engine exposes as {snum} in --name-format.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from tracklister.core.model import TrackRow, VersionKind
from tracklister.core.textnorm import classify_version, nfc

HEADER = ("Artist", "Title", "Length")


@dataclass(frozen=True)
class ManifestItem:
    snum: int
    uid: str
    pos: int
    artist: str
    title: str
    length: int | None

    def to_dict(self) -> dict:
        return {"snum": self.snum, "uid": self.uid, "pos": self.pos, "artist": self.artist,
                "title": self.title, "length": self.length}

    @classmethod
    def from_dict(cls, d: dict) -> "ManifestItem":
        return cls(int(d["snum"]), str(d["uid"]), int(d["pos"]), str(d["artist"]), str(d["title"]),
                   None if d.get("length") is None else int(d["length"]))


def _clean(s: str) -> str:
    # One physical line per record: the engine's CSV reader is line based.
    return nfc(s.replace("\r", " ").replace("\n", " "))


def engine_title(row: TrackRow) -> str:
    """title_with_version, except an ORIGINAL version (or none) sends the base title."""
    if not row.version or classify_version(row.version) == VersionKind.ORIGINAL:
        return _clean(row.title)
    return _clean(row.title_with_version)


def engine_artist(row: TrackRow) -> str:
    return _clean(row.search_artist)


def _q(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def write_engine_csv(rows: Sequence[TrackRow], path: Path) -> list[ManifestItem]:
    """Write the CSV for one pass and return the snum -> row manifest (pos order)."""
    ordered = sorted(rows, key=lambda r: r.pos)
    items: list[ManifestItem] = []
    lines = [",".join(_q(h) for h in HEADER)]
    for snum, row in enumerate(ordered, start=1):
        if not row.download:
            raise ValueError(f"la fila {row.pos} no está marcada para descargar")
        title = engine_title(row)
        if not title.strip():
            raise ValueError(f"la fila {row.pos} no tiene título: nunca se envía al motor")
        artist = engine_artist(row)
        length = int(row.expected_duration_s) if row.expected_duration_s else None
        lines.append(",".join((_q(artist), _q(title), _q("" if length is None else str(length)))))
        items.append(ManifestItem(snum, row.uid, row.pos, artist, title, length))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return items
