"""What a downloaded file really is: container by header (not extension), stream facts, tags.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

mutagen gives header facts and tags (a mutagen File with no tags is FALSY: always `is not None`);
soundfile decodes to the end to measure the real duration (truncated downloads).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import soundfile as sf

_EXT_CONTAINER = {".flac": "flac", ".wav": "wav", ".wave": "wav", ".aif": "aiff", ".aiff": "aiff",
                  ".aifc": "aiff", ".mp3": "mp3", ".m4a": "m4a", ".mp4": "m4a", ".aac": "m4a",
                  ".alac": "m4a", ".ogg": "ogg", ".oga": "ogg", ".opus": "opus"}
LOSSLESS_CONTAINERS = frozenset({"flac", "wav", "aiff"})
_GENERIC_TAG = re.compile(r"^\s*(unknown( artist| title)?|track\s*\d*|pista\s*\d*|audio\s*track|untitled|"
                          r"sin t[ií]tulo|desconocido|various( artists)?|va)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class AudioInfo:
    path: Path
    container: str               # flac|wav|aiff|mp3|m4a|ogg|opus|unknown (by header)
    ext_matches: bool
    duration_s: float | None     # from the header
    decoded_duration_s: float | None
    samplerate: int | None
    bitdepth: int | None
    channels: int | None
    bitrate_kbps: int | None
    bitrate_mode: str | None     # "cbr"|"vbr"|"abr"|"unknown" (MP3 only)
    is_aifc: bool
    is_float: bool
    tag_artist: str | None
    tag_title: str | None
    tag_album: str | None
    # MP3 whose header does not say CBR or VBR (no Xing/Info/VBRI frame): the bitrate of every frame
    # read at the start and around 25/50/75 % of the file; () = no frame could be read. None otherwise.
    mp3_frame_kbps: tuple[int, ...] | None = None
    # libsndfile's codec of the audio ("PCM_16", "FLOAT", "ULAW", "IMA_ADPCM"...); None = it cannot read it.
    # A WAV or AIFF may hold a lossy codec (audit round 4, B6).
    subtype: str | None = None

    @property
    def is_lossless(self) -> bool:
        return self.container in LOSSLESS_CONTAINERS

    @property
    def has_tags(self) -> bool:
        return bool(self.tag_artist or self.tag_title)


def _sniff(path: Path) -> tuple[str, bool]:
    """(container, is_aifc) from the first bytes."""
    try:
        with open(path, "rb") as f:
            head = f.read(64)
            if head[:3] == b"ID3" and len(head) >= 10:
                size = ((head[6] & 0x7F) << 21) | ((head[7] & 0x7F) << 14) | ((head[8] & 0x7F) << 7) | (head[9] & 0x7F)
                f.seek(10 + size)
                inner = f.read(16)
                if inner[:4] == b"fLaC":
                    return "flac", False
                if len(inner) >= 2 and inner[0] == 0xFF and (inner[1] & 0xE0) == 0xE0:
                    return "mp3", False
                return "mp3", False
    except OSError:
        return "unknown", False
    if head[:4] == b"fLaC":
        return "flac", False
    if head[:4] in (b"RIFF", b"RF64", b"BW64") and head[8:12] == b"WAVE":
        return "wav", False
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return "aiff", head[8:12] == b"AIFC"
    if head[:4] == b"OggS":
        return ("opus" if b"OpusHead" in head else "ogg"), False
    if head[4:8] == b"ftyp":
        return "m4a", False
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return "mp3", False
    return "unknown", False


def _first(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    if v is None:
        return None
    s = str(getattr(v, "text", [v])[0] if hasattr(v, "text") else v).strip()
    return s or None


def _tags(mf) -> tuple[str | None, str | None, str | None]:
    tags = getattr(mf, "tags", None)
    if tags is None:
        return None, None, None
    keys = {"artist": ("TPE1", "artist", "ARTIST", "\xa9ART", "Author"),
            "title": ("TIT2", "title", "TITLE", "\xa9nam", "Title"),
            "album": ("TALB", "album", "ALBUM", "\xa9alb")}
    out = []
    for field in ("artist", "title", "album"):
        val = None
        for k in keys[field]:
            try:
                if k in tags:
                    val = _first(tags[k])
                    if val:
                        break
            except (KeyError, ValueError, TypeError):
                continue
        if val and _GENERIC_TAG.match(val):
            val = None
        out.append(val)
    return out[0], out[1], out[2]


def read_tags(path: Path) -> tuple[str | None, str | None]:
    """(artist, title) from the tags only: fast, no decoding (used to scan whole folders)."""
    import mutagen
    try:
        mf = mutagen.File(str(path))
    except Exception:  # noqa: BLE001
        return None, None
    if mf is None:
        return None, None
    a, t, _ = _tags(mf)
    return a, t


_SUBTYPE_BITS = {"PCM_S8": 8, "PCM_U8": 8, "PCM_16": 16, "PCM_24": 24, "PCM_32": 32, "FLOAT": 32, "DOUBLE": 64}

# MPEG audio Layer III frame headers (ISO 11172-3 / 13818-3): kbps by bitrate index, Hz by version.
_L3_KBPS = {1: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),        # MPEG-1
            2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)}            # MPEG-2 / 2.5
_SAMPLERATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}
MP3_HEAD_FRAMES = 30          # frames read right after the ID3v2 tag
MP3_PROBE_FRAMES = 10         # frames read at each probe point
MP3_PROBE_POINTS = (0.25, 0.5, 0.75)
_RESYNC_WINDOW = 1 << 16      # bytes searched for a frame header at each probe point


def _l3_frame(buf: bytes, i: int) -> tuple[int, int, int] | None:
    """(kbps, frame length, version+samplerate key) of a Layer III header at buf[i], or None."""
    if i + 4 > len(buf) or buf[i] != 0xFF or (buf[i + 1] & 0xE0) != 0xE0:
        return None
    ver = (buf[i + 1] >> 3) & 3            # 3 = MPEG-1, 2 = MPEG-2, 0 = MPEG-2.5, 1 = reserved
    layer = (buf[i + 1] >> 1) & 3          # 1 = Layer III
    bi, si, pad = (buf[i + 2] >> 4) & 0xF, (buf[i + 2] >> 2) & 3, (buf[i + 2] >> 1) & 1
    if ver == 1 or layer != 1 or bi in (0, 15) or si == 3:    # free format (0) cannot be checked either
        return None
    kbps = _L3_KBPS[1 if ver == 3 else 2][bi]
    sr = _SAMPLERATES[ver][si]
    length = (144000 if ver == 3 else 72000) * kbps // sr + pad
    return kbps, length, (ver << 2) | si


def _frame_run(buf: bytes, n: int) -> list[int]:
    """Bitrates of up to n consecutive frames from the first real header in buf (resync). A header only
    counts when two more headers of the same MPEG version and sample rate follow it, so random audio
    bytes never pass for one."""
    end = min(len(buf), _RESYNC_WINDOW)
    i = 0
    while i < end:
        h = _l3_frame(buf, i)
        if h is not None:
            h2 = _l3_frame(buf, i + h[1])
            h3 = _l3_frame(buf, i + h[1] + h2[1]) if h2 is not None and h2[2] == h[2] else None
            if h3 is not None and h3[2] == h[2]:
                break
        i += 1
    else:
        return []
    out: list[int] = []
    key = _l3_frame(buf, i)[2]
    while len(out) < n:
        h = _l3_frame(buf, i)
        if h is None or h[2] != key or i + h[1] > len(buf):
            break
        out.append(h[0])
        i += h[1]
    return out


def mp3_frame_bitrates(path: Path) -> tuple[int, ...]:
    """Bitrates of the MPEG frames at the start of the audio and around 25/50/75 % of the file.

    Used when the header says nothing about CBR/VBR (no Xing/Info/VBRI frame), where mutagen only
    reports the FIRST frame's bitrate: a VBR file starting with a 320 kbps frame would pass for CBR."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(10)
            start = 0
            if head[:3] == b"ID3" and len(head) == 10:
                start = 10 + (((head[6] & 0x7F) << 21) | ((head[7] & 0x7F) << 14) | ((head[8] & 0x7F) << 7)
                              | (head[9] & 0x7F)) + (10 if head[5] & 0x10 else 0)
            f.seek(start)
            seen = _frame_run(f.read(MP3_HEAD_FRAMES * 1441 + _RESYNC_WINDOW), MP3_HEAD_FRAMES)
            if not seen:
                return ()
            for frac in MP3_PROBE_POINTS:
                f.seek(start + int((size - start) * frac))
                seen += _frame_run(f.read(MP3_PROBE_FRAMES * 1441 + _RESYNC_WINDOW), MP3_PROBE_FRAMES)
            return tuple(seen)
    except OSError:
        return ()


def decoded_duration(path: Path) -> tuple[float | None, int | None, str | None]:
    """Decode to the end; returns (seconds actually decodable, samplerate, subtype)."""
    try:
        with sf.SoundFile(str(path)) as f:
            sr, subtype = f.samplerate, f.subtype
            frames = 0
            while True:
                try:
                    block = f.read(65536, dtype="float32", always_2d=True)
                except (RuntimeError, sf.LibsndfileError):
                    break
                if len(block) == 0:
                    break
                frames += len(block)
            return frames / float(sr), sr, subtype
    except (RuntimeError, sf.LibsndfileError, OSError, TypeError, ValueError):
        return None, None, None


def header_duration(path: Path) -> tuple[float | None, int | None, str | None]:
    """(seconds, samplerate, subtype) from the header only, without decoding the audio."""
    try:
        i = sf.info(str(path))
        return float(i.duration), int(i.samplerate), str(i.subtype)
    except (RuntimeError, sf.LibsndfileError, OSError, TypeError, ValueError):
        return None, None, None


def probe(path: Path, *, decode: bool = True) -> AudioInfo:
    """decode=False reads the headers only and trusts them for the duration (decoded_duration_s is the
    header duration): for files that were fully verified before, like the library's (fast)."""
    import mutagen
    from mutagen.mp3 import BitrateMode

    path = Path(path)
    container, is_aifc = _sniff(path)
    ext_container = _EXT_CONTAINER.get(path.suffix.lower())
    mf = None
    try:
        # Open with the class of the REAL container: a renamed file (.flac that is an MP3)
        # would otherwise be parsed by the wrong reader.
        from mutagen.aiff import AIFF
        from mutagen.flac import FLAC
        from mutagen.mp3 import MP3
        from mutagen.mp4 import MP4
        from mutagen.oggopus import OggOpus
        from mutagen.oggvorbis import OggVorbis
        from mutagen.wave import WAVE
        cls = {"flac": FLAC, "mp3": MP3, "wav": WAVE, "aiff": AIFF, "m4a": MP4, "ogg": OggVorbis,
               "opus": OggOpus}.get(container)
        mf = cls(str(path)) if cls is not None else mutagen.File(str(path))
    except Exception:  # noqa: BLE001 - corrupt/unknown files must not crash the run
        try:
            mf = mutagen.File(str(path))
        except Exception:  # noqa: BLE001
            mf = None
    duration = samplerate = bitdepth = channels = bitrate = None
    mode: str | None = None
    if mf is not None:
        info = mf.info
        duration = float(getattr(info, "length", 0) or 0) or None
        samplerate = int(getattr(info, "sample_rate", 0) or 0) or None
        bitdepth = int(getattr(info, "bits_per_sample", 0) or 0) or None
        channels = int(getattr(info, "channels", 0) or 0) or None
        br = int(getattr(info, "bitrate", 0) or 0)
        bitrate = int(round(br / 1000)) if br else None
        if container == "mp3":
            bm = getattr(info, "bitrate_mode", None)
            mode = {BitrateMode.CBR: "cbr", BitrateMode.VBR: "vbr", BitrateMode.ABR: "abr"}.get(bm, "unknown")
    artist, title, album = _tags(mf) if mf is not None else (None, None, None)
    dec, sr2, subtype = decoded_duration(path) if decode else header_duration(path)
    if samplerate is None:
        samplerate = sr2
    if bitdepth is None and subtype in _SUBTYPE_BITS and container in LOSSLESS_CONTAINERS:
        bitdepth = _SUBTYPE_BITS[subtype]
    is_float = bool(subtype in ("FLOAT", "DOUBLE")) and container in ("wav", "aiff")
    if duration is None:
        duration = dec
    frame_kbps = mp3_frame_bitrates(path) if container == "mp3" and mode in (None, "unknown") else None
    return AudioInfo(path=path, container=container, ext_matches=(ext_container == container),
                     duration_s=duration, decoded_duration_s=dec, samplerate=samplerate, bitdepth=bitdepth,
                     channels=channels, bitrate_kbps=bitrate, bitrate_mode=mode, is_aifc=is_aifc,
                     is_float=is_float, tag_artist=artist, tag_title=title, tag_album=album,
                     mp3_frame_kbps=frame_kbps, subtype=subtype)
