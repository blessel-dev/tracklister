"""Contract tests for the shared core (model round-trips, textnorm rules, safety net)."""
from __future__ import annotations

import socket

import keyring
import pytest

from tracklister.core.jsonio import read_json, write_json
from tracklister.core.model import (
    DoubtKind, RowResult, ResultState, SetDoc, SourceRef, TrackRow, VersionKind,
)
from tracklister.core.paths import app_paths
from tracklister.core.settings import Settings, load_settings, save_settings
from tracklister.core.textnorm import (
    classify_version, nfc, norm_key, remixer_of, split_artists, split_title_version,
    versions_compatible,
)


def test_new_optional_fields_load_from_old_files():
    """set.json/library.json written before the audit fixes (no rejected_peers / flags) still load."""
    r = RowResult.from_dict({"uid": "u1", "pos": 1, "state": "dudoso", "doubt": "version", "peer": "peerA"})
    assert r.rejected_peers == [] and r.peer == "peerA"
    back = RowResult.from_dict(RowResult(uid="u2", pos=2, rejected_peers=["a", "b"]).to_dict())
    assert back.rejected_peers == ["a", "b"]
    # round 2 (N3): set.json files without lossy_asked still load; the field round-trips
    old = SetDoc(set_id="s", name="n", preset_id="lossless").to_dict()
    del old["lossy_asked"]
    assert SetDoc.from_dict(old).lossy_asked == []
    doc = SetDoc(set_id="s", name="n", preset_id="lossless", lossy_asked=["u1"])
    assert SetDoc.from_dict(doc.to_dict()).lossy_asked == ["u1"]


def test_setdoc_roundtrip(tmp_path):
    row = TrackRow(pos=3, title="Higher Things", artists=["Chris Liebing"],
                   artist_display="Chris Liebing", version="FJAAK Remix", expected_duration_s=289)
    res = RowResult(uid=row.uid, pos=3, state=ResultState.DUDOSO, doubt=DoubtKind.ESPECTRO,
                    flags=["posible_falso_lossless"])
    doc = SetDoc(set_id="abc", name="FJAAK SECTION", preset_id="lossless", rows=[row],
                 results={row.uid: res}, sources=[SourceRef(kind="trackid_csv", ref="x.csv")])
    p = tmp_path / "set.json"
    write_json(p, doc.to_dict())
    back = SetDoc.from_dict(read_json(p))
    assert back.rows[0] == row
    assert back.results[row.uid] == res
    assert back.rows[0].title_with_version == "Higher Things (FJAAK Remix)"


def test_settings_roundtrip_and_no_credentials(tmp_path):
    s = Settings(preset_id="cdj_antiguos", library_root="D:/Sets")
    p = tmp_path / "settings.json"
    save_settings(p, s)
    text = p.read_text(encoding="utf-8")
    assert "password" not in text and "username" not in text
    assert load_settings(p) == s


def test_paths_use_tracklister_home(_tracklister_home):
    assert str(app_paths().config_dir).startswith(str(_tracklister_home))


@pytest.mark.parametrize("title,base,version", [
    ("Higher Things (FJAAK Remix)", "Higher Things", "FJAAK Remix"),
    ("Raw Groove (Jon10 Remix) [Label X]", "Raw Groove", "Jon10 Remix"),
    ("Dust 1 - Kai Van Dongen Remix", "Dust 1", "Kai Van Dongen Remix"),
    ("Mercy Original Mix", "Mercy", "Original Mix"),
    ("Plain", "Plain", None),
])
def test_split_title_version(title, base, version):
    assert split_title_version(title) == (base, version)


def test_version_rules():
    assert classify_version(None) == VersionKind.ORIGINAL
    assert classify_version("Extended Mix") == VersionKind.EXTENDED
    assert classify_version("Radio Edit") == VersionKind.RADIO_EDIT
    assert classify_version("FJAAK Remix") == VersionKind.REMIX
    assert remixer_of("Kai Van Dongen Remix") == "kai van dongen"
    assert versions_compatible(None, "Original Mix")[0]
    assert versions_compatible("Original", "Extended Mix")[0]
    assert not versions_compatible(None, "FJAAK Remix")[0]
    assert not versions_compatible("FJAAK Remix", "Original Mix")[0]
    assert versions_compatible("FJAAK Remix", "Fjaak Remix")[0]
    assert not versions_compatible(None, "Radio Edit")[0]


def test_norm_and_artists():
    assert norm_key("Gla\u00f0ur") == "gladur"
    assert nfc("Cuerpo So\u0301lido") == "Cuerpo S\u00f3lido"
    assert nfc("Don\u2019t") == "Don't"
    assert split_artists("Blasha & Allatt") == ["Blasha", "Allatt"]


def test_safety_net_blocks_network_and_uses_fake_keyring(fake_keyring):
    with pytest.raises(RuntimeError):
        socket.create_connection(("server.slsknet.org", 2242), timeout=1)
    keyring.set_password("svc", "u", "p")
    assert fake_keyring.store[("svc", "u")] == "p"
