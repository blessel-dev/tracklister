"""Pick the best tracklist among a video's description, chapters and comments, then merge.

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

Ported from the research prototype `fuentes/tlselect.py` (5/5 real sets chosen right, one spam
list rejected). Score per candidate:
  base = strong rows + 0.5*IDs + 0.4*partial rows (partials count only with >= 3 strong rows)
  x1.25 if >= 70% of rows have a timestamp; x0.8 if timestamps are not monotonic; x0.7 if they
  fall outside the video
  + bonus: pinned (+4), author = channel (+4), author ~ DJ name in the title (+5),
    the word 'tracklist/setlist' (+2), log10(likes+1)
  x0.3 if a comment links to ANOTHER video/mix (typical self-promotion)
  x(0.55 + 0.45*consensus) when >= 2 candidates have >= 3 rows: consensus = share of its rows
  that also appear in another candidate (this drops spam lists).
Merge: the winner is the base; missing timestamps/version/label are copied from the other
candidates by aligning rows in order (difflib), so repeated rows like 'Unreleased' stay apart.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from rapidfuzz import fuzz

from tracklister.core.textnorm import norm_key
from tracklister.inputs.tlparse import OTHER_VIDEO, ParsedLine, parse_text


@dataclass
class Candidate:
    """One possible tracklist inside a video's metadata."""
    source: str                     # description | chapters | comment
    text: str
    author: str | None = None
    likes: int = 0
    pinned: bool = False
    uploader: bool = False
    rows: list[ParsedLine] = field(default_factory=list)
    score: float = 0.0
    consensus: float | None = None
    why: list[str] = field(default_factory=list)

    @property
    def strong(self) -> int:
        return sum(1 for r in self.rows if r.quality == "strong" and not r.is_id)

    def summary(self) -> dict:
        return {"source": self.source, "author": self.author, "likes": self.likes, "pinned": self.pinned,
                "uploader": self.uploader, "rows": len(self.rows), "strong": self.strong,
                "ids": sum(r.is_id for r in self.rows), "score": round(self.score, 2),
                "consensus": None if self.consensus is None else round(self.consensus, 2), "why": self.why}


def _fmt(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def dj_names_from_title(title: str) -> list[str]:
    t = re.split(r"\s+[|@\-\u2013\u2014]\s+|\s+at\s+|:", title or "")[0]
    return [n for n in re.split(r"\s+(?:b2b|vs|&|x|and)\s+|,", t, flags=re.I) if n.strip()]


def candidates_from_meta(meta: dict) -> list[Candidate]:
    dur = meta.get("duration")
    cands = [Candidate("description", meta.get("description") or "", author=meta.get("channel"), uploader=True)]
    if meta.get("chapters"):
        txt = "\n".join(f"{_fmt(c.get('start_time') or 0)} {c.get('title', '')}" for c in meta["chapters"])
        cands.append(Candidate("chapters", txt, author=meta.get("channel"), uploader=True))
    for c in meta.get("comments") or []:
        cands.append(Candidate("comment", c.get("text") or "", author=c.get("author"),
                               likes=c.get("like_count") or 0, pinned=bool(c.get("is_pinned")),
                               uploader=bool(c.get("author_is_uploader"))))
    for c in cands:
        c.rows = parse_text(c.text, dur)
    return cands


def _score(c: Candidate, meta: dict) -> None:
    rows = c.rows
    strong = c.strong
    ids = sum(r.is_id for r in rows)
    partial = sum(r.quality == "partial" for r in rows) if strong >= 3 else 0
    s = strong + 0.5 * ids + 0.4 * partial
    if not rows:
        c.score = 0.0
        return
    with_ts = [r.ts for r in rows if r.ts is not None]
    if len(with_ts) >= 0.7 * len(rows):
        s *= 1.25
        c.why.append("timestamps")
        inc = sum(1 for a, b in zip(with_ts, with_ts[1:]) if b >= a)
        if len(with_ts) > 2 and inc < 0.8 * (len(with_ts) - 1):
            s *= 0.8
            c.why.append("timestamps desordenados")
    if any("timestamp fuera del video" in r.notes for r in rows):
        s *= 0.7
        c.why.append("timestamps fuera del video")
    bonus = 0.0
    if c.pinned:
        bonus += 4
        c.why.append("fijado")
    if c.uploader and c.source == "comment":
        bonus += 4
        c.why.append("autor=canal")
    a = norm_key(c.author or "")
    for dj in dj_names_from_title(meta.get("title", "")):
        d = norm_key(dj)
        if len(d) >= 3 and a and (d.replace(" ", "") in a.replace(" ", "") or fuzz.partial_ratio(d, a) >= 90):
            bonus += 5
            c.why.append("autor~DJ")
            break
    if re.search(r"(?i)track\s?list|setlist|track\s?ids?\b", c.text[:200]):
        bonus += 2
        c.why.append("palabra tracklist")
    bonus += math.log10(c.likes + 1)
    s = s + bonus if strong >= 3 else s * 0.5
    if c.source == "comment" and OTHER_VIDEO.search(c.text):
        s *= 0.3
        c.why.append("enlaza a otro video/mix")
    c.score = s


def _same(r1: ParsedLine, r2: ParsedLine) -> bool:
    if r1.is_id or r2.is_id:
        return False
    k1, k2 = r1.key(), r2.key()
    return bool(k1 and k2) and fuzz.token_set_ratio(k1, k2) >= 85


def choose(meta: dict, min_rows: int = 3) -> tuple[Candidate | None, list[Candidate], list[ParsedLine]]:
    """-> (winner or None, all candidates ranked by score, merged rows of the winner)."""
    cands = candidates_from_meta(meta)
    for c in cands:
        _score(c, meta)
    multi = [c for c in cands if c.strong >= min_rows]
    if len(multi) >= 2:
        for c in multi:
            others = [o for o in multi if o is not c]
            real = [r for r in c.rows if not r.is_id and r.quality == "strong"]
            hit = sum(1 for r in real if any(_same(r, x) for o in others for x in o.rows))
            c.consensus = hit / max(1, len(real))
            c.score *= 0.55 + 0.45 * c.consensus
    ranked = sorted(cands, key=lambda c: -c.score)
    best = ranked[0] if ranked and ranked[0].strong >= min_rows else None
    merged = merge(best, [c for c in multi if c is not best]) if best else []
    return best, ranked, merged


def merge(base: Candidate, donors: list[Candidate]) -> list[ParsedLine]:
    rows = [ParsedLine(**r.as_dict()) for r in base.rows]
    for d in sorted(donors, key=lambda c: -c.score):
        if (d.consensus or 0) < 0.5:
            continue
        a = [r.key() for r in rows]
        b = [r.key() for r in d.rows]
        sm = SequenceMatcher(a=a, b=b, autojunk=False)
        pairs = []
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1):
                pairs += list(zip(range(i1, i2), range(j1, j2)))
        for i, j in pairs:
            r, x = rows[i], d.rows[j]
            if op_ok(r, x):
                if r.ts is None and x.ts is not None:
                    r.ts = x.ts
                    r.notes.append(f"ts de {d.author}")
                if not r.version and x.version:
                    r.version = x.version
                if not r.label and x.label:
                    r.label = x.label
    return rows


def op_ok(r: ParsedLine, x: ParsedLine) -> bool:
    if r.is_id and x.is_id:
        return True
    return fuzz.token_set_ratio(r.key(), x.key()) >= 70
