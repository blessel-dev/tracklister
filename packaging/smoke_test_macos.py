"""macOS smoke test of the built Tracklister.app: it starts, copies yt-dlp out cleanly, and is signed,
thin arm64 and complete, also after its zip is unpacked.

SPDX-License-Identifier: GPL-3.0-or-later

    .venv/bin/python packaging/smoke_test_macos.py [--app dist/Tracklister.app]
        [--zip dist/release/Tracklister-<v>-macos-arm64.zip] --screenshot OUT.png --json OUT.json
        [--offscreen] [--keep] [--timeout 120]

The six checks (report 3.7):
1. app_starts: a copy of the .app (made with ditto in a fresh temp folder outside the repo) runs
   `Contents/MacOS/Tracklister --screenshot <png>` with a minimal environment: PATH=/usr/bin:/bin:/usr/sbin:/sbin,
   HOME/TMPDIR/USER/LOGNAME/LANG/LC_* kept, no PYTHON* or VIRTUAL_ENV, TRACKLISTER_HOME a new empty folder
   (a brand-new user), the null keyring (the runner's Keychain is never touched). It must exit 0, save a
   PNG of at least 400 x 300 and log no error. Nothing connects anywhere: the first run checks no update
   and starts no engine. (No «no python on PATH» check: macOS ships /usr/bin/python3 as a stub.)
2. ytdlp_copy: before that run, com.apple.quarantine is planted on the copy's
   Contents/Resources/tools/yt-dlp_macos (never on the app's executable). The app's own copy,
   <home>/data/tools/yt-dlp, must have the pin's SHA-256, mode 0755 and NO quarantine.
3. codesign_verify: `codesign --verify --deep --strict` accepts the built .app.
4. info_plist_arm64: Info.plist has the identifier, versions and keys of packaging/tracklister.spec and an
   icon, and Contents/MacOS/Tracklister is a thin arm64 Mach-O (a universal binary fails).
5. engine_sha256: the Sockseek .tar.gz in Contents/Resources/engines has the macOS pin's SHA-256.
6. zip_roundtrip: `ditto -x -k` of the release zip gives a single top-level Tracklister.app, and that
   unpacked app passes check 3 too.

Prints the JSON ({"ok", "checks", "info"}; info["details"] says why a check failed) and writes it to --json.
Exit code 0 when every check passes, 1 otherwise, 2 on a computer that is not a Mac.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for _p in (str(REPO / "src"), str(HERE)):      # appended, so nothing on sys.path is shadowed
    if _p not in sys.path:
        sys.path.append(_p)

import build  # noqa: E402  (packaging/build.py: zip_name, the Info.plist expectations, the macOS tools)
from smoke_test import log_problems, png_size  # noqa: E402  (packaging/smoke_test.py, the Windows one)
from tracklister.core.bundled import ytdlp_pin  # noqa: E402
from tracklister.engine.spec import asset_name, engine_pins  # noqa: E402

APP_NAME = "Tracklister.app"
DEFAULT_APP = REPO / "dist" / APP_NAME
DEFAULT_ZIP = REPO / "dist" / "release" / build.zip_name("darwin")
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
KEEP_ENV = ("HOME", "TMPDIR", "USER", "LOGNAME", "LANG")
QUARANTINE = "com.apple.quarantine"
QUARANTINE_VALUE = "0081;00000000;Tracklister-smoke;"       # flags;time;agent;uuid, like a download's mark
CHECKS = ("app_starts", "ytdlp_copy", "codesign_verify", "info_plist_arm64", "engine_sha256", "zip_roundtrip")

MH_MAGIC_64 = b"\xcf\xfa\xed\xfe"          # 64-bit Mach-O, little endian (arm64 and x86_64)
FAT_MAGICS = {b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}
CPU_TYPES = {0x0100000C: "arm64", 0x01000007: "x86_64"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def macho_arch(path: Path) -> str:
    """'arm64' or 'x86_64' for a thin 64-bit Mach-O, 'universal' for a fat one, else 'unknown'."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return "unknown"
    if head[:4] in FAT_MAGICS:
        return "universal"
    if len(head) == 8 and head[:4] == MH_MAGIC_64:
        cputype = struct.unpack("<I", head[4:8])[0]
        return CPU_TYPES.get(cputype, f"cputype {cputype:#x}")
    return "unknown"


def clean_env(home: Path, *, offscreen: bool, base: dict[str, str] | None = None) -> dict[str, str]:
    """Minimal environment: the system PATH, no PYTHON* variables, a fresh TRACKLISTER_HOME, the null keyring."""
    base = dict(os.environ if base is None else base)
    env = {k: v for k, v in base.items() if k in KEEP_ENV or k.startswith("LC_")}
    env["PATH"] = SYSTEM_PATH
    env["TRACKLISTER_HOME"] = str(home)
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    if offscreen:
        env["QT_QPA_PLATFORM"] = "offscreen"
    return env


def _tool(cmd: list[str], run=None, timeout: int = 600) -> subprocess.CompletedProcess:
    return (run or subprocess.run)(cmd, capture_output=True, text=True, timeout=timeout)


def has_quarantine(path: Path, run=None) -> bool:
    """True when `xattr -p com.apple.quarantine` reads the mark (it fails when there is none)."""
    return _tool([build.XATTR, "-p", QUARANTINE, str(path)], run).returncode == 0


def plant_quarantine(path: Path, run=None) -> bool:
    return _tool([build.XATTR, "-w", QUARANTINE, QUARANTINE_VALUE, str(path)], run).returncode == 0


def codesign_verify(app: Path, run=None) -> tuple[bool, str]:
    r = _tool([build.CODESIGN, "--verify", "--deep", "--strict", "--verbose=2", str(app)], run)
    text = " / ".join(((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-4:])
    return r.returncode == 0, text


def info_plist_check(app: Path) -> tuple[bool, str]:
    plist = app / "Contents" / "Info.plist"
    if not plist.is_file():
        return False, "falta Contents/Info.plist"
    try:
        info = plistlib.loads(plist.read_bytes())
    except Exception as e:  # noqa: BLE001 - a broken plist is a failed check
        return False, f"Info.plist ilegible: {e}"
    problems = build.info_plist_problems(info)
    arch = macho_arch(app / "Contents" / "MacOS" / "Tracklister")
    if arch != "arm64":
        problems.append(f"Contents/MacOS/Tracklister es {arch}, no arm64 solo")
    return not problems, "; ".join(problems) or f"{info.get('CFBundleIdentifier')} {info.get('CFBundleVersion')} arm64"


def engine_check(app: Path) -> tuple[bool, str]:
    pin = engine_pins("darwin")["sockseek-3.0.5"]
    tar = app / "Contents" / "Resources" / "engines" / asset_name(pin)
    if not tar.is_file():
        return False, f"falta Contents/Resources/engines/{tar.name}"
    got = sha256_file(tar)
    return got == pin.asset_sha256, f"{tar.name} sha256={got[:12]}..."


def ytdlp_copy_check(home: Path, run=None) -> tuple[bool, str]:
    pin = ytdlp_pin("darwin")
    copy = home / "data" / "tools" / pin.exe_name
    if not copy.is_file():
        part = copy.with_name(copy.name + ".part")
        return False, f"no existe {copy.name} en data/tools" + (" (quedó un .part)" if part.exists() else "")
    problems = []
    if sha256_file(copy) != pin.sha256:
        problems.append("SHA-256 distinto del pin")
    mode = stat.S_IMODE(copy.stat().st_mode)
    if mode != 0o755:
        problems.append(f"modo {mode:o}, no 755")
    if has_quarantine(copy, run):
        problems.append("lleva com.apple.quarantine")
    return not problems, "; ".join(problems) or "sha256 del pin, modo 755, sin cuarentena"


def zip_roundtrip(zip_path: Path, work: Path, run=None) -> tuple[bool, str]:
    if not zip_path.is_file():
        return False, f"no existe {zip_path.name}"
    out = work / "unzip"
    out.mkdir()
    r = _tool([build.DITTO, "-x", "-k", str(zip_path), str(out)], run)
    if r.returncode != 0:
        return False, "ditto -x falló: " + " / ".join(((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-3:])
    # __MACOSX (ditto's --sequesterRsrc metadata) is read back as attributes by ditto and Archive Utility
    top = sorted(p.name for p in out.iterdir() if p.name != "__MACOSX")
    if top != [APP_NAME]:
        return False, f"el zip no tiene solo {APP_NAME} arriba: {top[:5]}"
    ok, text = codesign_verify(out / APP_NAME, run)
    return ok, ("descomprimida y firmada: " if ok else "la app descomprimida no verifica: ") + text


def run_smoke(app: Path, zip_path: Path, screenshot: Path, *, offscreen: bool, timeout_s: int, keep: bool,
              run=None) -> dict:
    checks = {name: False for name in CHECKS}
    details: dict[str, str] = {}
    info: dict = {"app": str(app), "zip": str(zip_path), "offscreen": offscreen, "details": details}
    if not (app / "Contents" / "MacOS" / "Tracklister").is_file():
        details["app_starts"] = f"no existe {app / 'Contents' / 'MacOS' / 'Tracklister'}"
        return {"ok": False, "checks": checks, "info": info}
    work = Path(tempfile.mkdtemp(prefix="tracklister-smoke-"))
    try:
        info["outside_repo"] = REPO.resolve() not in work.resolve().parents
        copy = work / APP_NAME
        t0 = time.monotonic()
        r = _tool([build.DITTO, str(app), str(copy)], run)
        info["copy_s"] = round(time.monotonic() - t0, 1)
        if r.returncode != 0:
            details["app_starts"] = "ditto no pudo copiar la app"
        else:
            bundled_ytdlp = copy / "Contents" / "Resources" / "tools" / ytdlp_pin("darwin").asset_name
            info["quarantine_planted"] = bundled_ytdlp.is_file() and plant_quarantine(bundled_ytdlp, run)
            home = work / "home"
            home.mkdir()
            shot = work / "first-run.png"
            env = clean_env(home, offscreen=offscreen)
            info["path"] = env["PATH"]
            t0 = time.monotonic()
            try:
                proc = subprocess.run([str(copy / "Contents" / "MacOS" / "Tracklister"), "--screenshot", str(shot)],
                                      env=env, cwd=str(work), stdin=subprocess.DEVNULL, capture_output=True,
                                      timeout=timeout_s)
                info["exit_code"] = proc.returncode
                info["stderr_tail"] = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-8:]
            except subprocess.TimeoutExpired:
                info["exit_code"] = None
            info["run_s"] = round(time.monotonic() - t0, 1)
            size = png_size(shot)
            info["screenshot_px"] = list(size) if size else None
            if size:
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(shot, screenshot)
                info["screenshot"] = str(screenshot)
            problems = log_problems(home / "data" / "logs" / "tracklister.log")
            info["log_problems"] = problems
            starts = [] if info.get("exit_code") == 0 else [f"código de salida {info.get('exit_code')}"
                                                             + (" (tiempo agotado)" if info.get("exit_code") is None else "")]
            if not (size and size[0] >= 400 and size[1] >= 300):
                starts.append(f"captura {size or 'ausente'}")
            starts += [f"log: {p}" for p in problems[:2]]
            checks["app_starts"] = not starts
            details["app_starts"] = "; ".join(starts) or f"arranca, captura {size[0]}x{size[1]}, log limpio"
            if info["quarantine_planted"]:
                checks["ytdlp_copy"], details["ytdlp_copy"] = ytdlp_copy_check(home, run)
            else:
                details["ytdlp_copy"] = "no se pudo marcar con cuarentena el yt-dlp_macos de la copia"
            info["home_files"] = sorted(str(p.relative_to(home)) for p in home.rglob("*") if p.is_file())[:40]
        checks["codesign_verify"], details["codesign_verify"] = codesign_verify(app, run)
        checks["info_plist_arm64"], details["info_plist_arm64"] = info_plist_check(app)
        checks["engine_sha256"], details["engine_sha256"] = engine_check(app)
        checks["zip_roundtrip"], details["zip_roundtrip"] = zip_roundtrip(zip_path, work, run)
    finally:
        if keep:
            info["kept"] = str(work)
        else:
            shutil.rmtree(work, ignore_errors=True)
    return {"ok": all(checks.values()), "checks": checks, "info": info}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--app", type=Path, default=DEFAULT_APP, help="the built .app (dist/Tracklister.app)")
    ap.add_argument("--zip", type=Path, default=DEFAULT_ZIP, help="its release zip (dist/release/...-macos-arm64.zip)")
    ap.add_argument("--screenshot", type=Path, default=REPO / "dist" / "smoke" / "first-run.png",
                    help="where to save the window capture")
    ap.add_argument("--json", type=Path, default=REPO / "dist" / "ci" / "smoke.json", help="where to write the result")
    ap.add_argument("--offscreen", action="store_true", help="Qt offscreen platform (CI)")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--keep", action="store_true", help="keep the temp copy for inspection")
    a = ap.parse_args(argv)
    if sys.platform != "darwin":
        print("Tracklister.app solo se puede probar en un Mac (este script es para el job de macOS).")
        return 2
    result = run_smoke(a.app.resolve(), a.zip.resolve(), a.screenshot.resolve(), offscreen=a.offscreen,
                       timeout_s=a.timeout, keep=a.keep)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    a.json.parent.mkdir(parents=True, exist_ok=True)
    a.json.write_text(text + "\n", encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
