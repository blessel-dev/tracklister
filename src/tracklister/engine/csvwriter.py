"""The engine's input CSV: exactly the artist/title/length strings the app wants searched.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Format (01 section 6.3, ENGINE-FACTS.md): header "Artist","Title","Length"; every field quoted;
UTF-8 without BOM; "\\n" line ends. Never an id/url/uri column (the engine reads those as links),
never an empty title (the engine would turn the row into an album/artist-only search).
`snum` is the 1-based data-row number the engine exposes as {snum} in --name-format.

Search variants (1.0.1, R4): a row that found nothing can be searched again with another spelling
(row_variants: its aliases, the dotted and the letter-digit forms). write_engine_csv(queries=...) sends
that spelling instead; the manifest records what was sent, so the outputs still map to the row.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from tracklister.core.aliases import search_variants
from tracklister.core.model import TrackRow, VersionKind
from tracklister.core.textnorm import classify_version, merge_versions, nfc, remixer_of, version_groups

HEADER = ("Artist", "Title", "Length")


@dataclass(frozen=True)
class SearchQuery:
    """What the engine is asked for one row: the Artist and Title columns of its CSV line."""
    artist: str
    title: str


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
    """The text --strict-title must find in the file name (as is, brackets included).

    - No version, or an ORIGINAL one: the base title.
    - One version group (or only original/extended ones): title_with_version, as always.
    - Several groups (audit round 4, second review): the base title with the first group that names a
      remixer ('Spirit (Kai Remix)' for 'Kai Remix - Radio Edit'), else with the rightmost group. The
      engine then demands the remixer and lets its edits through; the verification and --length-tol
      tell them apart. 'Spirit (Radio Edit)' would have let the original's radio edit through instead."""
    version = merge_versions([row.version])
    if not version or classify_version(version) == VersionKind.ORIGINAL:
        return _clean(row.title)
    groups = version_groups(version)
    if len(groups) > 1:
        named = [g for g in groups if remixer_of(g)]
        version = named[0] if named else groups[-1]
    return _clean(f"{row.title} ({version})")


def engine_artist(row: TrackRow) -> str:
    return _clean(row.search_artist)


def row_variants(row: TrackRow) -> list[SearchQuery]:
    """The other spellings to search when the row as written found nothing (R4), best first, at most
    core.aliases.MAX_VARIANTS and never the row's own query: each alias alone ('Komplex aka Jeroen Search'
    -> 'Komplex', then 'Jeroen Search'), the dotted form ('Vkn modular') and the letter-digit ones ('TR 440',
    'TR-440'). The title keeps its version text, so --strict-title still demands the right version.
    The row itself (its artist display, its file name) never changes."""
    return [SearchQuery(a, t) for a, t in search_variants(engine_artist(row), engine_title(row))]


def _q(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def write_engine_csv(rows: Sequence[TrackRow], path: Path, *,
                     queries: Mapping[str, SearchQuery] | None = None) -> list[ManifestItem]:
    """Write the CSV for one pass and return the snum -> row manifest (pos order).

    `queries[uid]` replaces that row's Artist/Title with another spelling (a search variant); the
    manifest item records what was actually sent. Rows without an entry are written as always."""
    ordered = sorted(rows, key=lambda r: r.pos)
    items: list[ManifestItem] = []
    lines = [",".join(_q(h) for h in HEADER)]
    for snum, row in enumerate(ordered, start=1):
        if not row.download:
            raise ValueError(f"la fila {row.pos} no está marcada para descargar")
        q = (queries or {}).get(row.uid)
        title = _clean(q.title) if q is not None else engine_title(row)
        if not title.strip():
            raise ValueError(f"la fila {row.pos} no tiene título: nunca se envía al motor")
        artist = _clean(q.artist) if q is not None else engine_artist(row)
        length = int(row.expected_duration_s) if row.expected_duration_s else None
        lines.append(",".join((_q(artist), _q(title), _q("" if length is None else str(length)))))
        items.append(ManifestItem(snum, row.uid, row.pos, artist, title, length))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return items
