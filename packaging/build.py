"""Build Tracklister for Windows: verify the pins, run PyInstaller, add engines/yt-dlp/licences, check, zip.

SPDX-License-Identifier: GPL-3.0-or-later

    .venv\\Scripts\\python.exe packaging\\build.py                     # dist\\Tracklister\\ (onedir) + checks
    .venv\\Scripts\\python.exe packaging\\build.py --fetch             # first download missing engines/yt-dlp
    .venv\\Scripts\\python.exe packaging\\build.py --zip               # + dist\\release\\ (zip, sources, SHA256SUMS.txt)
    .venv\\Scripts\\python.exe packaging\\build.py --skip-pyinstaller  # re-assemble and re-check dist\\Tracklister

Layout of dist\\Tracklister\\ (what the user unzips):
    Tracklister.exe, _internal\\            PyInstaller onedir (assets in _internal\\tracklister\\assets)
    engines\\<pinned zip>, engines\\<id>\\    engine zips (SHA-256 pinned, unpacked by the app on first use),
                                           with their LICENSE and SOURCE.md
    tools\\yt-dlp.exe, tools\\yt-dlp\\        yt-dlp (copied by the app to %LOCALAPPDATA%), its licences
    licenses\\                              licence texts of Python, PyInstaller, Qt and every Python package
    LICENSE.txt, NOTICES.txt                GPL-3.0 text and the third-party notices (third_party/NOTICES.md)

Never runs the engines or yt-dlp, and never touches the network unless --fetch is given.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import zipfile
from importlib import metadata
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for _p in (str(REPO / "src"), str(HERE)):      # appended, so nothing on sys.path is shadowed
    if _p not in sys.path:
        sys.path.append(_p)

import fetch_ytdlp  # noqa: E402  (packaging/fetch_ytdlp.py)
from tracklister import __version__  # noqa: E402
from tracklister.engine.spec import ENGINE_PINS, SOURCE_ARCHIVES, asset_name, dev_bin_dir  # noqa: E402

APP = "Tracklister"
SPEC = HERE / "tracklister.spec"
DIST = REPO / "dist"
WORK = REPO / "build" / "pyinstaller"
THIRD_PARTY = REPO / "third_party"
RUNTIME_LOCK = REPO / "requirements.lock.txt"
ZIP_NAME = f"{APP}-{__version__}-win64.zip"
SUMS_NAME = "SHA256SUMS.txt"

# Never part of the bundle: dev/test/brand-build modules, the source tree, scratch and user data.
FORBIDDEN_PARTS = {"scipy", "sklearn", "PIL", "pytest", "_pytest", "pytestqt", "tests", ".tmp", ".git", ".venv",
                   "setuptools", "pkg_resources"}
FORBIDDEN_NAMES = re.compile(r"(?i)^(settings\.json|library\.json|update\.json|credentials.*|.*\.conf|.*\.log|"
                             r"sldl\.conf|\.env)$")
LICENCE_FILE = re.compile(r"(?i)(licen[cs]e|copying|notice|authors)")


class BuildError(Exception):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def runtime_pins(lock: Path = RUNTIME_LOCK) -> list[tuple[str, str]]:
    """(name, version) of every runtime pin: exactly what PyInstaller may put in the bundle."""
    pins = []
    for raw in lock.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name, _, version = line.partition("==")
        if not version:
            raise BuildError(f"{lock.name}: pin sin versión exacta: {raw!r}")
        pins.append((name.strip(), version.strip()))
    return pins


# ---- 1. inputs ----------------------------------------------------------------------------------------------------
def check_inputs(*, fetch: bool, need_sources: bool) -> None:
    cmd = [sys.executable, str(REPO / "tools" / "fetch_engine.py")] + ([] if fetch else ["--verify-only"])
    if subprocess.run(cmd, cwd=str(REPO)).returncode != 0:
        raise BuildError("Los zips de los motores faltan o no coinciden con su SHA-256 (tools/fetch_engine.py).")
    if fetch:
        ytdlp_ok = fetch_ytdlp.fetch() == 0
    else:
        problems = fetch_ytdlp.verify_local()
        for line in problems:
            print(line)
        ytdlp_ok = not problems
    if not ytdlp_ok:
        raise BuildError("yt-dlp.exe falta o no coincide con su SHA-256 (packaging/fetch_ytdlp.py).")
    required = [REPO / "LICENSE", THIRD_PARTY / "NOTICES.md", THIRD_PARTY / "licenses" / "LGPL-3.0.txt",
                THIRD_PARTY / "licenses" / "Apache-2.0.txt",
                fetch_ytdlp.THIRD_PARTY / "LICENSE", fetch_ytdlp.THIRD_PARTY / "THIRD_PARTY_LICENSES.txt",
                fetch_ytdlp.THIRD_PARTY / "SOURCE.md"]
    for engine_id in ENGINE_PINS:
        required += [THIRD_PARTY / "engines" / engine_id / "LICENSE", THIRD_PARTY / "engines" / engine_id / "SOURCE.md"]
    if need_sources:
        required += [source_archive(engine_id) for engine_id in SOURCE_ARCHIVES]
    missing = [str(p.relative_to(REPO)) for p in required if not p.is_file()]
    if missing:
        raise BuildError("Faltan archivos: " + ", ".join(missing))


def source_archive(engine_id: str) -> Path:
    return dev_bin_dir() / "src" / f"{engine_id}-src.zip"


# ---- 2. PyInstaller -----------------------------------------------------------------------------------------------
def run_pyinstaller(dist: Path) -> Path:
    log = REPO / "build" / "pyinstaller.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm", "--clean",
           "--distpath", str(dist), "--workpath", str(WORK)]
    print("PyInstaller...", " ".join(cmd[2:]))
    with open(log, "w", encoding="utf-8", errors="replace") as out:
        code = subprocess.run(cmd, cwd=str(REPO), stdout=out, stderr=subprocess.STDOUT).returncode
    if code != 0:
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
        raise BuildError("PyInstaller falló:\n" + "\n".join(tail))
    return dist / APP


# ---- 3. assemble --------------------------------------------------------------------------------------------------
def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def openssl_version() -> str:
    """'3.0.15' from ssl.OPENSSL_VERSION ('OpenSSL 3.0.15 3 Sep 2024') of the building Python."""
    import ssl
    m = re.search(r"OpenSSL (\d+\.\d+\.\d+\w*)", ssl.OPENSSL_VERSION)
    return m.group(1) if m else "3"


def package_licence_files(name: str) -> tuple[str, list[tuple[Path, str]]]:
    """(version, [(file, path inside the licence folder)]) from the installed dist-info.

    PySide6/shiboken6 wheels only carry the Qt *commercial* licence reference; Tracklister uses
    them under the LGPL-3.0 option, so that text is shipped instead (see NOTICES)."""
    dist = metadata.distribution(name)
    if name.lower().startswith(("pyside6", "shiboken6")):
        return dist.version, [(THIRD_PARTY / "licenses" / "LGPL-3.0.txt", "LGPL-3.0.txt")]
    out = []
    for f in dist.files or []:
        parts = Path(str(f)).parts
        if not parts or not parts[0].endswith(".dist-info") or not LICENCE_FILE.search(parts[-1]):
            continue
        rel = Path(*parts[1:])
        if rel.parts and rel.parts[0] == "licenses":
            rel = Path(*rel.parts[1:])
        out.append((Path(dist.locate_file(f)), str(rel)))
    if not out:
        raise BuildError(f"{name} {dist.version} no trae ningún archivo de licencia en su dist-info.")
    return dist.version, out


def assemble(app_dir: Path) -> None:
    if not (app_dir / f"{APP}.exe").is_file():
        raise BuildError(f"No existe {app_dir / (APP + '.exe')}: ejecuta el build sin --skip-pyinstaller.")
    for sub in ("engines", "tools", "licenses"):
        shutil.rmtree(app_dir / sub, ignore_errors=True)
    for engine_id, pin in ENGINE_PINS.items():
        _copy(dev_bin_dir() / asset_name(pin), app_dir / "engines" / asset_name(pin))
        for name in ("LICENSE", "SOURCE.md"):
            _copy(THIRD_PARTY / "engines" / engine_id / name, app_dir / "engines" / engine_id / name)
    _copy(fetch_ytdlp.exe_path(), app_dir / "tools" / fetch_ytdlp.EXE_NAME)
    for name in ("LICENSE", "THIRD_PARTY_LICENSES.txt", "SOURCE.md"):
        _copy(fetch_ytdlp.THIRD_PARTY / name, app_dir / "tools" / "yt-dlp" / name)
    _copy(REPO / "LICENSE", app_dir / "LICENSE.txt")
    _copy(THIRD_PARTY / "NOTICES.md", app_dir / "NOTICES.txt")
    lic = app_dir / "licenses"
    base_licence = Path(sys.base_prefix) / "LICENSE.txt"
    if not base_licence.is_file():
        raise BuildError(f"No se encuentra la licencia de Python en {base_licence}.")
    _copy(base_licence, lic / f"python-{sys.version.split()[0]}" / "LICENSE.txt")
    # CPython's _ssl/_hashlib link OpenSSL 3 (libssl-3.dll, libcrypto-3.dll): Apache-2.0.
    _copy(THIRD_PARTY / "licenses" / "Apache-2.0.txt", lic / f"openssl-{openssl_version()}" / "LICENSE.txt")
    version, files = package_licence_files("pyinstaller")
    for src, rel in files:
        _copy(src, lic / f"pyinstaller-{version}" / rel)
    for name, pinned in runtime_pins():
        version, files = package_licence_files(name)
        if version != pinned:
            raise BuildError(f"{name} instalado {version}, pero el lock fija {pinned}: reinstala el venv.")
        for src, rel in files:
            _copy(src, lic / f"{name}-{version}" / rel)


# ---- 4. check -----------------------------------------------------------------------------------------------------
def exe_resources(exe: Path) -> tuple[dict[str, str], bool]:
    """(version strings, has an icon group) read back from the built exe."""
    import pefile  # PyInstaller's own dependency on Windows
    pe = pefile.PE(str(exe), fast_load=True)
    try:
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        strings: dict[str, str] = {}
        for fileinfo in getattr(pe, "FileInfo", None) or []:
            for entry in fileinfo:
                for table in getattr(entry, "StringTable", None) or []:
                    for k, v in table.entries.items():
                        strings[k.decode("utf-8", "replace")] = v.decode("utf-8", "replace")
        root = getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None)
        has_icon = bool(root) and any(e.id == pefile.RESOURCE_TYPE["RT_GROUP_ICON"] for e in root.entries)
    finally:
        pe.close()
    return strings, has_icon


def check_bundle(app_dir: Path, *, identity_scan: bool = True) -> list[str]:
    """Problems found in the built folder (empty list = ready to ship)."""
    problems: list[str] = []
    files = [p for p in app_dir.rglob("*") if p.is_file()]
    rels = [p.relative_to(app_dir) for p in files]
    for rel in rels:
        if FORBIDDEN_PARTS.intersection(rel.parts):
            problems.append(f"no debería estar en el paquete: {rel}")
        elif FORBIDDEN_NAMES.match(rel.name):
            problems.append(f"archivo de usuario o de registro en el paquete: {rel}")
    assets = app_dir / "_internal" / APP.lower() / "assets"
    required = [app_dir / f"{APP}.exe", app_dir / "LICENSE.txt", app_dir / "NOTICES.txt",
                assets / "tokens.json", assets / "icon" / "tracklister.ico",
                app_dir / "tools" / fetch_ytdlp.EXE_NAME, app_dir / "tools" / "yt-dlp" / "THIRD_PARTY_LICENSES.txt"]
    required += [assets / "fonts" / n for n in ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf",
                                                 "Inter-Bold.ttf", "JetBrainsMono-Regular.ttf",
                                                 "JetBrainsMono-Medium.ttf", "OFL-Inter.txt", "OFL-JetBrainsMono.txt")]
    for engine_id, pin in ENGINE_PINS.items():
        z = app_dir / "engines" / asset_name(pin)
        required += [z, app_dir / "engines" / engine_id / "LICENSE", app_dir / "engines" / engine_id / "SOURCE.md"]
        if z.is_file() and sha256_file(z) != pin.asset_sha256:
            problems.append(f"SHA-256 del motor no coincide: {z.name}")
    for p in required:
        if not p.is_file():
            problems.append(f"falta en el paquete: {p.relative_to(app_dir)}")
    y = app_dir / "tools" / fetch_ytdlp.EXE_NAME
    if y.is_file() and sha256_file(y) != fetch_ytdlp.EXE_SHA256:
        problems.append("SHA-256 de yt-dlp.exe no coincide")
    lic_dirs = {p.name for p in (app_dir / "licenses").iterdir()} if (app_dir / "licenses").is_dir() else set()
    for name, version in runtime_pins():
        if f"{name}-{version}" not in lic_dirs:
            problems.append(f"falta la licencia de {name} {version} en licenses/")
    exe = app_dir / f"{APP}.exe"
    if exe.is_file():
        strings, has_icon = exe_resources(exe)
        if strings.get("ProductName") != APP or strings.get("ProductVersion") != __version__:
            problems.append(f"recurso de versión inesperado: {strings.get('ProductName')} "
                            f"{strings.get('ProductVersion')}")
        if "blessel" in " ".join(strings.values()).lower():
            problems.append("el nombre del producto no puede llevar 'Blessel'")
        if not has_icon:
            problems.append("Tracklister.exe no lleva icono")
    if identity_scan:
        problems += identity_problems(files, app_dir)
    return problems


def identity_problems(files: list[Path], root: Path) -> list[str]:
    """This PC's Windows account and computer name must not travel inside the zip."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("tracklister_secrets_scan", REPO / "tools" / "secrets_scan.py")
    ss = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = ss
    spec.loader.exec_module(ss)
    res = ss.scan(files, ss.local_identity_patterns(), root=root)
    return [f"{res.labels[k]}: {n} vez/veces en {sorted(res.files[k])[:5]}" for k, n in res.counts.items() if n]


# ---- 5. release assets --------------------------------------------------------------------------------------------
def write_zip(app_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = zip_path.with_name(zip_path.name + ".part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(app_dir.rglob("*")):
            if p.is_file():
                z.write(p, (Path(APP) / p.relative_to(app_dir)).as_posix())
    tmp.replace(zip_path)


def write_sums(files: list[Path], sums_path: Path) -> None:
    lines = [f"{sha256_file(p)}  {p.name}" for p in sorted(files, key=lambda x: x.name)]
    sums_path.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")


def write_release_notes(sums_path: Path, notes_path: Path) -> None:
    template = (HERE / "release-notes.md").read_text(encoding="utf-8")
    text = (template.replace("{version}", __version__).replace("{zip_name}", ZIP_NAME)
            .replace("{sums}", sums_path.read_text(encoding="ascii").strip()))
    notes_path.write_text(text, encoding="utf-8", newline="\n")


def make_release(app_dir: Path, out: Path) -> list[Path]:
    """dist/release/: the app zip, the engines' source archives and SHA256SUMS.txt (the Release
    files), plus dist/release-notes.md for the Release text."""
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    assets = [out / ZIP_NAME]
    write_zip(app_dir, assets[0])
    for engine_id in SOURCE_ARCHIVES:
        dst = out / f"{engine_id}-source.zip"
        shutil.copy2(source_archive(engine_id), dst)
        assets.append(dst)
    write_sums(assets, out / SUMS_NAME)
    write_release_notes(out / SUMS_NAME, out.parent / "release-notes.md")
    return assets + [out / SUMS_NAME]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fetch", action="store_true", help="download missing engines / yt-dlp (public GitHub)")
    ap.add_argument("--zip", action="store_true", help="also write dist/release/ (zip, sources, SHA256SUMS.txt)")
    ap.add_argument("--skip-pyinstaller", action="store_true", help="reuse dist/Tracklister from a previous run")
    ap.add_argument("--no-identity-scan", action="store_true",
                    help="skip the Windows account / PC name scan (CI runners have no personal identity)")
    a = ap.parse_args(argv)
    try:
        check_inputs(fetch=a.fetch, need_sources=a.zip)
        app_dir = DIST / APP if a.skip_pyinstaller else run_pyinstaller(DIST)
        assemble(app_dir)
        problems = check_bundle(app_dir, identity_scan=not a.no_identity_scan)
        if problems:
            raise BuildError("El paquete no está listo:\n  " + "\n  ".join(problems))
        files = [p for p in app_dir.rglob("*") if p.is_file()]
        print(f"OK {app_dir} ({len(files)} archivos, {sum(p.stat().st_size for p in files) / 1e6:.1f} MB)")
        if a.zip:
            for p in make_release(app_dir, DIST / "release"):
                print(f"OK {p.relative_to(REPO)} ({p.stat().st_size / 1e6:.1f} MB)")
    except BuildError as e:
        print(f"ERROR: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
