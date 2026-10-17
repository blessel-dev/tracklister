"""Build Tracklister: verify the pins, run PyInstaller, add engines/yt-dlp/licences, check, zip.

SPDX-License-Identifier: GPL-3.0-or-later

    .venv\\Scripts\\python.exe packaging\\build.py                     # dist\\Tracklister\\ (onedir) + checks
    .venv\\Scripts\\python.exe packaging\\build.py --fetch             # first download missing engines/yt-dlp
    .venv\\Scripts\\python.exe packaging\\build.py --zip               # + dist\\release\\ (zip, sources, SHA256SUMS.txt)
    .venv\\Scripts\\python.exe packaging\\build.py --skip-pyinstaller  # re-assemble and re-check dist\\Tracklister

Windows, dist\\Tracklister\\ (what the user unzips):
    Tracklister.exe, _internal\\            PyInstaller onedir (assets in _internal\\tracklister\\assets)
    engines\\<pinned zip>, engines\\<id>\\    engine zips (SHA-256 pinned, unpacked by the app on first use),
                                           with their LICENSE and SOURCE.md
    tools\\yt-dlp.exe, tools\\yt-dlp\\        yt-dlp (copied by the app to %LOCALAPPDATA%), its licences
    licenses\\                              licence texts of Python, PyInstaller, Qt and every Python package
    LICENSE.txt, NOTICES.txt                GPL-3.0 text and the third-party notices (third_party/NOTICES.md)

macOS (Apple Silicon only), dist/Tracklister.app/ (the same files, in the places a signed bundle needs):
    Contents/MacOS/Tracklister             the executable (arm64); Python, Qt and the rest in Contents/Frameworks
    Contents/Resources/engines/, tools/, licenses/, LICENSE.txt, NOTICES.txt
                                           as on Windows, with the macOS pins: the Sockseek osx-arm64 .tar.gz
                                           (no sldl) and yt-dlp_macos. They are data: the app copies them to
                                           ~/Library/Application Support/Tracklister/tools and runs the copies.
  Then the whole .app is signed again ad hoc (PyInstaller's signature does not cover the files added
  here), verified with codesign --verify --deep --strict, checked, and zipped with ditto, which keeps
  the symlinks of the Qt frameworks, the permissions and the signature (zipfile would break them).

Never runs the engines or yt-dlp, and never touches the network unless --fetch is given.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import os
import plistlib
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
from tracklister.core import osplatform  # noqa: E402
from tracklister.core.bundled import ytdlp_pin  # noqa: E402
from tracklister.engine.spec import SOURCE_ARCHIVES, asset_name, dev_bin_dir, engine_pins  # noqa: E402

APP = "Tracklister"
SPEC = HERE / "tracklister.spec"
DIST = REPO / "dist"
WORK = REPO / "build" / "pyinstaller"
THIRD_PARTY = REPO / "third_party"
RUNTIME_LOCK = REPO / "requirements.lock.txt"
SUMS_NAME = "SHA256SUMS.txt"
WINDOWS, MACOS = osplatform.WINDOWS, osplatform.MACOS

# Never part of the bundle: dev/test/brand-build modules, the source tree, scratch and user data.
FORBIDDEN_PARTS = {"scipy", "sklearn", "PIL", "pytest", "_pytest", "pytestqt", "tests", ".tmp", ".git", ".venv",
                   "setuptools", "pkg_resources"}
FORBIDDEN_NAMES = re.compile(r"(?i)^(settings\.json|library\.json|update\.json|credentials.*|.*\.conf|.*\.log|"
                             r"sldl\.conf|\.env)$")
LICENCE_FILE = re.compile(r"(?i)(licen[cs]e|copying|notice|authors)")
# The OpenSSL 3 libraries that CPython's _ssl/_hashlib link, as each platform names them (Apache-2.0).
OPENSSL_LIBS = {WINDOWS: ("libssl-3.dll", "libcrypto-3.dll"), MACOS: ("libssl.3.dylib", "libcrypto.3.dylib")}
FONTS = ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf", "JetBrainsMono-Regular.ttf",
         "JetBrainsMono-Medium.ttf", "OFL-Inter.txt", "OFL-JetBrainsMono.txt")
# macOS tools, by absolute path (a PATH of the build machine can never swap them)
XATTR, CODESIGN, DITTO = "/usr/bin/xattr", "/usr/bin/codesign", "/usr/bin/ditto"


class BuildError(Exception):
    pass


def target(platform: str | None = None) -> str:
    """The build target: 'darwin' (the .app) for macOS, 'win32' (the onedir folder) for anything else.
    Default: the platform whose policy applies (osplatform.current(), sys.platform outside the tests)."""
    return MACOS if (platform or osplatform.current()) == MACOS else WINDOWS


def zip_name(platform: str | None = None) -> str:
    return f"{APP}-{__version__}-{'macos-arm64' if target(platform) == MACOS else 'win64'}.zip"


ZIP_NAME = zip_name()


def app_dir_name(platform: str | None = None) -> str:
    return f"{APP}.app" if target(platform) == MACOS else APP


def executable(app_dir: Path, platform: str | None = None) -> Path:
    return app_dir / "Contents" / "MacOS" / APP if target(platform) == MACOS else app_dir / f"{APP}.exe"


def data_root(app_dir: Path, platform: str | None = None) -> Path:
    """Where the engines, tools, licences, LICENSE.txt and NOTICES.txt go: what the app's bundled_dir() gives
    (the exe's folder on Windows, Contents/Resources on macOS)."""
    return app_dir / "Contents" / "Resources" if target(platform) == MACOS else app_dir


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def runtime_pins(lock: Path = RUNTIME_LOCK, platform: str | None = None) -> list[tuple[str, str]]:
    """(name, version) of every runtime pin that applies to `platform` (default: this one): exactly
    what PyInstaller may put in the bundle. A pin with an environment marker
    (`pywin32-ctypes==0.2.3 ; sys_platform == "win32"`) only counts where the marker is true."""
    from packaging.requirements import InvalidRequirement, Requirement  # the library, a runtime pin
    env = {"sys_platform": platform or sys.platform}
    pins = []
    for raw in lock.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        try:
            req = Requirement(line)
        except InvalidRequirement as e:
            raise BuildError(f"{lock.name}: línea no válida: {raw!r}") from e
        specs = list(req.specifier)
        if len(specs) != 1 or specs[0].operator != "==" or "*" in specs[0].version:
            raise BuildError(f"{lock.name}: pin sin versión exacta: {raw!r}")
        if req.marker is not None and not req.marker.evaluate(env):
            continue
        pins.append((req.name, specs[0].version))
    return pins


def spec_values() -> dict:
    """BUNDLE_ID, INFO_PLIST and version_numbers() of packaging/tracklister.spec (which only PyInstaller can
    run as a whole), so the checks below never restate them."""
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    out: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in ("BUNDLE_ID", "INFO_PLIST"):
            out[node.targets[0].id] = ast.literal_eval(node.value)
        elif isinstance(node, ast.FunctionDef) and node.name == "version_numbers":
            ns = {"re": re}
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(SPEC), "exec"), ns)  # noqa: S102
            out["version_numbers"] = ns["version_numbers"]
    return out


def mac_version(version: str = __version__) -> str:
    """CFBundleShortVersionString/CFBundleVersion: the three release numbers ('1.1.0.dev1' -> '1.1.0')."""
    return ".".join(str(n) for n in spec_values()["version_numbers"](version)[:3])


# ---- 1. inputs ----------------------------------------------------------------------------------------------------
def check_inputs(*, fetch: bool, need_sources: bool, platform: str | None = None) -> None:
    p = target(platform)
    cmd = [sys.executable, str(REPO / "tools" / "fetch_engine.py"), "--platform", p] + ([] if fetch else ["--verify-only"])
    if subprocess.run(cmd, cwd=str(REPO)).returncode != 0:
        what = "Los zips de los motores faltan" if p == WINDOWS else "Los archivos de los motores faltan"
        raise BuildError(f"{what} o no coinciden con su SHA-256 (tools/fetch_engine.py).")
    if fetch:
        ytdlp_ok = fetch_ytdlp.fetch(p) == 0
    else:
        problems = fetch_ytdlp.verify_local(p)
        for line in problems:
            print(line)
        ytdlp_ok = not problems
    if not ytdlp_ok:
        raise BuildError(f"{ytdlp_pin(p).asset_name} falta o no coincide con su SHA-256 (packaging/fetch_ytdlp.py).")
    required = [REPO / "LICENSE", THIRD_PARTY / "NOTICES.md", THIRD_PARTY / "licenses" / "LGPL-3.0.txt",
                THIRD_PARTY / "licenses" / "Apache-2.0.txt",
                fetch_ytdlp.THIRD_PARTY / "LICENSE", fetch_ytdlp.THIRD_PARTY / "THIRD_PARTY_LICENSES.txt",
                fetch_ytdlp.THIRD_PARTY / "SOURCE.md"]
    for engine_id in engine_pins(p):
        required += [THIRD_PARTY / "engines" / engine_id / "LICENSE", THIRD_PARTY / "engines" / engine_id / "SOURCE.md"]
    if need_sources and p == WINDOWS:          # the Windows job attaches the engines' sources to the Release
        required += [source_archive(engine_id) for engine_id in SOURCE_ARCHIVES]
    missing = [str(f.relative_to(REPO) if f.is_relative_to(REPO) else f) for f in required if not f.is_file()]
    if missing:
        raise BuildError("Faltan archivos: " + ", ".join(missing))


def source_archive(engine_id: str) -> Path:
    return dev_bin_dir() / "src" / f"{engine_id}-src.zip"


# ---- 2. PyInstaller -----------------------------------------------------------------------------------------------
def run_pyinstaller(dist: Path, platform: str | None = None) -> Path:
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
    return dist / app_dir_name(platform)


# ---- 3. assemble --------------------------------------------------------------------------------------------------
def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def openssl_version() -> str:
    """'3.0.15' from ssl.OPENSSL_VERSION ('OpenSSL 3.0.15 3 Sep 2024') of the building Python."""
    import ssl
    m = re.search(r"OpenSSL (\d+\.\d+\.\d+\w*)", ssl.OPENSSL_VERSION)
    return m.group(1) if m else "3"


def python_licence(base: Path | None = None) -> Path:
    """The building Python's LICENSE.txt: <prefix>/lib/python3.X/LICENSE.txt on macOS (a POSIX install),
    <prefix>/LICENSE.txt on Windows."""
    base = Path(sys.base_prefix) if base is None else Path(base)
    candidates = [base / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt",
                  base / "LICENSE.txt"]
    for c in candidates:
        if c.is_file():
            return c
    raise BuildError("No se encuentra la licencia de Python en " + " ni en ".join(str(c) for c in candidates) + ".")


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


def assemble(app_dir: Path, platform: str | None = None) -> None:
    """Add the engines, yt-dlp, the licences, LICENSE.txt and NOTICES.txt to the PyInstaller output:
    next to Tracklister.exe on Windows, in Tracklister.app/Contents/Resources on macOS."""
    p = target(platform)
    exe = executable(app_dir, p)
    if not exe.is_file():
        raise BuildError(f"No existe {exe}: ejecuta el build sin --skip-pyinstaller.")
    root = data_root(app_dir, p)
    for sub in ("engines", "tools", "licenses"):
        shutil.rmtree(root / sub, ignore_errors=True)
    for engine_id, pin in engine_pins(p).items():
        _copy(dev_bin_dir() / asset_name(pin), root / "engines" / asset_name(pin))
        for name in ("LICENSE", "SOURCE.md"):
            _copy(THIRD_PARTY / "engines" / engine_id / name, root / "engines" / engine_id / name)
    ytdlp_name = ytdlp_pin(p).asset_name
    _copy(fetch_ytdlp.exe_path(p), root / "tools" / ytdlp_name)
    for name in ("LICENSE", "THIRD_PARTY_LICENSES.txt", "SOURCE.md"):
        _copy(fetch_ytdlp.THIRD_PARTY / name, root / "tools" / "yt-dlp" / name)
    _copy(REPO / "LICENSE", root / "LICENSE.txt")
    _copy(THIRD_PARTY / "NOTICES.md", root / "NOTICES.txt")
    lic = root / "licenses"
    _copy(python_licence(), lic / f"python-{sys.version.split()[0]}" / "LICENSE.txt")
    # CPython's _ssl/_hashlib link OpenSSL 3 (libssl-3.dll and libcrypto-3.dll on Windows, libssl.3.dylib and
    # libcrypto.3.dylib on macOS): Apache-2.0.
    _copy(THIRD_PARTY / "licenses" / "Apache-2.0.txt", lic / f"openssl-{openssl_version()}" / "LICENSE.txt")
    version, files = package_licence_files("pyinstaller")
    for src, rel in files:
        _copy(src, lic / f"pyinstaller-{version}" / rel)
    for name, pinned in runtime_pins(platform=p):
        version, files = package_licence_files(name)
        if version != pinned:
            raise BuildError(f"{name} instalado {version}, pero el lock fija {pinned}: reinstala el venv.")
        for src, rel in files:
            _copy(src, lic / f"{name}-{version}" / rel)


def _run_tool(cmd: list[str], run=None) -> str:
    """Run a macOS tool; its output, or BuildError with the last lines of it. `run` is subprocess.run
    unless a test passes a fake one."""
    r = (run or subprocess.run)(cmd, capture_output=True, text=True)
    output = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode != 0:
        tail = "\n".join(output.splitlines()[-15:])
        raise BuildError(f"{Path(cmd[0]).name} {cmd[1]} falló (código {r.returncode}):\n{tail}")
    return output


def sign_and_verify(app: Path, run=None) -> list[str]:
    """macOS: sign the whole .app again, ad hoc, and verify it. PyInstaller signed it before assemble() added
    its files, and an altered bundle is «damaged» for macOS. No Developer ID, no hardened runtime and no
    entitlements: ad-hoc dylibs would fail the hardened runtime's library validation."""
    _run_tool([XATTR, "-cr", str(app)], run)                       # Finder info, quarantine...: never signed in
    _run_tool([CODESIGN, "--force", "--deep", "--sign", "-", str(app)], run)
    out = _run_tool([CODESIGN, "--verify", "--deep", "--strict", "--verbose=2", str(app)], run)
    return out.splitlines()


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


def bundle_files(app_dir: Path) -> list[Path]:
    """Every regular file of the build (a symlink of the macOS bundle is not a second copy)."""
    return [p for p in app_dir.rglob("*") if p.is_file() and not p.is_symlink()]


def check_bundle(app_dir: Path, *, identity_scan: bool = True, platform: str | None = None) -> list[str]:
    """Problems found in the built folder or .app (empty list = ready to ship). On macOS it runs after
    sign_and_verify(), so the engine and yt-dlp hashes are those of the signed bundle."""
    p = target(platform)
    problems: list[str] = []
    files = bundle_files(app_dir)
    rels = [f.relative_to(app_dir) for f in files]
    for rel in rels:
        if FORBIDDEN_PARTS.intersection(rel.parts):
            problems.append(f"no debería estar en el paquete: {rel}")
        elif FORBIDDEN_NAMES.match(rel.name):
            problems.append(f"archivo de usuario o de registro en el paquete: {rel}")
    if p == MACOS:
        problems += _check_mac_app(app_dir)
    else:
        problems += _check_windows_folder(app_dir)
    if identity_scan:
        problems += identity_problems(files, app_dir)
    return problems


def _check_shipped_data(root: Path, app_dir: Path, platform: str, required: list[Path]) -> list[str]:
    """The engines, yt-dlp and licences under `root`, checked against the pins of `platform`."""
    problems: list[str] = []
    ypin = ytdlp_pin(platform)
    required += [root / "LICENSE.txt", root / "NOTICES.txt", root / "tools" / ypin.asset_name,
                 root / "tools" / "yt-dlp" / "THIRD_PARTY_LICENSES.txt"]
    for engine_id, pin in engine_pins(platform).items():
        z = root / "engines" / asset_name(pin)
        required += [z, root / "engines" / engine_id / "LICENSE", root / "engines" / engine_id / "SOURCE.md"]
        if z.is_file() and sha256_file(z) != pin.asset_sha256:
            problems.append(f"SHA-256 del motor no coincide: {z.name}")
    for f in required:
        if not f.is_file():
            problems.append(f"falta en el paquete: {f.relative_to(app_dir)}")
    y = root / "tools" / ypin.asset_name
    if y.is_file() and sha256_file(y) != ypin.sha256:
        problems.append(f"SHA-256 de {ypin.asset_name} no coincide")
    lic_dirs = {d.name for d in (root / "licenses").iterdir()} if (root / "licenses").is_dir() else set()
    for name, version in runtime_pins(platform=platform):
        if f"{name}-{version}" not in lic_dirs:
            problems.append(f"falta la licencia de {name} {version} en licenses/")
    return problems


def _check_windows_folder(app_dir: Path) -> list[str]:
    assets = app_dir / "_internal" / APP.lower() / "assets"
    required = [app_dir / f"{APP}.exe", assets / "tokens.json", assets / "icon" / "tracklister.ico"]
    required += [assets / "fonts" / n for n in FONTS]
    problems = _check_shipped_data(app_dir, app_dir, WINDOWS, required)
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
    return problems


def mac_assets_dir(app_dir: Path) -> Path:
    """The app's assets in the .app: PyInstaller keeps data in Contents/Resources and links it from
    Contents/Frameworks (sys._MEIPASS, what assets_dir() reads)."""
    for base in ("Resources", "Frameworks"):
        d = app_dir / "Contents" / base / APP.lower() / "assets"
        if (d / "tokens.json").is_file():
            return d
    return app_dir / "Contents" / "Resources" / APP.lower() / "assets"


def _check_mac_app(app_dir: Path) -> list[str]:
    contents = app_dir / "Contents"
    assets = mac_assets_dir(app_dir)
    required = [contents / "MacOS" / APP, contents / "Info.plist", assets / "tokens.json"]
    required += [assets / "fonts" / n for n in FONTS]
    problems = _check_shipped_data(contents / "Resources", app_dir, MACOS, required)
    plist = contents / "Info.plist"
    if plist.is_file():
        problems += info_plist_problems(plistlib.loads(plist.read_bytes()))
    problems += symlink_problems(app_dir)
    return problems


def info_plist_problems(info: dict, version: str = __version__) -> list[str]:
    """The Info.plist of the .app against the spec: identifier, version, executable, icon and INFO_PLIST."""
    spec = spec_values()
    v = mac_version(version)
    expected = {**spec["INFO_PLIST"], "CFBundleIdentifier": spec["BUNDLE_ID"], "CFBundleExecutable": APP,
                "CFBundlePackageType": "APPL", "CFBundleShortVersionString": v, "CFBundleVersion": v}
    problems = [f"Info.plist: {k} es {info.get(k)!r}, se esperaba {want!r}"
                for k, want in expected.items() if info.get(k) != want]
    if not info.get("CFBundleIconFile"):
        problems.append("Info.plist: falta CFBundleIconFile (el icono de la app)")
    if "blessel" in " ".join(str(info.get(k, "")) for k in ("CFBundleName", "CFBundleDisplayName")).lower():
        problems.append("el nombre del producto no puede llevar 'Blessel'")
    return problems


def symlink_problems(app_dir: Path) -> list[str]:
    """A link of the bundle that is broken or points outside it would make the copied app incomplete."""
    root = app_dir.resolve()
    problems = []
    for link in sorted(app_dir.rglob("*")):
        if not link.is_symlink():
            continue
        dest = (link.parent / os.readlink(link)).resolve()
        if dest != root and root not in dest.parents:
            problems.append(f"enlace fuera del paquete: {link.relative_to(app_dir)}")
        elif not dest.exists():
            problems.append(f"enlace roto: {link.relative_to(app_dir)}")
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
def write_zip(app_dir: Path, zip_path: Path, platform: str | None = None, run=None) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = zip_path.with_name(zip_path.name + ".part")
    tmp.unlink(missing_ok=True)
    if target(platform) == MACOS:
        # ditto keeps the symlinks, the modes and the signature; the zip holds Tracklister.app at its top level
        _run_tool([DITTO, "-c", "-k", "--sequesterRsrc", "--keepParent", str(app_dir), str(tmp)], run)
    else:
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


def make_release(app_dir: Path, out: Path, platform: str | None = None, run=None) -> list[Path]:
    """dist/release/. Windows: the app zip, the engines' source archives and SHA256SUMS.txt (the Release
    files), plus dist/release-notes.md for the Release text. macOS: the app zip and a SHA256SUMS.txt of
    it only (the publish job writes the Release's single SHA256SUMS.txt and notes for both zips)."""
    p = target(platform)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    assets = [out / zip_name(p)]
    write_zip(app_dir, assets[0], p, run)
    if p == MACOS:
        write_sums(assets, out / SUMS_NAME)
        return assets + [out / SUMS_NAME]
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
    p = target()
    try:
        check_inputs(fetch=a.fetch, need_sources=a.zip, platform=p)
        app_dir = DIST / app_dir_name(p) if a.skip_pyinstaller else run_pyinstaller(DIST, p)
        assemble(app_dir, p)
        if p == MACOS:
            for line in sign_and_verify(app_dir):
                print(f"  {line}")
        problems = check_bundle(app_dir, identity_scan=not a.no_identity_scan, platform=p)
        if problems:
            raise BuildError("El paquete no está listo:\n  " + "\n  ".join(problems))
        files = bundle_files(app_dir)
        print(f"OK {app_dir} ({len(files)} archivos, {sum(f.stat().st_size for f in files) / 1e6:.1f} MB)")
        if a.zip:
            for f in make_release(app_dir, DIST / "release", p):
                print(f"OK {f.relative_to(REPO)} ({f.stat().st_size / 1e6:.1f} MB)")
    except BuildError as e:
        print(f"ERROR: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
