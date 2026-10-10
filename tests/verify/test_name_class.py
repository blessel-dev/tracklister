"""1.0.1, Addendum 10 (B1-CLASE, DECISIONES X.42): a file name that only fits its row after the parse DROPS
alphabetic words, or MOVES them between artist and title, verifies only with an independent confirmation:
the file's own artist and title tags, or its duration within 3 s of the expected one. Without one, the file
is «Dudoso» (_dudosos), «Reordenar» proposes it unchecked and the Diagnóstico rejects the candidate.

SPDX-License-Identifier: GPL-3.0-or-later

The rules of the class, one case each (every name invented or a public track; no peer folder):
1 a scene '-group' ('underworld_-_born_slippy-nuxx': «Born Slippy .NUXX» is another track),
2 the scene folder's group ('...-space-time' in a folder whose group is TIME),
3 the parts before a ' - 06 - ' ('Adam Beyer - Space - 06 - Time'),
4 a cut without ' - ' (a glued hyphen, a scene name), also behind a joiner credit ('Adam Beyer & Space-Time'),
5 a bracket group that is no version ('Born Slippy (Nuxx)'),
and B2-R: the folder as the artist with only a title tag ('Adam Beyer\\Adam Port Rush.flac' tagged 'Rush').
These tests only use APIs that 7720b35 already had: there every rejection below fails (VERIFICADO / match).
"""
from __future__ import annotations

import dataclasses

import pytest

from tests.fakes.synth import make_track
from tracklister.core.model import DoubtKind, ResultState, TrackRow
from tracklister.diagnostics.run import judge_candidate
from tracklister.engine.presets import build_preset
from tracklister.organize import reorder
from tracklister.organize.reorder import propose_reorder
from tracklister.verify import verifier
from tracklister.verify.verifier import verify_file

LOSSLESS = build_preset("lossless").accept
FMT = build_preset("lossless").passes[0]


def _row(artist, title, version=None, dur=None, label=None, pos=1):
    return TrackRow(pos=pos, title=title, artists=[a.strip() for a in artist.split("&")], artist_display=artist,
                    version=version, expected_duration_s=dur, label=label)


def _verify(tmp_path, row, tail, *, seconds=20, tags=None, name="descarga.flac"):
    p = make_track(tmp_path / name, fmt="flac", seconds=seconds, tags=tags)
    return verify_file(row, p, LOSSLESS, lossy_allowed=False, source_path_tail=tail)


def _assert_unconfirmed(v, words):
    assert v.state == ResultState.DUDOSO and v.doubt == DoubtKind.IDENTIDAD and v.score <= 49, v.reasons_es
    assert any(r.startswith("El nombre solo encaja") and words in r and "ni las etiquetas ni la duración" in r
               for r in v.reasons_es), v.reasons_es


# ---- the three names of audit v101-2 B1 (rule 1) ------------------------------------------------------------
B1 = [
    (_row("Adam Beyer", "Space"), "Musica\\adam_beyer_-_space-time.flac", "'time'"),
    (_row("Planetary Assault Systems", "Non"), "Musica\\planetary_assault_systems_-_non-stop.flac", "'stop'"),
    (_row("Underworld", "Born Slippy"), "Musica\\underworld_-_born_slippy-nuxx.flac", "'nuxx'"),
]


@pytest.mark.parametrize("row,tail,words", B1, ids=[t.split("\\")[-1] for _, t, _ in B1])
def test_b1_scene_group_needs_a_confirmation(tmp_path, row, tail, words):
    """Untagged (or with only the artist tag) and without an expected duration: DUDOSO with the reason. A duration
    within 3 s, or artist and title tags that fit, confirm it: VERIFICADO. 6 s apart does not confirm."""
    _assert_unconfirmed(_verify(tmp_path, row, tail), words)
    _assert_unconfirmed(_verify(tmp_path, row, tail, tags={"artist": row.artist_display}, name="a.flac"), words)
    timed = dataclasses.replace(row, expected_duration_s=22)
    v = _verify(tmp_path, timed, tail, name="t.flac")
    assert v.state == ResultState.VERIFICADO and v.score == 100, v.reasons_es
    v = _verify(tmp_path, dataclasses.replace(row, expected_duration_s=26), tail, name="o.flac")
    _assert_unconfirmed(v, words)
    v = _verify(tmp_path, row, tail, tags={"artist": row.artist_display, "title": row.title}, name="g.flac")
    assert v.state == ResultState.VERIFICADO and v.score == 95, v.reasons_es


@pytest.mark.parametrize("row,tail,words", B1, ids=[t.split("\\")[-1] for _, t, _ in B1])
def test_b1_scene_group_in_reordenar_and_the_diagnostico(tmp_path, row, tail, words):
    folder = tmp_path / "Musica"
    folder.mkdir()
    (folder / tail.split("\\")[-1]).write_bytes(b"sin audio")
    p = next(x for x in propose_reorder(folder, [row]) if x.pos == 1)
    assert p.status == "ambiguous" and words in p.reason_es, p
    timed = dataclasses.replace(row, expected_duration_s=300)
    score, ok, why = judge_candidate(timed, FMT, "@@x\\" + tail, None, None)
    assert not ok and score < 50 and why.startswith("rechazado: el nombre solo encaja") and words in why, why
    score, ok, why = judge_candidate(timed, FMT, "@@x\\" + tail, 302, None)
    assert ok and score >= 80, why


# ---- the sweep: one case per rule, no tags and no expected duration -----------------------------------------
SWEEP = [
    # (rule, row, Soulseek path tail, what the reason names)
    ("1", _row("Underworld", "Born Slippy"), "Musica\\underworld_-_born_slippy-nuxx.flac", "quitando 'nuxx'"),
    ("2", _row("Adam Beyer", "Space"), "Adam_Beyer-Space_EP-WEB-2026-TIME\\03-adam_beyer-space-time.flac",
     "quitando 'time'"),
    ("3", _row("Adam Beyer", "Time"), "Musica\\Adam Beyer - Space - 06 - Time.flac", "quitando 'Space'"),
    ("4", _row("Adam Beyer", "Time"), "Musica\\Adam Beyer & Space-Time.flac",
     "leyendo 'Adam Beyer & Space' como artista"),
    ("4", _row("Adam Beyer", "Time"), "Musica\\Adam Beyer x Space-Time.flac",
     "leyendo 'Adam Beyer x Space' como artista"),
    ("4", _row("Red Rooms", "Trip"), "Musica\\04-red_rooms-trip.flac", "leyendo 'red rooms' como artista"),
    ("5", _row("Underworld", "Born Slippy"), "Musica\\Underworld - Born Slippy (Nuxx).flac", "quitando 'Nuxx'"),
    ("5", _row("Underworld", "Born Slippy"), "Musica\\Underworld - Born Slippy [Nuxx].flac", "quitando 'Nuxx'"),
]
SWEEP_IDS = [f"regla{r}-{t.split(chr(92))[-1]}" for r, _, t, _ in SWEEP]


@pytest.mark.parametrize("rule,row,tail,words", SWEEP, ids=SWEEP_IDS)
def test_sweep_verify_file_never_verifies_without_a_confirmation(tmp_path, rule, row, tail, words):
    _assert_unconfirmed(_verify(tmp_path, row, tail), words)
    v = _verify(tmp_path, dataclasses.replace(row, expected_duration_s=20), tail, name="t.flac")
    assert v.state == ResultState.VERIFICADO, v.reasons_es


@pytest.mark.parametrize("rule,row,tail,words", SWEEP, ids=SWEEP_IDS)
def test_sweep_reordenar_never_proposes_it_as_a_match(tmp_path, rule, row, tail, words):
    folder = tmp_path / "carpeta"
    *sub, name = tail.split("\\")
    target = folder.joinpath(*sub[1:] if sub[0] == "Musica" else sub) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"sin audio")
    p = next(x for x in propose_reorder(folder, [row]) if x.pos == 1)
    assert p.status == "ambiguous" and p.src == target and words in p.reason_es, p
    assert p.dst.name == f"01 - {row.artist_display} - {row.title}.flac"


@pytest.mark.parametrize("rule,row,tail,words", SWEEP, ids=SWEEP_IDS)
def test_sweep_the_diagnostico_needs_the_reported_duration(rule, row, tail, words):
    timed = dataclasses.replace(row, expected_duration_s=300)
    for reported in (None, 306):                       # no duration in the result, or 6 s apart
        score, ok, why = judge_candidate(timed, FMT, "@@x\\" + tail, reported, None)
        assert not ok and score < 50 and words in why and why.startswith("rechazado: el nombre solo encaja"), why
    score, ok, why = judge_candidate(timed, FMT, "@@x\\" + tail, 303, None)
    assert ok and score >= 80 and why.startswith("aceptable"), why
    score, ok, why = judge_candidate(row, FMT, "@@x\\" + tail, 300, None)    # the row has no duration
    assert not ok and score < 50, why


# ---- B2-R: the folder as the artist with only a title tag -----------------------------------------------------
def test_b2r_the_names_own_words_beyond_the_title_tag_need_a_confirmation(tmp_path):
    row = _row("Adam Beyer", "Rush")
    tail = "Adam Beyer\\Adam Port Rush.flac"
    _assert_unconfirmed(_verify(tmp_path, row, tail, tags={"title": "Rush"}), "quitando 'adam' y 'port'")
    v = _verify(tmp_path, dataclasses.replace(row, expected_duration_s=20), tail, tags={"title": "Rush"}, name="t.flac")
    assert v.state == ResultState.VERIFICADO, v.reasons_es
    # the folder and a title tag still verify a name that says nothing more than that title
    for clean in ("Adam Beyer\\Rush.flac", "Adam Beyer\\03 Rush.flac", "Adam Beyer\\Rush - Original Mix.flac"):
        assert _verify(tmp_path, row, clean, tags={"title": "Rush"}, name="c.flac").state == ResultState.VERIFICADO
    folder = tmp_path / "carpeta"
    make_track(folder / "Adam Beyer" / "Adam Port Rush.flac", fmt="flac", seconds=2, tags={"title": "Rush"})
    p = next(x for x in propose_reorder(folder, [row]) if x.pos == 1)
    assert p.status == "ambiguous" and "quitando 'adam' y 'port'" in p.reason_es, p


def test_rule5_a_title_tag_without_the_artist_tag_does_not_confirm_its_own_group(tmp_path):
    """Only a title tag 'Born Slippy (Nuxx)' (the artist from the name): the title fits only once '(Nuxx)' is gone,
    and one tag is no confirmation. Both tags are the file's own identity (the rule of Addendum 10)."""
    row = _row("Underworld", "Born Slippy")
    tail = "Musica\\Underworld - Born Slippy.flac"
    v = _verify(tmp_path, row, tail, tags={"title": "Born Slippy (Nuxx)"})
    assert v.state == ResultState.DUDOSO and v.doubt == DoubtKind.IDENTIDAD and v.score <= 49, v.reasons_es
    assert "La etiqueta de título solo encaja quitando 'Nuxx': puede ser otra canción u otra versión, y ni las " \
           "etiquetas ni la duración lo confirman." in v.reasons_es, v.reasons_es
    v = _verify(tmp_path, dataclasses.replace(row, expected_duration_s=20), tail, tags={"title": "Born Slippy (Nuxx)"},
                name="t.flac")
    assert v.state == ResultState.VERIFICADO, v.reasons_es


# ---- what the class does NOT include: no confirmation needed (DECISIONES X.42) ---------------------------------
@pytest.mark.parametrize("row,tail", [
    (_row("Red Rooms", "Trip"), "Musica\\Red Rooms - Trip (Original Mix) [www.dj-promo.org].flac"),   # watermark
    (_row("Red Rooms", "Trip"), "Musica\\04 - Red Rooms - Trip.flac"),                              # track number
    (_row("Red Rooms", "Trip"), "Musica\\Red Rooms - Trip (Original Mix) 140.flac"),                # BPM
    (_row("Red Rooms", "Trip"), "Musica\\Red Rooms - Trip (Key 8A).flac"),                          # key
    (_row("Red Rooms", "Trip"), "Musica\\Red Rooms - Trip [PHORUM004].flac"),                       # catalogue
    (_row("Red Rooms", "Trip"), "Musica\\red_rooms_-_trip-web.flac"),                                # release token
    (_row("Red Rooms", "Trip"), "Musica\\Red Rooms - Trip (feat. Kai).flac"),                       # a feat credit
    (_row("Red Rooms", "Trip", label="Phorum"), "Musica\\Red Rooms - Trip [Phorum].flac"),          # the row's label
    (_row("Red Rooms", "Trip"), "Musica\\Red Rooms - Trip [Phorum Records].flac"),                  # label-shaped
    (_row("Kwartz", "Show Me That Light", "Cleric Remix"),
     "7 - Carpeta Inventada\\Kwartz - Show Me That Light (Cleric Remix) [.wav"),                    # open bracket
    # another reading leaves nothing out and fits: it wins ('Born Slippy .NUXX' is the file as written)
    (_row("Underworld", "Born Slippy Nuxx"), "Musica\\underworld_-_born_slippy-nuxx.flac"),
    (_row("Adam Beyer", "Space-Time"), "Adam_Beyer-Space_EP-WEB-2026-TIME\\Adam Beyer - Space-Time.flac"),
])
def test_out_of_the_class_verifies_without_tags_or_duration(tmp_path, row, tail):
    v = _verify(tmp_path, row, tail)
    assert v.state == ResultState.VERIFICADO and v.score == 95 and "nombre_sin_confirmar" not in v.flags, v.reasons_es


# ---- his 7 real Diagnóstico names, with their real durations (Trip 5:05, Kwartz 6:25 / files 6:24, Seiko 5:32) --
TRIP = _row("Red Rooms", "Trip")
KWARTZ = _row("Kwartz", "Show me that light", "Cleric Remix")
SEIKO = _row("Phil Berg", "Seiko")
REAL = [
    (TRIP, 305, "Red_Rooms-Blind_Spot-(PHORUM004)-16BIT-WEB-FLAC-2026-PTC\\04-red_rooms-trip.flac", 305, True),
    (KWARTZ, 385, "Kwartz-Show_Me_That_Light_EP-(CRG014)-16BIT-WEB-FLAC-2018-BABAS\\"
                  "04-kwartz-show_me_that_light_(cleric_remix)-3fa1c09b.flac", 384, True),
    (SEIKO, 332, "Phil_Berg-Darin-MR047D-24BIT-WEB-FLAC-2026-WAVED\\06-phil_berg-seiko.flac", 332, True),
    (KWARTZ, 385, "Coleccion Inventada\\1-04-Kwartz-Show me that light (Cleric Remix).flac", 384, True),
    (TRIP, 305, "Novedades Inventadas\\Red Rooms - Trip (Original Mix) 140.flac", 305, False),
    (SEIKO, 332, "Lista Ejemplo\\Phil Berg - D\u0101rin - 06 - Seiko.flac", 332, True),
    (KWARTZ, 385, "7 - Carpeta Inventada\\Kwartz - Show Me That Light (Cleric Remix) [.wav", 384, False),
]
REAL_IDS = [t.split("\\")[-1][:40] for *_, t, _, _ in REAL]


@pytest.mark.parametrize("row,expected,tail,seconds,guessed", REAL, ids=REAL_IDS)
def test_his_real_names_verify_with_their_real_durations(tmp_path, monkeypatch, row, expected, tail, seconds, guessed):
    """verify_file with the durations of his Diagnóstico (the probe reports them; the audio is 2 s). Without an
    expected duration the guessed ones (scene names, '1-04-', ' - 06 - ') need a confirmation."""
    real_probe = verifier.probe
    monkeypatch.setattr(verifier, "probe", lambda path, **kw: dataclasses.replace(
        real_probe(path, **kw), duration_s=float(seconds), decoded_duration_s=float(seconds)))
    p = make_track(tmp_path / "x.flac", fmt="flac", seconds=2)
    v = verify_file(dataclasses.replace(row, expected_duration_s=expected), p, LOSSLESS, lossy_allowed=False,
                    source_path_tail=tail, spectral=False)
    assert v.state == ResultState.VERIFICADO and v.score >= 95, v.reasons_es
    v = verify_file(row, p, LOSSLESS, lossy_allowed=False, source_path_tail=tail, spectral=False)
    assert (v.state == ResultState.DUDOSO) is guessed, v.reasons_es


@pytest.mark.parametrize("row,expected,tail,seconds,guessed", REAL, ids=REAL_IDS)
def test_his_real_names_are_matched_by_reordenar_with_their_real_durations(tmp_path, monkeypatch, row, expected,
                                                                          tail, seconds, guessed):
    """«Reordenar» reads each file's duration from its header (here reported as in his Diagnóstico)."""
    sub, name = tail.rsplit("\\", 1)
    folder = tmp_path / "Set casa"
    f = folder / sub / name
    f.parent.mkdir(parents=True)
    f.write_bytes(b"sin audio")
    monkeypatch.setattr(reorder, "read_tags_and_length", lambda p: (None, None, float(seconds)))
    p = next(x for x in propose_reorder(folder, [dataclasses.replace(row, expected_duration_s=expected)]) if x.pos)
    assert p.status == "match" and p.src == f, p
    p = next(x for x in propose_reorder(folder, [row]) if x.pos)
    assert (p.status == "ambiguous") is guessed and p.src == f, p
