"""06 R9: the publishable tree carries none of the real YouTube/SoundCloud comments of the 1.0.0 test
fixtures: neither their authors' aliases nor their text (tools/secrets_scan.py, «alias retirados» and
«comentarios retirados»). Count-only: no test ever prints a matched value, and the lists hold only
SHA-256 fingerprints.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import sys

import pytest

from tests.release.helpers import REPO

_spec = importlib.util.spec_from_file_location("tracklister_secrets_scan_retired", REPO / "tools" / "secrets_scan.py")
ss = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ss                 # dataclasses look their module up while the class is built
_spec.loader.exec_module(ss)
YT = REPO / "tests" / "fixtures" / "youtube"


@pytest.fixture(scope="module")
def rules():
    return {r.key: r for r in ss.retired_rules()}


def test_the_fingerprint_lists_are_there_and_well_formed(rules):
    assert rules["retired_handle"].size() >= 1000            # the authors of ~1450 comments
    assert rules["retired_comment"].size() >= 1000
    for line in ss._fingerprint_lines(ss.RETIRED_HANDLES_FILE):
        assert len(line) == 64 and int(line, 16) >= 0         # one SHA-256 per line, nothing else
    for line in ss._fingerprint_lines(ss.RETIRED_COMMENTS_FILE):
        n, digest = line.split()
        assert 2 <= int(n) <= 5 and len(digest) == ss.NGRAM_HEX and int(digest, 16) >= 0


def test_no_retired_alias_or_comment_in_the_publishable_tree(rules):
    files = ss.publishable_files(REPO)
    assert len(files) > 300
    res = ss.scan(files, tuple(rules.values()), root=REPO)
    assert {k: v for k, v in res.counts.items() if v} == {}, ss.report_lines(res)   # counts and file names only


def test_the_cli_scan_includes_both_rules():
    keys = {r.key for r in ss.retired_rules()}
    assert keys == {"retired_handle", "retired_comment"}
    assert "retired_rules()" in inspect.getsource(ss.main)


def test_the_rules_find_planted_values(tmp_path):
    """Positive control with invented values only: an alias and a sentence fingerprinted here."""
    alias = "@alias" + "-de-prueba"
    words = ss.text_words("Una frase de prueba que nadie ha escrito")
    handles = tmp_path / "h.sha256"
    handles.write_text("# prueba\n" + ss.handle_digest(alias) + "\n", encoding="utf-8")
    comments = tmp_path / "c.sha256"
    comments.write_text(f"5 {ss.ngram_digest(words[2:7])}\n2 {ss.ngram_digest(['oyente', 'raro'])}\n",
                        encoding="utf-8")
    h_rule, c_rule = ss.retired_rules(handles, comments)
    assert h_rule.count(f"hola {alias.upper()}. y {alias}, y @otro") == 2           # case, trailing '.'
    assert h_rule.count("alias-de-prueba sin arroba") == 0
    assert c_rule.count("Dijo: una FRASE de prueba que nadie, ha escrito") == 1      # case/punctuation
    assert c_rule.count("Dé PRUEBA qué nadie ha") == 1                               # accents
    assert c_rule.count('"text": "de prueba\\nque nadie ha"') == 1                  # JSON escapes undone
    assert c_rule.count("de prueba que nadie lo") == 0
    assert c_rule.count("Oyente Raro") == 1 and c_rule.count("oyente muy raro") == 0
    planted = tmp_path / "comentarios.json"
    planted.write_text(json.dumps({"author": alias, "text": "de prueba que nadie ha"}), encoding="utf-8")
    res = ss.scan([planted], (h_rule, c_rule), root=tmp_path)
    assert res.counts == {"retired_handle": 1, "retired_comment": 1}


def test_a_missing_list_fails_the_scan(tmp_path):
    h_rule, _ = ss.retired_rules(tmp_path / "no-existe.sha256", tmp_path / "tampoco.sha256")
    with pytest.raises(FileNotFoundError):
        h_rule.count("@x")


def test_the_new_fixtures_keep_the_comment_shape():
    """Every comment of 1.0.0 is still there, one for one, with an invented author."""
    counts = {"6Wi11ljHVb4": 26, "7CXp2EaRaIU": 300, "FckHz08Z7PM": 300, "cmUov7X5Pjc": 300, "mD9ELt_Pvp4": 223,
              "soundcloud_451181991": 2, "z6CwInMQF4w": 300}
    authors = set()
    for vid, n in counts.items():
        meta = json.loads((YT / f"{vid}.meta.json").read_text(encoding="utf-8"))
        assert len(meta["comments"]) == n
        authors |= {c["author"] for c in meta["comments"]}
    assert all(a.startswith(("@oyente-", "Oyente Ejemplo ")) or a.endswith(("-ejemplo", "-ejemplo-2"))
               for a in authors)
