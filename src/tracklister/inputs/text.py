"""Pasted text (1001tracklists, MixesDB, Instagram, comments, notes) -> rows. Works offline.

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

from tracklister.core.model import TrackRow
from tracklister.inputs.tlparse import parse_text, to_track_rows


def parse_pasted_text(text: str, source: str = "texto") -> list[TrackRow]:
    """One row per track line ('Artista - Titulo', with or without a time); prose is dropped."""
    return to_track_rows(parse_text(text), source)
