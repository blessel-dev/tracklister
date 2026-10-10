"""1.0.1 R6: calibration of the spectral classes with synthetic material (the table is in DECISIONES X).

SPDX-License-Identifier: GPL-3.0-or-later

Broadband material is encoded to MP3 with the suite's pinned encoder (LAME inside libsndfile 1.2.2 of
soundfile 0.14.0: CBR 128/160/192/224/256/320 and VBR V0), decoded and written as FLAC, exactly what a
"lossless" file made from an MP3 is. The genuine cases are the same material at full band and through
steep (FFT brick-wall) low-pass filters at 20.0, 20.5 and 21.0 kHz, as resampling or mastering leave it,
plus a dark mix with a smooth roll-off. Run with -s to see the measured table.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import soundfile as sf

from tests.fakes.synth import make_low_treble_track, make_track
from tracklister.core.model import ResultState, TrackRow
from tracklister.engine.presets import build_preset
from tracklister.verify.audioinfo import mp3_frame_bitrates
from tracklister.verify.spectral import (
    AMBIGUOUS_MAX_HZ, STRONG_MAX_HZ, SpectralClass, classify, fake_lossless_check, khz_es,
)
from tracklister.verify.verifier import verify_file

SECONDS = 12
MP3_CASES = [("mp3_128", 128, False), ("mp3_160", 160, False), ("mp3_192", 192, False), ("mp3_224", 224, False),
             ("mp3_256", 256, False), ("mp3_320", 320, False), ("mp3_v0", None, True)]
MASTER_CASES = [("master_full", None), ("master_lp_20000", 20000.0), ("master_lp_20500", 20500.0),
                ("master_lp_21000", 21000.0)]
EXPECTED = {"mp3_128": SpectralClass.STRONG, "mp3_160": SpectralClass.STRONG, "mp3_192": SpectralClass.STRONG,
            "mp3_224": SpectralClass.STRONG, "mp3_256": SpectralClass.STRONG, "mp3_320": SpectralClass.AMBIGUOUS,
            "mp3_v0": SpectralClass.NONE, "master_full": SpectralClass.NONE,
            "master_lp_20000": SpectralClass.AMBIGUOUS, "master_lp_20500": SpectralClass.AMBIGUOUS,
            "master_lp_21000": SpectralClass.NONE, "master_low_treble": SpectralClass.NONE}


def transcode(tmp: Path, name: str, kbps: int | None, vbr: bool, seed: int = 0) -> tuple[Path, int | None]:
    """Broadband material -> MP3 (pinned encoder) -> decoded -> FLAC 16 bit. Returns (flac, frame kbps)."""
    mp3 = make_track(tmp / f"{name}.mp3", fmt="mp3", seconds=SECONDS, mp3_kbps=kbps or 320, vbr=vbr, seed=seed)
    frames = set(mp3_frame_bitrates(mp3))
    y, sr = sf.read(str(mp3), dtype="float32")
    out = tmp / f"{name}.flac"
    sf.write(str(out), y, sr, format="FLAC", subtype="PCM_16")
    return out, (frames.pop() if len(frames) == 1 else None)


def master(tmp: Path, name: str, lowpass: float | None, seed: int = 0) -> Path:
    return make_track(tmp / f"{name}.flac", fmt="flac", seconds=SECONDS, lowpass_hz=lowpass, seed=seed)


def calibration_table(tmp: Path, seed: int = 0) -> list[dict]:
    """Every calibration case with its measured cut, drop and class (also used to write DECISIONES X)."""
    rows = []
    for name, kbps, vbr in MP3_CASES:
        p, frame_kbps = transcode(tmp, f"{name}-{seed}", kbps, vbr, seed)
        rows.append({"case": name, "kbps": frame_kbps, "result": fake_lossless_check(p)})
    for name, lp in MASTER_CASES:
        rows.append({"case": name, "kbps": None, "result": fake_lossless_check(master(tmp, f"{name}-{seed}", lp, seed))})
    dark = make_low_treble_track(tmp / f"dark-{seed}.flac", seconds=SECONDS, seed=seed)
    rows.append({"case": "master_low_treble", "kbps": None, "result": fake_lossless_check(dark)})
    return rows


@pytest.fixture(scope="module", params=[0, 1], ids=["seed0", "seed1"])
def table(request, tmp_path_factory):
    return calibration_table(tmp_path_factory.mktemp(f"cal{request.param}"), request.param)


def test_r6_the_encoder_gives_the_bitrates_it_is_asked_for(table):
    kbps = {r["case"]: r["kbps"] for r in table}
    for name, want, vbr in MP3_CASES:
        if vbr:
            assert kbps[name] is None, name                 # V0: frames of several bitrates
        else:
            assert kbps[name] == want, (name, kbps[name])


def test_r6_calibration_classes(table):
    print()
    for r in table:
        res = r["result"]
        cut = "-" if res.cutoff_hz is None else f"{res.cutoff_hz / 1000:.2f} kHz"
        drop = "-" if res.drop_db is None else f"{res.drop_db:.0f} dB"
        print(f"{r['case']:<20} cut {cut:<11} drop {drop:<7} -> {res.klass}")
    got = {r["case"]: r["result"].klass for r in table}
    assert got == EXPECTED
    for r in table:
        res = r["result"]
        assert res.suspicious == (res.klass == SpectralClass.STRONG)
        if res.klass == SpectralClass.STRONG:
            assert res.cutoff_hz < STRONG_MAX_HZ and "Probable MP3 convertido" in res.reason_es
            assert "«Reintentar fallos» busca otra copia" in res.reason_es and "scúchalo" not in res.reason_es
        elif res.klass == SpectralClass.AMBIGUOUS:
            assert STRONG_MAX_HZ <= res.cutoff_hz <= AMBIGUOUS_MAX_HZ
            assert res.reason_es == (f"Corte a {khz_es(res.cutoff_hz)} kHz: habitual tanto en MP3 320 como en másters "
                                     "legítimos; no se puede saber solo con el espectro.")
        else:
            assert res.reason_es is None


def test_r6_the_margins_around_the_strong_limit(table):
    """The highest cut of an MP3 at 256 kbps or less, and the lowest of a genuine master, are on each side of
    STRONG_MAX_HZ with at least one band (250 Hz) to spare."""
    by = {r["case"]: r["result"] for r in table}
    lossy_top = max(by[c].cutoff_hz for c in ("mp3_128", "mp3_160", "mp3_192", "mp3_224", "mp3_256"))
    genuine_low = min(by[c].cutoff_hz for c in ("master_lp_20000", "master_lp_20500"))
    assert lossy_top <= STRONG_MAX_HZ - 250 and genuine_low >= STRONG_MAX_HZ + 250
    assert by["mp3_320"].cutoff_hz >= STRONG_MAX_HZ + 250


@pytest.mark.parametrize("cut_khz,drop,klass", [
    (16.2, 61, SpectralClass.STRONG),       # Border One - Spectral Tension
    (18.8, 42, SpectralClass.STRONG),       # Rene Wise - Dynamic
    (19.8, 28, SpectralClass.AMBIGUOUS),    # GCOD - Incentive Systems
    (20.2, 39, SpectralClass.AMBIGUOUS),    # Justine Perry - Nova Voyager
    (20.2, 26, SpectralClass.AMBIGUOUS),    # Holden Federico - Crux
    (20.5, 44, SpectralClass.AMBIGUOUS),    # Lucy & Xhin - Lx2
])
def test_r6_his_six_measured_cuts(cut_khz, drop, klass):
    """His set report (10 Oct): the six 'posible lossless falso' of 1.0.0. The kHz there were rounded to one
    decimal, so both the rounded value and the band edge it came from classify the same."""
    assert classify(cut_khz * 1000, drop) == klass
    edge = round(cut_khz * 4) * 250            # 16.2 -> 16250, 18.8 -> 18750, 19.8 -> 19750, 20.2 -> 20250
    assert classify(edge, drop) == klass


def test_r6_no_cut_or_a_small_drop_is_no_class():
    assert classify(None, None) == SpectralClass.NONE
    assert classify(16250, 20) == SpectralClass.NONE
    assert classify(21000, 80) == SpectralClass.NONE


LOSSLESS = build_preset("lossless").accept
TAGS = {"artist": "Justine Perry", "title": "Nova Voyager"}


def test_r6_the_verdicts_keep_quality_apart_from_identity(tmp_path):
    row = TrackRow(pos=1, title="Nova Voyager", artists=["Justine Perry"], artist_display="Justine Perry",
                   expected_duration_s=SECONDS)
    ambiguous, _ = transcode(tmp_path, "amb", 320, False)
    strong, _ = transcode(tmp_path, "strong", 128, False)
    for p in (ambiguous, strong):
        import mutagen.flac
        f = mutagen.flac.FLAC(str(p))
        f["artist"], f["title"] = [TAGS["artist"]], [TAGS["title"]]
        f.save()
    v = verify_file(row, ambiguous, LOSSLESS, lossy_allowed=False, source_path_tail=None)
    assert v.state == ResultState.VERIFICADO and v.doubt is None and v.score == 100 and v.flags == []
    assert any(x.startswith("Corte a 20,0 kHz: habitual tanto en MP3 320") for x in v.reasons_es)
    s = verify_file(row, strong, LOSSLESS, lossy_allowed=False, source_path_tail=None)
    assert s.state == ResultState.REVISAR_CALIDAD and s.doubt is None and s.score == 100
    assert s.flags == ["probable_mp3_convertido"] and s.spectral.klass == SpectralClass.STRONG
    assert not any("scúchalo" in x for x in s.reasons_es)
