"""Exe smoke test: Tracklister.exe starts WITHOUT Python and shows the first-run screen.

SPDX-License-Identifier: GPL-3.0-or-later

    .venv\\Scripts\\python.exe packaging\\smoke_test.py [--dist dist\\Tracklister] [--screenshot OUT.png]
                                                      [--offscreen] [--keep] [--timeout 120]

1. Copies the onedir bundle to a fresh temp folder OUTSIDE the repo, so nothing can come from
   the source tree or the venv.
2. Starts `Tracklister.exe --screenshot <png>` with a minimal environment:
   - PATH = System32 and Wbem only; the script checks that no python/py is reachable on it;
   - no PYTHON* / VIRTUAL_ENV variables;
   - TRACKLISTER_HOME = an empty temp folder, so it is a brand-new user (first-run screen);
   - keyring = the null backend, so the real Windows Credential Manager is never touched.
   Nothing connects anywhere: the first run never checks for updates and the engine never starts.
3. Checks: exit code 0, a real PNG, no error in the app log, the bundled yt-dlp.exe copied intact
   to the per-user tools folder, and the user not marked as set up.

Prints a JSON summary. Exit code 0 only when every check passes. `--offscreen` uses Qt's
offscreen platform (CI runners); without it the real Windows platform plugin is used and the
window shows for about 1.5 s.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DIST = REPO / "dist" / "Tracklister"
EXE_NAME = "Tracklister.exe"
YTDLP_REL = Path("tools") / "yt-dlp.exe"

# Windows variables a desktop app may legitimately need; everything else is dropped.
KEEP_ENV = ("SystemRoot", "windir", "SystemDrive", "ComSpec", "PATHEXT", "TEMP", "TMP", "USERPROFILE",
            "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "USERNAME", "USERDOMAIN", "COMPUTERNAME",
            "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "OS", "ProgramData",
            "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "CommonProgramFiles",
            "CommonProgramFiles(x86)", "CommonProgramW6432", "PUBLIC", "ALLUSERSPROFILE")
PYTHON_NAMES = ("python", "python3", "pythonw", "py", "pyw")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def system_path() -> str:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    return os.pathsep.join([os.path.join(root, "System32"), os.path.join(root, "System32", "Wbem")])


def clean_env(home: Path, *, offscreen: bool, base: dict[str, str] | None = None) -> dict[str, str]:
    """Minimal environment: no Python on PATH, no PYTHON* variables, a fresh TRACKLISTER_HOME."""
    base = dict(os.environ if base is None else base)
    upper = {k.upper(): k for k in base}
    env = {upper[k.upper()]: base[upper[k.upper()]] for k in KEEP_ENV if k.upper() in upper}
    env["PATH"] = system_path()
    env["TRACKLISTER_HOME"] = str(home)
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    if offscreen:
        env["QT_QPA_PLATFORM"] = "offscreen"
    return env


def python_on_path(path_value: str) -> list[str]:
    """Every python/py launcher reachable through `path_value` (only PATH, never the cwd)."""
    exts = [""] + [e.lower() for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e]
    found = []
    for folder in filter(None, path_value.split(os.pathsep)):
        for name in PYTHON_NAMES:
            for ext in exts:
                candidate = Path(folder) / f"{name}{ext}"
                if candidate.is_file():
                    found.append(str(candidate))
    return found


def png_size(path: Path) -> tuple[int, int] | None:
    """(width, height) from the IHDR chunk, or None if it is not a PNG."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def log_problems(log_file: Path) -> list[str]:
    if not log_file.is_file():
        return []
    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    return [ln[:200] for ln in lines if " ERROR " in ln or " CRITICAL " in ln or "Traceback" in ln]


def run_smoke(dist: Path, screenshot: Path, *, offscreen: bool, timeout_s: int, keep: bool) -> dict:
    checks: dict[str, bool] = {}
    info: dict = {"dist": str(dist), "offscreen": offscreen}
    if not (dist / EXE_NAME).is_file():
        return {"ok": False, "checks": {"exe_present": False}, "info": info}
    work = Path(tempfile.mkdtemp(prefix="tracklister-smoke-"))
    try:
        app_dir = work / "Tracklister"
        t0 = time.monotonic()
        shutil.copytree(dist, app_dir)
        info["copy_s"] = round(time.monotonic() - t0, 1)
        home = work / "home"
        home.mkdir()
        shot = work / "first-run.png"
        env = clean_env(home, offscreen=offscreen)
        info["path"] = env["PATH"]
        on_path = python_on_path(env["PATH"])
        checks["no_python_on_path"] = not on_path
        checks["no_python_env_vars"] = not any(k.upper().startswith("PYTHON") and k != "PYTHON_KEYRING_BACKEND"
                                               or k.upper() == "VIRTUAL_ENV" for k in env)
        checks["outside_repo"] = REPO not in app_dir.resolve().parents
        t0 = time.monotonic()
        try:
            proc = subprocess.run([str(app_dir / EXE_NAME), "--screenshot", str(shot)], env=env, cwd=str(work),
                                  stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout_s)
            info["exit_code"] = proc.returncode
        except subprocess.TimeoutExpired:
            info["exit_code"] = None
            info["error"] = f"timeout after {timeout_s} s"
        info["run_s"] = round(time.monotonic() - t0, 1)
        checks["exit_code_0"] = info.get("exit_code") == 0
        size = png_size(shot)
        info["screenshot_px"] = list(size) if size else None
        checks["screenshot_png"] = bool(size and size[0] >= 400 and size[1] >= 300)
        if size:
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(shot, screenshot)
            info["screenshot"] = str(screenshot)
        problems = log_problems(home / "data" / "logs" / "tracklister.log")
        info["log_problems"] = problems
        checks["log_clean"] = not problems
        bundled = app_dir / YTDLP_REL
        copied = home / "data" / "tools" / "yt-dlp.exe"
        if bundled.is_file():
            checks["ytdlp_copied_intact"] = copied.is_file() and sha256_file(copied) == sha256_file(bundled)
        else:
            checks["ytdlp_copied_intact"] = False
            info["ytdlp"] = "not bundled"
        settings = home / "config" / "settings.json"
        first_run_pending = True
        if settings.is_file():
            try:
                first_run_pending = not json.loads(settings.read_text(encoding="utf-8")).get("first_run_done")
            except ValueError:
                first_run_pending = False
        checks["first_run_pending"] = first_run_pending
        info["home_files"] = sorted(str(p.relative_to(home)) for p in home.rglob("*") if p.is_file())
    finally:
        if keep:
            info["kept"] = str(work)
        else:
            shutil.rmtree(work, ignore_errors=True)
    return {"ok": all(checks.values()), "checks": checks, "info": info}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", type=Path, default=DEFAULT_DIST, help="the onedir folder (dist\\Tracklister)")
    ap.add_argument("--screenshot", type=Path, default=REPO / "dist" / "smoke" / "first-run.png",
                    help="where to save the window capture")
    ap.add_argument("--offscreen", action="store_true", help="Qt offscreen platform (CI)")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--keep", action="store_true", help="keep the temp copy for inspection")
    a = ap.parse_args(argv)
    if sys.platform != "win32":
        print("Tracklister.exe solo se puede probar en Windows.")
        return 2
    result = run_smoke(a.dist.resolve(), a.screenshot.resolve(), offscreen=a.offscreen, timeout_s=a.timeout,
                       keep=a.keep)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
