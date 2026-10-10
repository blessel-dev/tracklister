"""1.0.1 additions to the shared core: the quality state, optional fields and version_key.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import pytest

from tracklister.core.model import (
    LIBRARY_SCHEMA, LIBRARY_SCHEMA_V1, DoubtKind, ResultState, RowResult, SetDoc, SourceRef,
)
from tracklister.core.textnorm import version_key


def test_the_quality_state_is_its_own_state_and_espectro_stays_readable():
    assert ResultState("revisar_calidad") is ResultState.REVISAR_CALIDAD
    assert ResultState.REVISAR_CALIDAD != ResultState.VERIFICADO
    # 1.0.0 results with doubt "espectro" still load (the upgrade re-verifies them later)
    old = RowResult.from_dict({"uid": "u", "pos": 6, "state": "dudoso", "doubt": "espectro",
                               "flags": ["posible_falso_lossless"]})
    assert old.state == ResultState.DUDOSO and old.doubt == DoubtKind.ESPECTRO and old.spectral_cutoff_hz is None
    assert LIBRARY_SCHEMA == "tracklister.library/2" and LIBRARY_SCHEMA_V1 == "tracklister.library/1"


def test_new_optional_fields_round_trip_and_old_files_load():
    r = RowResult(uid="u", pos=1, state=ResultState.REVISAR_CALIDAD, spectral_cutoff_hz=16250.0)
    assert RowResult.from_dict(r.to_dict()) == r
    old = SetDoc(set_id="s", name="n", preset_id="lossless").to_dict()
    del old["migrations"]                                   # a set.json written by 1.0.0
    assert SetDoc.from_dict(old).migrations == []
    doc = SetDoc(set_id="s", name="n", preset_id="lossless", migrations=["1.0.1-reverificar"],
                 sources=[SourceRef("youtube_comment", "x", detail="youtube_comment:@ejemplo (22 pistas)")])
    assert SetDoc.from_dict(doc.to_dict()).migrations == ["1.0.1-reverificar"]


@pytest.mark.parametrize("a,b", [
    ("Kai Remix - Radio Edit", "Radio Edit - Kai Remix"),
    ("(Kai Remix) (Radio Edit)", "(Radio Edit) (Kai Remix)"),
    ("Kai Remix (Extended Mix)", "Kai Remix"),
    ("Original Mix", None), ("Extended Mix", "Original Mix - Extended Mix"),
])
def test_version_key_does_not_depend_on_the_group_order(a, b):
    """Audit r4-3 N1: the library and duplicate keys depended on the order of the version groups."""
    assert version_key(a) == version_key(b)


def test_version_key_keeps_different_versions_apart():
    keys = {v: version_key(v) for v in ("Kai Remix", "Radio Edit", "Kai Remix - Radio Edit", None,
                                        "Cleric Remix", "Connor Wall Remix")}
    assert len(set(keys.values())) == len(keys)
    assert keys[None] == "original" and keys["Cleric Remix"] == "cleric remix"
    # one group: the same text the 1.0.0 keys had, so his whole library keeps its keys
    assert keys["Kai Remix - Radio Edit"] == "kai remix radio edit"
