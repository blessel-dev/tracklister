"""yt-dlp.exe as a separate, updatable tool: metadata only (description, chapters, comments).

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

02 section 4, principle 4 and DECISIONES B.2: the official yt-dlp.exe lives in the user's tools
folder with its own cache folder (never %USERPROFILE%\\.cache), and "Actualizar yt-dlp" runs
`yt-dlp -U`. No audio is downloaded and no API key is needed. Equivalent of the research probe
fuentes/yt_meta.py, trimmed to the same fields.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

KEEP = ("id", "title", "channel", "channel_id", "uploader", "uploader_id", "duration",
        "upload_date", "view_count", "comment_count", "description", "chapters", "webpage_url")
CKEEP = ("id", "parent", "author", "author_id", "author_is_uploader", "is_pinned",
         "is_favorited", "like_count", "text", "timestamp")
COMMENT_ARGS = "youtube:comment_sort=top;max_comments=300,300,60,3"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_UNAVAILABLE = ("private video", "video unavailable", "this video is not available", "has been removed",
                "does not exist", "404")


class YtDlpError(Exception):
    """str(error) is the Spanish message for the status bar; `detail` keeps yt-dlp's own text."""

    def __init__(self, message_es: str, detail: str | None = None):
        super().__init__(message_es)
        self.detail = detail


def site_of(url: str) -> str:
    return "SoundCloud" if "soundcloud" in url.lower() or "snd.sc" in url.lower() else "YouTube"


def trim_meta(info: dict) -> dict:
    """Keep only what the tracklist chooser reads (fuentes/yt_meta.py KEEP/CKEEP)."""
    meta = {k: info.get(k) for k in KEEP}
    meta["channel"] = meta.get("channel") or info.get("uploader")
    meta["comments"] = [{k: c.get(k) for k in CKEEP} for c in (info.get("comments") or [])
                        if isinstance(c, dict)]
    return meta


def _text(b) -> str:
    if b is None:
        return ""
    return b.decode("utf-8", errors="replace") if isinstance(b, bytes) else str(b)


def _last_line(*texts: str) -> str:
    for t in texts:
        lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
        if lines:
            return lines[-1]
    return ""


class YtDlp:
    def __init__(self, exe: Path, cache_dir: Path, run=subprocess.run):
        self.exe = Path(exe)
        self.cache_dir = Path(cache_dir)
        self._run = run

    def available(self) -> bool:
        return self.exe.is_file()

    def _call(self, args: list[str], timeout_s: int):
        # --ignore-config here too (--version, -U): a yt-dlp config the user had from before never applies
        return self._run([str(self.exe), "--ignore-config", *args], capture_output=True, timeout=timeout_s,
                         stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW, check=False)

    def version(self) -> str | None:
        if not self.available():
            return None
        try:
            p = self._call(["--version"], 30)
        except (OSError, subprocess.SubprocessError):
            return None
        out = _text(p.stdout).strip()
        return out.splitlines()[0].strip() if p.returncode == 0 and out else None

    def meta_argv(self, url: str) -> list[str]:
        return [str(self.exe), "--ignore-config", "--skip-download", "--dump-single-json", "--no-warnings",
                "--no-playlist", "--flat-playlist", "--ignore-no-formats-error", "--write-comments",
                "--extractor-args", COMMENT_ARGS, "--cache-dir", str(self.cache_dir), "--", url]

    def fetch_meta(self, url: str, *, timeout_s: int = 180) -> dict:
        site = site_of(url)
        generic = f"No se pudieron leer los comentarios de {site}: actualiza yt-dlp en Ajustes."
        if not url.lower().startswith(("https://", "http://")):
            raise YtDlpError(f"El enlace no es válido: {url}")
        if not self.available():
            raise YtDlpError(f"No encuentro yt-dlp ({self.exe.name}). Actualiza yt-dlp en Ajustes o vuelve a "
                             "descomprimir Tracklister.")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        argv = self.meta_argv(url)
        try:
            p = self._run(argv, capture_output=True, timeout=timeout_s, stdin=subprocess.DEVNULL,
                          creationflags=CREATE_NO_WINDOW, check=False)
        except subprocess.TimeoutExpired as e:
            raise YtDlpError(f"{site} tarda demasiado en responder (más de {timeout_s} s). Inténtalo de nuevo "
                             "o pega la tracklist aquí.", str(e)) from e
        except OSError as e:
            raise YtDlpError(f"No se pudo ejecutar yt-dlp: {e.strerror or e}.", str(e)) from e
        out, err = _text(p.stdout), _text(p.stderr)
        if p.returncode != 0:
            detail = _last_line(err, out)
            if any(w in detail.lower() for w in _UNAVAILABLE):
                raise YtDlpError(f"Ese vídeo de {site} no está disponible (privado o borrado).", detail)
            raise YtDlpError(generic, detail)
        try:
            info = json.loads(out)
        except json.JSONDecodeError as e:
            raise YtDlpError(generic, _last_line(err) or str(e)) from e
        if not isinstance(info, dict):
            raise YtDlpError(generic, "respuesta inesperada")
        return trim_meta(info)

    def update(self) -> tuple[bool, str]:
        """`yt-dlp -U` -> (ok, Spanish message)."""
        if not self.available():
            return False, "No encuentro yt-dlp. Vuelve a descomprimir Tracklister completo."
        try:
            p = self._call(["-U"], 300)
        except subprocess.TimeoutExpired:
            return False, "La actualización de yt-dlp tarda demasiado. Inténtalo más tarde."
        except OSError as e:
            return False, f"No se pudo ejecutar yt-dlp: {e.strerror or e}."
        out, err = _text(p.stdout), _text(p.stderr)
        last = _last_line(out, err)
        if p.returncode != 0:
            return False, f"No se pudo actualizar yt-dlp: {last or 'error desconocido'}."
        if "up to date" in (out + err).lower():
            return True, f"yt-dlp ya estaba al día ({self.version() or last})."
        return True, f"yt-dlp actualizado ({self.version() or last})."
