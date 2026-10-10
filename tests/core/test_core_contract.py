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
    classify_version, merge_versions, nfc, norm_key, remixer_of, split_artists, split_title_version,
    version_groups, versions_compatible,
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


@pytest.mark.parametrize("title,dropped", [
    ("Raw Groove (Jon10 Remix) [Label X]", ["Label X"]),
    ("Born Slippy (Nuxx) [Junior]", ["Nuxx", "Junior"]),
    ("Spirit (Nuxx) (Kai Remix)", ["Nuxx"]),
    ("Spirit (feat. Jo) Extended Mix (Kai Remix)", ["feat. Jo"]),
    ("Track (Part 2)", ["Part 2"]),
    ("Higher Things (FJAAK Remix)", []), ("Mercy Original Mix", []), ("Plain", []), ("(Nuxx)", []),
])
def test_title_dropped_groups(title, dropped):
    """1.0.1, Addendum 10: the bracket groups split_title_version leaves out of the base title without making
    them the version, in written order; the base and the version are unchanged."""
    from tracklister.core.textnorm import title_dropped_groups
    assert title_dropped_groups(title) == dropped


@pytest.mark.parametrize("title,version,kind", [
    ("Spirit (Kai Remix) (Extended Mix)", "Kai Remix", VersionKind.REMIX),
    ("Spirit (Extended Mix) (Kai Remix)", "Kai Remix", VersionKind.REMIX),
    ("Spirit - Kai Remix (Extended Mix)", "Kai Remix", VersionKind.REMIX),
    ("Spirit (Live at Awakenings)", "Live at Awakenings", VersionKind.LIVE),
    ("Spirit (Live)", "Live", VersionKind.LIVE),
    ("Spirit (Kai Remix) (Radio Edit)", "Kai Remix - Radio Edit", VersionKind.RADIO_EDIT),
    ("Spirit (Extended Mix) [Drumcode]", "Extended Mix", VersionKind.EXTENDED),
    ("Spirit (Original Mix) (Extended Mix)", "Extended Mix", VersionKind.EXTENDED),
    ("Spirit (Original Mix)", "Original Mix", VersionKind.ORIGINAL),
    ("Spirit [Drumcode]", None, VersionKind.ORIGINAL),
])
def test_r4_b3_no_version_group_is_lost(title, version, kind):
    """Audit round 4, B3: only the rightmost group with a version word was kept, so 'Spirit (Kai Remix)
    (Extended Mix)' was the extended ORIGINAL, and '(Live ...)' had no version word at all. Now every
    group that is not original/extended is kept (merge_versions; the radio edit of the Kai Remix keeps
    its remixer since the second review of round 4); labels are still dropped."""
    assert split_title_version(title) == ("Spirit", version)
    assert classify_version(version) == kind


@pytest.mark.parametrize("title,version", [
    ("Spirit (Kai Remix) (Radio Edit)", "Kai Remix - Radio Edit"),
    ("Spirit (Radio Edit) (Kai Remix)", "Radio Edit - Kai Remix"),
    ("Spirit - Kai Remix (Radio Edit)", "Kai Remix - Radio Edit"),
    ("Spirit (Kai Remix - Radio Edit)", "Kai Remix - Radio Edit"),
    ("Spirit (Kai Remix) (Edit)", "Kai Remix - Edit"),
    ("Spirit (Kai Remix) (Live)", "Kai Remix - Live"),
    ("Spirit (Kai Remix) (Instrumental)", "Kai Remix - Instrumental"),
    ("Spirit (Kai Remix) (Remastered)", "Kai Remix - Remastered"),
    ("Spirit (Kai Remix) (2011 Remaster)", "Kai Remix - 2011 Remaster"),
    ("Spirit (feat. Jo) Kai Remix (Radio Edit)", "Kai Remix - Radio Edit"),
])
def test_r4_v_a_remix_keeps_its_remixer_behind_another_group(title, version):
    """Audit round 4, second review, B2: '(Kai Remix) (Radio Edit)' kept only 'Radio Edit' (and the same
    with Edit, Live, Instrumental, Remastered), so the ORIGINAL's radio edit was VERIFICADO and offered
    from the library. Now the version keeps every group, in written order, joined with ' - '."""
    assert split_title_version(title) == ("Spirit", version)


@pytest.mark.parametrize("title,version", [
    ("Spirit (Kai Remix)", "Kai Remix"), ("Spirit (Kai Remix) (Extended Mix)", "Kai Remix"),
    ("Spirit (Extended Mix) (Kai Remix)", "Kai Remix"), ("Spirit (Kai Remix) [Drumcode]", "Kai Remix"),
    ("Spirit (Kai Remix) (Extended)", "Kai Remix"), ("Spirit (Kai Remix) [Extended]", "Kai Remix"),
    ("Spirit (Kai Remix) - Extended Mix", "Kai Remix"),
    ("Spirit (feat. Jo) Extended Mix (Kai Remix)", "Kai Remix"), ("Spirit (feat. Jo) Extended Mix [Kai Remix]", "Kai Remix"),
    ("Spirit (Original Mix)", "Original Mix"), ("Spirit (Extended Mix)", "Extended Mix"),
    ("Spirit (Extended)", "Extended"), ("Spirit (Radio Edit)", "Radio Edit"),
    ("Spirit (Live at Awakenings)", "Live at Awakenings"), ("Spirit (Original)", None),
])
def test_r4_v_one_remix_or_the_original_is_unchanged(title, version):
    """The original/extended groups still give way to any other group, and a single group is as before."""
    assert split_title_version(title) == ("Spirit", version)


def test_r4_v_merge_versions_is_the_one_rule():
    assert merge_versions(["Kai Remix", "Extended Mix"]) == "Kai Remix"
    assert merge_versions(["Original Mix", "Extended Mix"]) == "Extended Mix"
    assert merge_versions(["Kai Remix", "Radio Edit"]) == "Kai Remix - Radio Edit"
    assert merge_versions(["(Kai Remix) [Radio Edit]"]) == "Kai Remix - Radio Edit"
    assert merge_versions(["Kai Remix", "kai remix"]) == "Kai Remix"             # no repeats
    assert merge_versions(["Remix", "Kai Remix"]) == "Kai Remix"                 # a group inside another
    assert merge_versions([None, ""]) is None and merge_versions([]) is None
    for v in ("Kai Remix - Radio Edit", "Extended Mix", "Radio Edit - Kai Remix", "Live at Awakenings"):
        assert merge_versions([merge_versions([v])]) == merge_versions([v]) == v
    assert version_groups("Kai Remix - Radio Edit") == version_groups("(Kai Remix) [Radio Edit]") == [
        "Kai Remix", "Radio Edit"]


ROW = "Kai Remix - Radio Edit"


@pytest.mark.parametrize("wanted,got,ok", [
    (ROW, ROW, True), (ROW, "(Kai Remix) [Radio Edit]", True), (ROW, "Radio Edit - Kai Remix", True),
    (ROW, "Radio Edit", False), (ROW, "Kai Remix", False), (ROW, "Edit", False), (ROW, None, False),
    (ROW, "Original Mix", False), (ROW, "Other Remix - Radio Edit", False), (ROW, "Kai Remix - Edit", False),
    ("Radio Edit", ROW, False), ("Radio Edit", "Radio Edit", True), ("Radio Edit", "Radio Mix", True),
    ("Radio Edit", "Kai Remix Radio Edit", False), ("Radio Edit", "Kai Radio Edit", False),
    ("Kai Remix", ROW, False), ("Kai Remix", "Kai Remix (Extended Mix)", True), ("Kai Remix", "Kai Remix", True),
    ("Kai Remix", "Kai Remix Edit", False), ("Kai Remix", "Kai Edit", False),
    ("FJAAK Remix", "Fjaak Remix", True), ("Kai Remix", "Kai Van Dongen Remix", True),
    ("Kai Remix - Edit", "(Kai Remix) (Edit)", True), ("Kai Remix - Edit", "Edit", False),
    ("Kai Remix - Edit", "Kai Remix", False), ("Edit", "Kai Remix - Edit", False),
    ("Kai Remix - Live", "Kai Remix (Live)", True), ("Kai Remix - Live", "Live", False),
    ("Kai Remix - Instrumental", "Kai Remix [Instrumental]", True), ("Kai Remix - Instrumental", "Instrumental", False),
    ("Kai Remix - Remastered", "(Kai Remix) (Remastered)", True), ("Kai Remix - Remastered", "Remastered", False),
    ("Kai Remix - Remastered", "Kai Remix", False), ("Live", "Kai Remix - Live", False),
    (None, "Kai Remix - Radio Edit", False), (None, "Extended Mix", True),
])
def test_r4_v_versions_are_compared_group_by_group(wanted, got, ok):
    """Every wanted group needs its own partner of the same kind in the file, and the other way round."""
    assert versions_compatible(wanted, got)[0] is ok, versions_compatible(wanted, got)


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


def test_safety_net_blocks_network_and_uses_fake_keyring(fake_keyring, _no_network):
    with pytest.raises(RuntimeError):
        socket.create_connection(("server.slsknet.org", 2242), timeout=1)
    assert _no_network == ["DNS lookup blocked in tests: 'server.slsknet.org'"]
    _no_network.clear()                          # expected: the guard would otherwise fail this test
    keyring.set_password("svc", "u", "p")
    assert fake_keyring.store[("svc", "u")] == "p"
