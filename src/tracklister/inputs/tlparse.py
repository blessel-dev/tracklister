"""Free-text tracklist parser: YouTube/SoundCloud comments and descriptions, pasted text.

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

Ported from the research prototype `fuentes/tlparse.py` (24/24 self-tests, 165 real YouTube
lines). Normalisation now comes from `tracklister.core.textnorm`. Formats added for v1.0
(02 section 3.B "Pendiente en el parser"):

- MixesDB minute markers: "[12] Artista - Titulo" (12 minutes) and "[??] ?";
- a trailing label written with an at sign: "Titulo (X Remix) @ SDL records";
- a version written after a feat group: "Titulo (feat. X) Y Dub".

And for 1.1 (CL-03): a time range before or after the track, "00:00 - 04:30 Artista - Titulo" or
"Artista - Titulo [00:00 - 04:30]", starts at its first time.

API:
    parse_line(line) -> list[ParsedLine]
    parse_text(text, duration=None) -> list[ParsedLine]
    to_track_rows(lines, source, source_url=None) -> list[TrackRow]
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from tracklister.core.model import RowStatus, TrackRow
from tracklister.core.textnorm import VERSION_KW, is_version_group, merge_versions, norm_key, split_artists, version_groups

# ---------------------------------------------------------------- model


@dataclass
class ParsedLine:
    """One track as read from one text line (the prototype's `Row`)."""
    pos: int | None = None
    ts: int | None = None            # seconds into the video/set
    artist: str = ""                 # as written (used for searching)
    artists: list[str] = field(default_factory=list)
    title: str = ""                  # without version or label
    version: str | None = None       # "Kai Van Dongen Remix", "Original Mix", "Edit"...
    feat: str | None = None
    label: str | None = None
    is_id: bool = False
    quality: str = "strong"          # strong | partial
    notes: list[str] = field(default_factory=list)
    raw: str = ""
    ts_minutes: bool = False         # ts came from a MixesDB minute marker "[12]"

    def key(self) -> str:
        return norm_key(f"{self.artist} {self.title}")

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- patterns

DASH_CHARS = "\\-\u2010\u2011\u2012\u2013\u2014\u2015\u2212"  # escaped hyphen: used inside [...]
SPACED_SEP = re.compile(rf"\s+[{DASH_CHARS}]+\s+")
LOOSE_SEP = re.compile(rf"(?<=\w)[{DASH_CHARS}]+\s+|\s+[{DASH_CHARS}]+(?=\w)")
TS_CORE = r"(?:\d{1,2}[:.])?\d{1,2}:\d{2}"
LEAD_TS = re.compile(rf"^[\[\(]?\s*({TS_CORE})\s*[\]\)]?(?=\s|$|[{DASH_CHARS}|:>\]\)])")
TRAIL_TS = re.compile(rf"[\s\[\(]+({TS_CORE})\s*[\]\)]?\s*$")
# a time range «00:00 - 04:30» is the start of the track (CL-03): the end of a leading range, right after the
# start and its separator, and a whole trailing range, whose FIRST time is the start
RANGE_END = re.compile(rf"({TS_CORE})\s*[\]\)]?(?=\s|$)")
TRAIL_RANGE = re.compile(rf"[\s\[\(]+({TS_CORE})\s*[{DASH_CHARS}]+\s*({TS_CORE})\s*[\]\)]?\s*$")
MIXESDB_TS = re.compile(r"^\[\s*(\d{1,3}|\?{1,3})\s*\]\s*")
NUMBERING = re.compile(rf"^(?:#\s?\d{{1,3}}\b[.):]?|\d{{1,3}}\s*[.)\]:]|\d{{1,3}}\s+[{DASH_CHARS}|]"
                       rf"|\d{{1,3}}\s+(?=[\[\(]?{TS_CORE}))\s*")
LEAD_JUNK = re.compile(r"^[^\w\"'\u201c\u201d\u2018\u2019\[\(?]+")
AFTER_TS_JUNK = re.compile(rf"^[\s{DASH_CHARS}|:>\]\)\u2022\u00b7*]+")
# VERSION_KW comes from core.textnorm (the same words as the verifier: 'live' too, audit round 4, B3)
UNREL_KW = re.compile(r"\b(unreleased|forthcoming|upcoming|dubplate|white ?label|wip|soon)\b", re.I)
FEAT_KW = re.compile(r"^\s*(?:feat\.?|ft\.?|featuring)\s+(.+)$", re.I)
AT_LABEL = re.compile(r"\s@\s+([^@()\[\]]+?)\s*$")           # "... @ SDL records"
BPM_NOTE = re.compile(r"^@?\s*\d{2,3}\s*bpm$", re.I)          # "(@150 bpm)" is not a label
FEAT_THEN_VERSION = re.compile(
    r"^(.+?)\s*[\(\[]\s*(?:feat\.?|ft\.?|featuring)\s+([^()\[\]]+?)\s*[\)\]]\s+(.+)$", re.I)
TRAILING_GROUPS = re.compile(r"^(.*?)((?:\s*[\(\[][^()\[\]]*[\)\]])*)\s*$")
ID_WORDS = {"id", "track id", "unknown", "unreleased", "tba", "tbc", "untitled id"}
LINK = re.compile(r"https?://|www\.", re.I)
OTHER_VIDEO = re.compile(r"youtu\.be/|youtube\.com/(?:watch|live|@|channel|c/)|soundcloud\.com/|mixcloud\.com/",
                         re.I)


def ts_to_s(ts: str) -> int:
    parts = [int(p) for p in re.split(r"[:.]", ts)]
    s = 0
    for p in parts:
        s = s * 60 + p
    return s


def is_id_text(s: str) -> bool:
    raw = (s or "").strip()
    if re.fullmatch(r"[?\uff1f!.\s]*\?[?\uff1f!.\s]*", raw):
        return True
    return norm_key(raw) in ID_WORDS


# ---------------------------------------------------------------- one line


def _put_label(row: ParsedLine, text: str) -> None:
    if not row.label:
        row.label = text
    else:
        row.notes.append(text)


def _clean_title(row: ParsedLine, title: str) -> None:
    t = title.strip()
    m = AT_LABEL.search(t)
    if m and m.start() > 0:
        lab = m.group(1).strip(" -,;")
        if lab:
            if BPM_NOTE.match(lab):
                row.notes.append(lab)
            else:
                _put_label(row, lab)
        t = t[:m.start()].rstrip()
    after_feat: str | None = None
    m = FEAT_THEN_VERSION.match(t)
    if m:
        tail = TRAILING_GROUPS.match(m.group(3))
        core, groups = tail.group(1).strip(), tail.group(2)
        if core and VERSION_KW.search(core):
            row.feat = row.feat or m.group(2).strip()
            after_feat = core
            t = m.group(1).rstrip() + groups
    # version groups, right to left: core.textnorm.merge_versions keeps them all (round 4, second review)
    versions: list[str] = []
    while True:  # trailing (...) or [...] groups
        m = re.search(r"\s*([\(\[])\s*([^()\[\]]*?)\s*[\)\]]\s*$", t)
        if not m or m.start() == 0:
            break
        inner = m.group(2).strip()
        t = t[:m.start()].rstrip()
        if not inner:
            continue
        fm = FEAT_KW.match(inner)
        if fm:
            row.feat = row.feat or fm.group(1).strip()
        elif UNREL_KW.search(inner):
            row.notes.append("unreleased/forthcoming")
            rest = UNREL_KW.sub("", inner).strip(" -:")
            if rest and not row.label:
                row.label = rest
        elif BPM_NOTE.match(inner):
            row.notes.append(inner)
        elif is_version_group(inner):
            versions.append(inner)
        elif not row.label:
            row.label = inner
        else:
            row.notes.append(inner)
    # written order: 'Title Original Mix (feat. X) Y Dub (Z) [W]' -> Original Mix, Y Dub, Z, W
    written = ([after_feat] if after_feat else []) + versions[::-1]
    m = re.search(r"\s+(?:feat\.?|ft\.?|featuring)\s+(.+)$", t, re.I)
    if m:
        row.feat = row.feat or m.group(1).strip()
        t = t[:m.start()]
    m = re.search(r"\s+((?:original|extended|radio|club|dub|vocal|instrumental)\s+(?:mix|edit|version))$", t, re.I)
    if m:
        written.insert(0, m.group(1))
        t = t[:m.start()]
    if written:
        _set_version(row, written)
    row.title = t.strip(" -,;\"'\u201c\u201d\u2018\u2019")


def _set_version(row: ParsedLine, groups: list[str]) -> None:
    """row.version from its groups with the shared rule; the original/extended groups it leaves out go
    to the notes (the remixer never does: it is in the version, audit round 4, second review)."""
    row.version = merge_versions([row.version] + groups)
    kept = {norm_key(g, drop_original=False) for g in version_groups(row.version)}
    for g in groups:
        for part in version_groups(g):
            if norm_key(part, drop_original=False) not in kept and part not in row.notes:
                row.notes.append(part)


def _set_artist(row: ParsedLine, a: str) -> None:
    a = a.strip(" ,;:-\"'\u201c\u201d\u2018\u2019")
    m = re.search(r"\s+(?:feat\.?|ft\.?|featuring)\s+(.+)$", a, re.I)
    if m:
        row.feat = row.feat or m.group(1).strip()
        a = a[:m.start()].strip()
    row.artist = re.sub(r"\s+", " ", a)
    row.artists = split_artists(row.artist)


def _split_top(s: str, rx: re.Pattern, maxsplit: int = 0) -> list[str]:
    """Like rx.split(s) but ignores separators inside (), [] or {}."""
    depth, masked = 0, []
    for ch in s:
        if ch in "([{":
            depth += 1
            masked.append("_")
        elif ch in ")]}" and depth:
            depth -= 1
            masked.append("_")
        else:
            masked.append("_" if depth else ch)
    m = "".join(masked)
    parts, last = [], 0
    for n, mt in enumerate(rx.finditer(m), 1):
        parts.append(s[last:mt.start()])
        last = mt.end()
        if maxsplit and n >= maxsplit:
            break
    parts.append(s[last:])
    return parts


def parse_track(s: str, has_ts: bool) -> ParsedLine | None:
    """'Artist - Title (X Remix) [LABEL]' -> ParsedLine. None if it does not look like a track."""
    s = s.strip().strip("|").strip()
    row = ParsedLine(raw=s)
    if not s:
        return None
    if is_id_text(s) or re.fullmatch(rf"(?i)id\s*[{DASH_CHARS}]+\s*id", s):
        row.artist, row.title, row.is_id = "ID", "ID", True
        return row
    m = re.match(rf'^["\u201c](.+?)["\u201d]\s*[{DASH_CHARS}]+\s*(.+)$', s)
    if m:
        a, t, extra = m.group(1), m.group(2), []
    else:
        parts = _split_top(s, SPACED_SEP)
        if len(parts) < 2:
            parts = _split_top(s, LOOSE_SEP, maxsplit=1)
        if len(parts) >= 2:
            a, t, extra = parts[0], parts[1], parts[2:]
        else:
            m = re.match(r"^(.+?)\s+[\u2018\u201c\"](.+?)[\u2019\u201d\"]\s*$", s)
            if m:
                a, t, extra = m.group(1), m.group(2), []
            elif has_ts:
                row.title, row.quality = s, "partial"
                row.notes.append("sin separador artista-titulo")
                return row
            else:
                return None
    _set_artist(row, a)
    _clean_title(row, t)
    for e in extra:
        if norm_key(e) == norm_key(row.artist):
            continue
        if is_version_group(e):          # 'A - T (Kai Remix) - Radio Edit': one more group, never the label
            _set_version(row, [e.strip()])
        elif not row.label:
            row.label = e.strip()
        row.notes.append("3+ partes: revisar")
    a_id, t_id = is_id_text(row.artist), (is_id_text(row.title) or bool(UNREL_KW.fullmatch(row.title.strip())))
    if t_id:
        row.is_id = True
        if UNREL_KW.fullmatch(row.title.strip()):
            row.notes.append("unreleased")
        if a_id:
            row.artist, row.artists = "ID", []
    elif a_id:
        row.quality = "partial"
        row.notes.append("artista desconocido")
    if not row.title and not row.is_id:
        return None
    return row


def parse_line(line: str) -> list[ParsedLine]:
    s = re.sub(r"\s+", " ", line.replace("\t", " ")).strip()
    s = LEAD_JUNK.sub("", s)
    if not s:
        return []
    ts = None
    minutes = False
    marker = False
    m = LEAD_TS.match(s)
    if not m:
        mx = MIXESDB_TS.match(s)
        if mx:
            marker = True
            if mx.group(1).isdigit():
                ts, minutes = int(mx.group(1)) * 60, True
            s = AFTER_TS_JUNK.sub("", s[mx.end():])
        else:
            n = NUMBERING.match(s)
            if n:
                s = LEAD_JUNK.sub("", s[n.end():])
                m = LEAD_TS.match(s)
    if m:
        ts = ts_to_s(m.group(1))
        s = AFTER_TS_JUNK.sub("", s[m.end():])
        e = RANGE_END.match(s)        # «00:00 - 04:30 Artista - Título»: «04:» is not a track number (CL-03)
        if e:
            s = AFTER_TS_JUNK.sub("", s[e.end():])
        n = NUMBERING.match(s)
        if n:
            s = s[n.end():]
    elif not marker:
        m = TRAIL_RANGE.search(s) or TRAIL_TS.search(s)
        if m and m.start() > 3:
            ts = ts_to_s(m.group(1))
            s = s[:m.start()].rstrip(" -|")
    s = s.strip()
    if not s:
        return []
    rows: list[ParsedLine] = []
    for i, seg in enumerate(re.split(r"\s+w/\s*", s, flags=re.I)):
        for r in _split_vs(seg, ts is not None or marker):
            if i > 0:
                r.notes.append("w/ (tocado a la vez)")
            r.ts = ts
            r.ts_minutes = minutes
            r.raw = line.strip()
            rows.append(r)
    return rows


def _split_vs(seg: str, has_ts: bool) -> list[ParsedLine]:
    base = parse_track(seg, has_ts)
    if base is None:
        return []
    vs = re.compile(r"\s+vs\.?\s+", re.I)
    a_parts, t_parts = vs.split(base.artist), vs.split(base.title)
    if len(a_parts) >= 2 and len(a_parts) == len(t_parts):
        out = []
        for a, t in zip(a_parts, t_parts):
            r = parse_track(f"{a} - {t}", has_ts)
            if r:
                r.notes.append("vs (mashup)")
                out.append(r)
        return out
    if len(a_parts) >= 2 or len(t_parts) >= 2:
        base.notes.append("vs")
    return [base]


def _minute_markers_as_numbering(rows: list[ParsedLine]) -> None:
    """'[1] A - x', '[2] B - y', '[3] C - z' is a numbered list, not minutes 1, 2, 3."""
    marked = [r for r in rows if r.ts_minutes]
    values: list[int] = []
    prev = None
    for r in marked:
        k = (r.raw, r.ts)
        if k != prev:
            values.append((r.ts or 0) // 60)
            prev = k
    if len(values) >= 3 and all(b - a == 1 for a, b in zip(values, values[1:])):
        for r in marked:
            r.ts, r.ts_minutes = None, False
            r.notes.append("[n] parece numeracion, no minutos")


def parse_text(text: str, duration: float | None = None) -> list[ParsedLine]:
    rows: list[ParsedLine] = []
    for line in (text or "").splitlines():
        rows.extend(parse_line(line))
    _minute_markers_as_numbering(rows)
    for i, r in enumerate(rows, 1):
        r.pos = i
        if duration and r.ts is not None and r.ts > duration + 30:
            r.notes.append("timestamp fuera del video")
    return rows


# ---------------------------------------------------------------- to the shared model


def needs_review(line: ParsedLine) -> bool:
    """'revisar' rows (02 section 5.10): no artist/title separator, unknown artist or 3+ parts."""
    return not line.is_id and (line.quality == "partial" or any("revisar" in n for n in line.notes))


def to_track_rows(lines: list[ParsedLine], source: str, source_url: str | None = None) -> list[TrackRow]:
    """ParsedLine -> TrackRow. `pos` is 1..n in text order; `ts_end` is the next later start.

    ID rows: status ID, unchecked, confidence 0. 'Revisar' rows: unchecked, confidence 0.4.
    Strong rows: confidence 0.7 (0.9 once enrichment confirms them).
    """
    rows: list[TrackRow] = []
    for i, ln in enumerate(lines, 1):
        artist_display, artists = ln.artist, list(ln.artists)
        if is_id_text(artist_display):
            artist_display, artists = ("ID" if ln.is_id else ""), []
        if ln.is_id:
            status, download, confidence = RowStatus.ID, False, 0.0
        elif needs_review(ln):
            status, download, confidence = RowStatus.REVISAR, False, 0.4
        else:
            status, download, confidence = RowStatus.OK, True, 0.7
        rows.append(TrackRow(
            pos=i, title=ln.title, artists=artists, artist_display=artist_display, version=ln.version,
            feat=ln.feat, label=ln.label, ts_start=ln.ts, source=source, source_url=source_url,
            confidence=confidence, is_id=ln.is_id, status=status, notes=list(ln.notes), raw=ln.raw,
            download=download))
    for i, r in enumerate(rows):
        if r.ts_start is None:
            continue
        r.ts_end = next((x.ts_start for x in rows[i + 1:] if x.ts_start is not None and x.ts_start > r.ts_start),
                        None)
    return rows
