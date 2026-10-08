"""Format presets: ordered engine passes plus the post-download quality rule.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Rules: 01 section 6.3 plus brief Addendum items 5 and 6.
- Every pass filters with --strict-title and --strict-artist, and --length-tol 3 when the row has
  an expected duration. Never --strict-conditions, never --fast-search, never --profile.
- MP3 is searched with --min-bitrate 320 (an unknown bitrate passes the search); after the
  download the header must say CBR >= 320 kbps (VBR, including V0, is rejected).
- .m4a is excluded from every preset (it can be AAC).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from tracklister.core.settings import CustomPreset


class PresetId(StrEnum):
    LOSSLESS = "lossless"
    CDJ = "cdj_antiguos"
    MP3 = "solo_mp3_320"
    CUSTOM = "personalizado"


LOSSLESS_FORMATS = ("flac", "wav", "aiff", "aif")
_LOSSLESS_CONTAINER = {"flac": "flac", "wav": "wav", "aiff": "aiff", "aif": "aiff"}


@dataclass(frozen=True)
class FormatPass:
    name: str                       # "lossless" | "mp3_320" | "aiff_wav" | "flac_a_aiff" | "personalizado"
    formats: tuple[str, ...]        # engine --format values
    min_bitrate: int | None = None  # --min-bitrate (never --strict-conditions)
    max_samplerate: int | None = None
    lossy: bool = False             # True -> only rows in SetDoc.lossy_approved, asked once per set
    strict_artist: bool = True
    strict_title: bool = True
    length_tol_s: int = 3           # used only when the row has expected_duration_s

    def to_dict(self) -> dict:
        return {"name": self.name, "formats": list(self.formats), "min_bitrate": self.min_bitrate,
                "max_samplerate": self.max_samplerate, "lossy": self.lossy,
                "strict_artist": self.strict_artist, "strict_title": self.strict_title,
                "length_tol_s": self.length_tol_s}


@dataclass(frozen=True)
class AcceptRule:
    containers: frozenset[str]       # real containers accepted as-is
    convert_to_aiff: frozenset[str]  # containers converted to AIFF PCM (CDJ: flac)
    mp3_min_kbps: int | None         # MP3 must be CBR >= this in the header; None = MP3 never accepted
    max_samplerate: int | None       # CDJ: 48000 (over -> downconvert with a warning)
    max_bitdepth: int | None         # CDJ: 24
    # When convert_to_aiff is non-empty (CDJ), lossless WAV/AIFF over the limits, AIFF-C and float
    # files are converted to AIFF PCM too (DECISIONES A.5). Otherwise over-limit files are rejected.

    @property
    def converts(self) -> bool:
        return bool(self.convert_to_aiff)

    def to_dict(self) -> dict:
        return {"containers": sorted(self.containers), "convert_to_aiff": sorted(self.convert_to_aiff),
                "mp3_min_kbps": self.mp3_min_kbps, "max_samplerate": self.max_samplerate,
                "max_bitdepth": self.max_bitdepth}


@dataclass(frozen=True)
class Preset:
    id: PresetId
    label_es: str
    passes: tuple[FormatPass, ...]
    accept: AcceptRule

    def to_snapshot(self) -> dict:
        """Stored in SetDoc.preset_snapshot so a re-run knows what the set was built with."""
        return {"id": str(self.id), "label_es": self.label_es,
                "passes": [p.to_dict() for p in self.passes], "accept": self.accept.to_dict()}


def _mp3_pass(*, lossy: bool, kbps: int = 320) -> FormatPass:
    return FormatPass(name="mp3_320" if kbps == 320 else f"mp3_{kbps}", formats=("mp3",),
                      min_bitrate=kbps, lossy=lossy)


def _lossless() -> Preset:
    return Preset(
        PresetId.LOSSLESS, "Lossless",
        (FormatPass("lossless", LOSSLESS_FORMATS), _mp3_pass(lossy=True)),
        AcceptRule(frozenset({"flac", "wav", "aiff"}), frozenset(), 320, None, None))


def _cdj() -> Preset:
    return Preset(
        PresetId.CDJ, "CDJ antiguos",
        (FormatPass("aiff_wav", ("aiff", "aif", "wav")), FormatPass("flac_a_aiff", ("flac",)),
         _mp3_pass(lossy=True)),
        AcceptRule(frozenset({"aiff", "wav"}), frozenset({"flac"}), 320, 48000, 24))


def _mp3_only() -> Preset:
    return Preset(PresetId.MP3, "Solo MP3 320", (_mp3_pass(lossy=False),),
                  AcceptRule(frozenset(), frozenset(), 320, None, None))


def _custom(custom: CustomPreset | None) -> Preset:
    c = custom or CustomPreset()
    wanted: list[str] = []
    for f in c.formats:
        f = str(f).strip().lower().lstrip(".")
        if f == "aif":
            f = "aiff"
        if f in ("flac", "wav", "aiff", "mp3") and f not in wanted:
            wanted.append(f)          # m4a/ogg/opus/aac are never offered (m4a may be AAC)
    lossless = [f for f in wanted if f != "mp3"]
    engine_formats: list[str] = []
    for f in lossless:
        engine_formats += ["aiff", "aif"] if f == "aiff" else [f]
    kbps = int(c.min_mp3_kbps or 320)
    passes: list[FormatPass] = []
    if engine_formats:
        passes.append(FormatPass("personalizado", tuple(engine_formats), max_samplerate=c.max_samplerate))
    if "mp3" in wanted:
        passes.append(_mp3_pass(lossy=False, kbps=kbps))
    elif c.allow_lossy_fallback:
        passes.append(_mp3_pass(lossy=True, kbps=kbps))
    if not passes:   # nothing usable chosen: fall back to the default lossless formats
        passes.append(FormatPass("personalizado", LOSSLESS_FORMATS, max_samplerate=c.max_samplerate))
        lossless = ["flac", "wav", "aiff"]
    mp3_ok = "mp3" in wanted or c.allow_lossy_fallback
    return Preset(PresetId.CUSTOM, "Personalizado", tuple(passes),
                  AcceptRule(frozenset(_LOSSLESS_CONTAINER[f] for f in lossless), frozenset(),
                             kbps if mp3_ok else None, c.max_samplerate, c.max_bitdepth))


def build_preset(preset_id: str, custom: CustomPreset | None = None) -> Preset:
    pid = PresetId(preset_id)
    if pid == PresetId.LOSSLESS:
        return _lossless()
    if pid == PresetId.CDJ:
        return _cdj()
    if pid == PresetId.MP3:
        return _mp3_only()
    return _custom(custom)


def relaxed(p: FormatPass) -> FormatPass:
    """'Reintentar fallos': same pass without --strict-artist (title filter stays)."""
    return replace(p, strict_artist=False)
