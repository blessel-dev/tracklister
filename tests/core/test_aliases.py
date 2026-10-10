"""core.aliases: the other spellings searched when a row finds nothing (1.0.1, R4), on his real rows.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import pytest

from tracklister.core.aliases import (
    MAX_VARIANTS, artist_aliases, dotted_variant, letter_digit_forms, letter_digit_variant, search_variants,
)


@pytest.mark.parametrize("artist", [
    "Komplex aka Jeroen Search", "Komplex a.k.a. Jeroen Search", "Komplex AKA Jeroen Search",
    "Komplex a.k.a Jeroen Search", "Komplex (aka Jeroen Search)", "Komplex [a.k.a. Jeroen Search]",
    "Komplex  aka  Jeroen Search",
])
def test_aka_forms_give_both_names(artist):
    assert artist_aliases(artist) == ["Komplex", "Jeroen Search"]


def test_more_aliases_and_no_alias():
    assert artist_aliases("A1 aka B2 aka C3") == ["A1", "B2", "C3"]
    for name in ("Komplex", "Akasha", "Sakamoto", "Takaaki Itoh", "Aka Aka", "AKA AKA & Thalstroem",
                 "Jeroen Search", "", None, "Kaka aka", "aka Komplex", "Same aka same"):
        assert artist_aliases(name) == [], name


@pytest.mark.parametrize("text,expected", [
    ("Vkn.modular", "Vkn modular"), ("Mr.Oizo", "Mr Oizo"), ("Vkn.mod.ular", "Vkn mod ular"),
    ("D.A.V.E.", None), ("St. Germain", None), ("A.Paul", None), ("No.12", None), ("Vkn modular", None),
    ("", None),
])
def test_dotted_variant(text, expected):
    assert dotted_variant(text) == expected


@pytest.mark.parametrize("text,space,dash", [
    ("TR440", "TR 440", "TR-440"), ("tb303 Acid", "tb 303 Acid", "tb-303 Acid"),
    ("Lx2", None, None), ("DVS1", None, None), ("1982", None, None), ("13130 Space Project", None, None),
    ("TR440s", None, None), ("TR 440", None, None), ("X440", None, None),
])
def test_letter_digit_variant_only_splits_a_glued_start(text, space, dash):
    assert letter_digit_variant(text) == space
    assert letter_digit_variant(text, "-") == dash


def test_letter_digit_forms_cover_the_three_spellings():
    assert letter_digit_forms("TR440") == ["TR 440", "TR-440"]
    assert letter_digit_forms("TR-440") == ["TR440", "TR 440"]
    assert letter_digit_forms("TR 440") == ["TR440", "TR-440"]
    assert letter_digit_forms("Lx2") == [] and letter_digit_forms("1982") == [] and letter_digit_forms("Orbe") == []


def test_search_variants_on_his_three_no_result_rows():
    assert search_variants("Komplex aka Jeroen Search", "Inject") == [("Komplex", "Inject"), ("Jeroen Search", "Inject")]
    assert search_variants("Vkn.modular", "Hidden Reason") == [("Vkn modular", "Hidden Reason")]
    assert search_variants("TR440", "Somewhen") == [("TR 440", "Somewhen"), ("TR-440", "Somewhen")]


@pytest.mark.parametrize("artist,title", [
    ("Red Rooms", "Trip"), ("Lucy", "Lx2"), ("Miss Kittin", "1982"), ("13130 Space Project", "Talitha"),
    ("Kwartz", "Show me that light (Cleric Remix)"), ("D.A.V.E. The Drummer", "Hydraulix 2"),
    ("St. Germain", "Rose Rouge"), ("Orbe", "Velocity"),
])
def test_rows_that_need_no_variant(artist, title):
    assert search_variants(artist, title) == []


def test_variants_are_deduplicated_capped_and_never_the_original():
    many = search_variants("Vkn.modular aka TR440 aka Kwartz", "Hidden.Reason")
    assert len(many) == MAX_VARIANTS == 2
    assert many == [("Vkn.modular", "Hidden.Reason"), ("TR440", "Hidden.Reason")]
    assert search_variants("Komplex aka komplex", "Inject") == []          # one name twice: no alias
    v = search_variants("Vkn.modular", "Hidden.Reason")
    assert v == [("Vkn modular", "Hidden Reason")]                         # one combined variant
    assert ("Vkn.modular", "Hidden.Reason") not in v
    assert search_variants("Artist", "TB303 Acid") == [("Artist", "TB 303 Acid"), ("Artist", "TB-303 Acid")]
    assert search_variants("", "Inject") == [] and search_variants("Komplex aka Jeroen Search", "") == []


def test_title_versions_are_kept():
    assert search_variants("Vkn.modular", "Hidden Reason (Kwartz Remix)") == [
        ("Vkn modular", "Hidden Reason (Kwartz Remix)")]
