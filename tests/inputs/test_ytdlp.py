"""yt-dlp wrapper with an injected `run`: argv, cache folder, trimming, errors. No network."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tracklister.inputs.ytdlp import CREATE_NO_WINDOW, YtDlp, YtDlpError, trim_meta

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "youtube"
URL = "https://www.youtube.com/watch?v=mD9ELt_Pvp4"


class FakeRun:
    """Stands in for subprocess.run. `responses` maps a marker argument to (code, stdout, stderr)."""

    def __init__(self, responses: dict[str, tuple[int, bytes, bytes]] | None = None, exc: Exception | None = None):
        self.responses = responses or {}
        self.exc = exc
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        if self.exc is not None:
            raise self.exc
        for marker, (code, out, err) in self.responses.items():
            if marker in argv:
                return subprocess.CompletedProcess(argv, code, out, err)
        return subprocess.CompletedProcess(argv, 0, b"", b"")


def full_info(meta_name: str = "mD9ELt_Pvp4") -> dict:
    """What yt-dlp prints: the fixture plus fields the app must drop."""
    info = json.loads((FIX / f"{meta_name}.meta.json").read_text(encoding="utf-8"))
    info["formats"] = [{"format_id": "251", "url": "https://example.invalid/a"}]
    info["thumbnails"] = [{"url": "https://example.invalid/t.jpg"}]
    info["http_headers"] = {"User-Agent": "x"}
    for c in info["comments"]:
        c["author_thumbnail"] = "https://example.invalid/a.jpg"
        c["_time_text"] = "hace 2 meses"
    return info


@pytest.fixture
def exe(tmp_path) -> Path:
    p = tmp_path / "tools" / "yt-dlp.exe"
    p.parent.mkdir()
    p.write_bytes(b"MZ fake")
    return p


def test_fetch_meta_argv_cache_dir_and_trim(exe, tmp_path):
    cache = tmp_path / "cache" / "yt-dlp"
    run = FakeRun({"--dump-single-json": (0, json.dumps(full_info()).encode("ascii"), b"")})
    meta = YtDlp(exe, cache, run=run).fetch_meta(URL)
    (argv, kw), = run.calls
    assert argv == [str(exe), "--ignore-config", "--skip-download", "--dump-single-json", "--no-warnings",
                    "--no-playlist", "--flat-playlist", "--ignore-no-formats-error", "--write-comments",
                    "--extractor-args", "youtube:comment_sort=top;max_comments=300,300,60,3",
                    "--cache-dir", str(cache), "--", URL]
    assert kw["capture_output"] is True and kw["timeout"] == 180 and kw["stdin"] == subprocess.DEVNULL
    assert kw["creationflags"] == CREATE_NO_WINDOW and kw.get("shell") is not True
    assert cache.is_dir()                                       # the app's own cache, created on demand
    assert "formats" not in meta and "thumbnails" not in meta
    assert meta["title"] == "FJAAK | Techno DJ Set | SECTION. | May 2026" and meta["duration"] == 3474
    assert len(meta["comments"]) == 223
    assert "author_thumbnail" not in meta["comments"][0] and "_time_text" not in meta["comments"][0]
    assert set(meta["comments"][0]) <= {"id", "parent", "author", "author_id", "author_is_uploader", "is_pinned",
                                        "is_favorited", "like_count", "text", "timestamp"}


def test_utf8_json_output_is_decoded(exe, tmp_path):
    info = {"title": "Glaður · Ñ", "description": "0:00 Exos - Glaður Og Reifur", "comments": []}
    run = FakeRun({"--dump-single-json": (0, json.dumps(info, ensure_ascii=False).encode("utf-8"), b"")})
    assert YtDlp(exe, tmp_path, run=run).fetch_meta(URL)["title"] == "Glaður · Ñ"


def test_trim_meta_uses_uploader_as_channel_for_soundcloud():
    meta = trim_meta({"title": "x", "uploader": "Plots! Klaps!", "comments": [{"text": "hi"}, "basura"]})
    assert meta["channel"] == "Plots! Klaps!" and meta["comments"] == [
        {k: ("hi" if k == "text" else None) for k in ("id", "parent", "author", "author_id", "author_is_uploader",
                                                       "is_pinned", "is_favorited", "like_count", "text",
                                                       "timestamp")}]


@pytest.mark.parametrize("code,out,err,expect", [
    (1, b"", b"ERROR: [youtube] abc: Sign in to confirm you're not a bot\n",
     "No se pudieron leer los comentarios de YouTube: actualiza yt-dlp en Ajustes."),
    (1, b"", b"ERROR: [youtube] abc: Private video. Sign in if you've been granted access\n",
     "Ese vídeo de YouTube no está disponible (privado o borrado)."),
    (0, b"no json", b"", "No se pudieron leer los comentarios de YouTube: actualiza yt-dlp en Ajustes."),
    (0, b"[1, 2]", b"", "No se pudieron leer los comentarios de YouTube: actualiza yt-dlp en Ajustes."),
])
def test_fetch_meta_errors_are_spanish(exe, tmp_path, code, out, err, expect):
    y = YtDlp(exe, tmp_path, run=FakeRun({"--dump-single-json": (code, out, err)}))
    with pytest.raises(YtDlpError) as e:
        y.fetch_meta(URL)
    assert str(e.value) == expect


def test_timeout_missing_exe_and_bad_url(exe, tmp_path):
    y = YtDlp(exe, tmp_path, run=FakeRun(exc=subprocess.TimeoutExpired(["yt-dlp"], 180)))
    with pytest.raises(YtDlpError, match="tarda demasiado"):
        y.fetch_meta(URL)
    missing = YtDlp(tmp_path / "no" / "yt-dlp.exe", tmp_path, run=FakeRun())
    assert not missing.available() and missing.version() is None
    with pytest.raises(YtDlpError, match="No encuentro yt-dlp"):
        missing.fetch_meta(URL)
    with pytest.raises(YtDlpError, match="no es válido"):
        YtDlp(exe, tmp_path, run=FakeRun()).fetch_meta("--exec calc.exe")
    sc = YtDlp(exe, tmp_path, run=FakeRun({"--dump-single-json": (1, b"", b"ERROR: boom")}))
    with pytest.raises(YtDlpError, match="comentarios de SoundCloud"):
        sc.fetch_meta("https://soundcloud.com/a/b")


def test_version_and_update(exe, tmp_path):
    run = FakeRun({"--version": (0, b"2026.08.19\n", b""),
                   "-U": (0, b"Current version: stable@2026.08.19 from yt-dlp/yt-dlp\n"
                             b"yt-dlp is up to date (stable@2026.08.19 from yt-dlp/yt-dlp)\n", b"")})
    y = YtDlp(exe, tmp_path, run=run)
    assert y.available() and y.version() == "2026.08.19"
    assert y.update() == (True, "yt-dlp ya estaba al día (2026.08.19).")
    # audit round 2, N5: --ignore-config also for --version and -U (a user's own yt-dlp config never applies)
    assert [c[0][1:] for c in run.calls] == [["--ignore-config", "--version"], ["--ignore-config", "-U"],
                                            ["--ignore-config", "--version"]]
    updated = YtDlp(exe, tmp_path, run=FakeRun({"--version": (0, b"2026.09.30\n", b""),
                                                "-U": (0, b"Updated yt-dlp to stable@2026.09.30\n", b"")}))
    assert updated.update() == (True, "yt-dlp actualizado (2026.09.30).")
    failed = YtDlp(exe, tmp_path, run=FakeRun({"-U": (100, b"", b"ERROR: Unable to write to yt-dlp.exe\n")}))
    ok, msg = failed.update()
    assert not ok and msg == "No se pudo actualizar yt-dlp: ERROR: Unable to write to yt-dlp.exe."
