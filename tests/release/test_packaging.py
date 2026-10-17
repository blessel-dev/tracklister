"""Packaging contract: the PyInstaller spec, the licences and .gitignore (the release workflow: test_workflows.py).

SPDX-License-Identifier: GPL-3.0-or-later

Static checks only (no PyInstaller run, no network). The real build is checked by
packaging/build.py (bundle contents), packaging/smoke_test.py (the exe starts without Python) and
packaging/smoke_test_macos.py (the .app, on the macOS runner).
"""
from __future__ import annotations

import ast
import hashlib
import re
import subprocess
from pathlib import Path

from tests.release.helpers import REPO, load
from tracklister.core.bundled import ytdlp_pin
from tracklister.engine.spec import SOURCE_ARCHIVES, asset_name, engine_pins

SPEC = REPO / "packaging" / "tracklister.spec"
NOTICES = REPO / "third_party" / "NOTICES.md"
ICON = REPO / "src" / "tracklister" / "assets" / "icon" / "tracklister.ico"

# SHA-256 of the canonical texts (LF line ends): gnu.org gpl-3.0.txt / lgpl-3.0.txt, apache.org LICENSE-2.0.txt
GPL3_SHA256 = "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"
LGPL3_SHA256 = "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118"
APACHE2_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"


def _sha256_lf(path: Path) -> str:
    """Hash with LF line ends, so a CRLF checkout (core.autocrlf on Windows runners) still matches."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _spec_tree() -> ast.Module:
    return ast.parse(SPEC.read_text(encoding="utf-8"))


def _spec_call(name: str) -> dict[str, ast.expr]:
    for node in ast.walk(_spec_tree()):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name:
            return {kw.arg: kw.value for kw in node.keywords}
    raise AssertionError(f"{name}(...) not found in the spec")


def _spec_constant(name: str):
    for node in _spec_tree().body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in the spec")


# ---- PyInstaller spec -----------------------------------------------------------------------------------------
def test_spec_builds_a_windowed_onedir_without_upx():
    exe, coll = _spec_call("EXE"), _spec_call("COLLECT")
    assert ast.literal_eval(exe["exclude_binaries"]) is True          # binaries go to COLLECT: onedir
    assert ast.literal_eval(exe["upx"]) is False and ast.literal_eval(coll["upx"]) is False
    assert ast.literal_eval(exe["console"]) is False                    # a window, no console
    assert ast.literal_eval(exe["debug"]) is False
    assert _spec_constant("APP_NAME") == "Tracklister"
    assert isinstance(exe["name"], ast.Name) and exe["name"].id == "APP_NAME"
    assert "blessel" not in _spec_constant("APP_NAME").lower()


def test_spec_uses_the_brand_icon():
    exe = _spec_call("EXE")
    assert "ICON" in ast.unparse(exe["icon"])
    assert 'ICON = ASSETS / "icon" / "tracklister.ico"' in SPEC.read_text(encoding="utf-8")
    data = ICON.read_bytes()
    reserved, kind, count = int.from_bytes(data[0:2], "little"), int.from_bytes(data[2:4], "little"), \
        int.from_bytes(data[4:6], "little")
    assert (reserved, kind) == (0, 1) and count == 9                    # ICONDIR with the 9 brand sizes


def test_spec_excludes_dev_only_modules_and_src_never_imports_them():
    excludes = set(_spec_constant("EXCLUDES"))
    assert {"scipy", "sklearn", "PIL", "pytest", "tests", "tools"} <= excludes
    for py in (REPO / "src" / "tracklister").rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            for n in names:
                # If this fails, the frozen app needs that module: drop it from EXCLUDES (for scipy also
                # pass --collect-submodules scipy._external --collect-submodules scipy).
                assert n.split(".")[0] not in excludes, f"{py.relative_to(REPO)} imports {n}"


def test_packaging_folder_never_shadows_the_packaging_library():
    import packaging.version
    assert not (REPO / "packaging" / "__init__.py").exists()
    assert "site-packages" in Path(packaging.version.__file__).parts


# ---- PyInstaller spec, macOS (1.1) -------------------------------------------------------------------------------
INFO_PLIST = {
    "CFBundleName": "Tracklister",
    "CFBundleDisplayName": "Tracklister",
    "LSMinimumSystemVersion": "14.0",
    "LSApplicationCategoryType": "public.app-category.music",
    "CFBundleDevelopmentRegion": "es",
    "NSHighResolutionCapable": True,
    "NSHumanReadableCopyright": "Copyright (C) 2026 Tracklister contributors. GPL-3.0-or-later",
    "NSDownloadsFolderUsageDescription":
        "Tracklister vigila tu carpeta Descargas para avisarte cuando llega un CSV de trackid.net.",
    "NSRemovableVolumesUsageDescription":
        "Tracklister lee y guarda tus sets en la memoria USB o el disco externo que elijas.",
    "NSNetworkVolumesUsageDescription": "Tracklister lee y guarda tus sets en la carpeta de red (NAS) que elijas.",
    "NSLocalNetworkUsageDescription":
        "Tracklister descarga música de otros usuarios de Soulseek, y alguno puede estar en tu misma red.",
}


def _guarded(tree: ast.Module, condition: str) -> list[ast.stmt]:
    """The statements inside the top-level `if <condition>:` blocks of the spec."""
    return [s for n in tree.body if isinstance(n, ast.If) and ast.unparse(n.test) == condition for s in n.body]


def test_spec_imports_the_windows_version_resource_only_on_windows():
    tree = _spec_tree()
    text = SPEC.read_text(encoding="utf-8")
    assert 'IS_WINDOWS = sys.platform == "win32"' in text and 'IS_MAC = sys.platform == "darwin"' in text
    top_imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not any("win32" in ast.unparse(n) for n in top_imports)            # pefile does not exist on macOS
    windows_only = _guarded(tree, "IS_WINDOWS")
    imports = [n for n in windows_only if isinstance(n, ast.ImportFrom)]
    assert [n.module for n in imports] == ["PyInstaller.utils.win32.versioninfo"]
    assert [n.name for n in windows_only if isinstance(n, ast.FunctionDef)] == ["version_resource"]
    assert not [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "version_resource"]


def test_spec_exe_differs_only_by_platform_switches():
    exe = _spec_call("EXE")
    assert ast.unparse(exe["target_arch"]) == "'arm64' if IS_MAC else None"
    assert ast.unparse(exe["icon"]) == "[str(ICNS if IS_MAC else ICON)]"
    assert ast.unparse(exe["version"]) == "version_resource(VERSION) if IS_WINDOWS else None"
    for key in ("codesign_identity", "entitlements_file"):                    # ad hoc, no hardened runtime
        assert ast.literal_eval(exe[key]) is None
    assert ast.literal_eval(exe["argv_emulation"]) is False
    text = SPEC.read_text(encoding="utf-8")
    assert "--options" not in text and "entitlements_file=None" in text and "codesign_identity=None" in text


def test_spec_bundles_the_mac_app_with_its_info_plist():
    tree = _spec_tree()
    mac_only = _guarded(tree, "IS_MAC")
    calls = [n.value for n in mac_only if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)]
    assert [ast.unparse(c.func) for c in calls] == ["BUNDLE"]
    bundle = {kw.arg: ast.unparse(kw.value) for kw in calls[0].keywords}
    assert [ast.unparse(a) for a in calls[0].args] == ["coll"]
    assert bundle == {"name": "f'{APP_NAME}.app'", "icon": "str(ICNS)", "bundle_identifier": "BUNDLE_ID",
                      "version": "MAC_VERSION",
                      "info_plist": "{**INFO_PLIST, 'CFBundleShortVersionString': MAC_VERSION, "
                                    "'CFBundleVersion': MAC_VERSION}"}
    assert _spec_constant("BUNDLE_ID") == "io.github.blessel-dev.tracklister"
    assert _spec_constant("INFO_PLIST") == INFO_PLIST
    assert 'ICNS = ASSETS / "icon" / "tracklister.icns"' in SPEC.read_text(encoding="utf-8")
    assert "yaml" in _spec_constant("EXCLUDES")


def test_spec_ships_the_icns_only_in_the_mac_app():
    node = next(n for n in _spec_tree().body if isinstance(n, ast.FunctionDef) and n.name == "asset_datas")
    src = REPO / "src"
    for is_mac in (False, True):
        ns = {"ASSETS": src / "tracklister" / "assets", "SRC": src, "IS_MAC": is_mac}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "tracklister.spec", "exec"), ns)  # noqa: S102
        names = {Path(p).name for p, _ in ns["asset_datas"]()}
        assert ("tracklister.icns" in names) is is_mac
        assert {"tracklister.ico", "tokens.json", "manifest.json", "Inter-Bold.ttf"} <= names


# The release workflow (three jobs since 1.1) is checked in tests/release/test_workflows.py.


# ---- licences -----------------------------------------------------------------------------------------------------
def test_licence_is_gpl3_and_the_project_is_or_later():
    assert _sha256_lf(REPO / "LICENSE") == GPL3_SHA256
    assert 'license = "GPL-3.0-or-later"' in (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert "GPL-3.0-or-later" in (REPO / "README.md").read_text(encoding="utf-8")
    notices = NOTICES.read_text(encoding="utf-8")
    assert "either version 3 of the\nLicense, or (at your option) any later version" in notices


def test_canonical_licence_texts_are_unchanged():
    assert _sha256_lf(REPO / "third_party" / "licenses" / "LGPL-3.0.txt") == LGPL3_SHA256
    assert _sha256_lf(REPO / "third_party" / "licenses" / "Apache-2.0.txt") == APACHE2_SHA256


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _lock(path: Path, platform: str | None = None) -> list[tuple[str, str]]:
    """(name, version) of the pins of a lock file; with `platform`, only those whose marker applies."""
    from packaging.requirements import Requirement
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            req = Requirement(line)
            if platform and req.marker is not None and not req.marker.evaluate({"sys_platform": platform}):
                continue
            (spec,) = req.specifier
            out.append((req.name, spec.version))
    return out


def test_notices_list_every_bundled_python_package():
    """Both zips: every runtime pin of Windows or macOS (pywin32-ctypes is Windows only)."""
    rows = [ln for ln in NOTICES.read_text(encoding="utf-8").splitlines() if ln.startswith("|")]
    runtime = REPO / "requirements.lock.txt"
    pins = sorted(set(_lock(runtime, "win32")) | set(_lock(runtime, "darwin")))
    assert len(pins) >= 20 and ("pywin32-ctypes", "0.2.3") in set(_lock(runtime, "win32")) - set(_lock(runtime, "darwin"))
    dev = dict(_lock(REPO / "requirements-dev.lock.txt"))
    for name, version in pins + [("PyInstaller", dev["pyinstaller"])]:
        assert any(_norm(name) in _norm(r) and f"| {version} |" in r for r in rows), f"{name} {version}"


def test_notices_cover_fonts_engines_and_ytdlp():
    notices = NOTICES.read_text(encoding="utf-8")
    assert re.search(r"\| Inter \| 4\.1 \| OFL-1\.1 \|", notices)
    assert re.search(r"\| JetBrains Mono \| 2\.304 \| OFL-1\.1 \|", notices)
    fonts = REPO / "src" / "tracklister" / "assets" / "fonts"
    assert (fonts / "OFL-Inter.txt").is_file() and (fonts / "OFL-JetBrainsMono.txt").is_file()
    for platform in ("win32", "darwin"):                        # both zips: the Windows and the Mac binaries
        for engine_id, pin in engine_pins(platform).items():
            for needle in (pin.version, pin.asset_sha256, asset_name(pin), pin.source_url,
                           SOURCE_ARCHIVES[engine_id][0], f"{engine_id}-source.zip"):
                assert needle in notices, (platform, engine_id, needle)
            for name in ("LICENSE", "SOURCE.md"):
                assert (REPO / "third_party" / "engines" / engine_id / name).is_file()
        yp = ytdlp_pin(platform)
        assert yp.version in notices and yp.sha256 in notices and f"`{yp.asset_name}`" in notices, platform
    assert f"{engine_pins('darwin')['sockseek-3.0.5'].asset_size:,} bytes" in notices
    assert f"{ytdlp_pin('darwin').size:,} bytes" in notices
    assert "sldl is not shipped on macOS" in notices and "libssl.3.dylib" in notices and "libssl-3.dll" in notices
    assert "| AGPL-3.0 |" in notices and "| GPL-3.0 |" in notices
    y = load("fetch_ytdlp")
    assert y.VERSION in notices and y.EXE_SHA256 in notices and "THIRD_PARTY_LICENSES.txt" in notices
    source = (y.THIRD_PARTY / "SOURCE.md").read_text(encoding="utf-8")
    assert y.VERSION in source and ytdlp_pin("win32").sha256 in source and ytdlp_pin("darwin").sha256 in source
    engine_source = (REPO / "third_party" / "engines" / "sockseek-3.0.5" / "SOURCE.md").read_text(encoding="utf-8")
    assert all(engine_pins(p)["sockseek-3.0.5"].asset_sha256 in engine_source for p in ("win32", "darwin"))
    assert (y.THIRD_PARTY / "LICENSE").read_text(encoding="utf-8").startswith(
        "This is free and unencumbered software released into the public domain.")
    assert "THIRD-PARTY LICENSES" in (y.THIRD_PARTY / "THIRD_PARTY_LICENSES.txt").read_text(encoding="utf-8")


# ---- .gitignore: scratch, builds and binaries never reach the repo or the zip ------------------------------------------
IGNORED = [".tmp/x.txt", ".tmp/capturas-1/shot.png", "dist/Tracklister/Tracklister.exe", "dist/release/x.zip",
           "build/pyinstaller/x.toc", "entrega/Tracklister-1.0.0-win64.zip", ".venv/Scripts/python.exe",
           "third_party/engines/bin/sockseek_3.0.5_win-x64.zip", "third_party/yt-dlp/bin/yt-dlp.exe",
           "third_party/yt-dlp/bin/yt-dlp.exe.part", "settings.json", "sldl.conf", "credentials.json",
           ".agents/x.md", ".agents/tasks/plan-mac.md", "dist/Tracklister.app/Contents/Info.plist",
           "third_party/engines/bin/sockseek_3.0.5_osx-arm64.tar.gz", "third_party/yt-dlp/bin/yt-dlp_macos"]
KEPT = ["packaging/build.py", "packaging/tracklister.spec", "packaging/release-notes.md",
        ".github/workflows/release.yml", "third_party/NOTICES.md", "third_party/yt-dlp/THIRD_PARTY_LICENSES.txt",
        "third_party/yt-dlp/SOURCE.md", "third_party/licenses/LGPL-3.0.txt", "src/tracklister/engine/credentials.py"]


def _ignored(paths: list[str]) -> list[str]:
    """The paths git ignores (NUL-separated I/O: no CRLF or quoting surprises on Windows)."""
    r = subprocess.run(["git", "-C", str(REPO), "check-ignore", "--no-index", "-z", "--stdin"],
                       input="\0".join(paths).encode("utf-8") + b"\0", capture_output=True)
    assert r.returncode in (0, 1), r.stderr
    return [p for p in r.stdout.decode("utf-8").split("\0") if p]


def test_gitignore_keeps_scratch_builds_and_binaries_out():
    assert sorted(_ignored(IGNORED)) == sorted(IGNORED)


def test_gitignore_keeps_the_packaging_sources_in():
    assert _ignored(KEPT) == []


def test_nothing_under_tmp_is_tracked_or_publishable():
    r = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "--", ".tmp"], capture_output=True)
    assert r.returncode == 0 and r.stdout == b""
    ss = load_secrets_scan()
    assert not [p for p in ss.publishable_files(REPO) if ".tmp" in p.relative_to(REPO).parts]


def load_secrets_scan():
    import importlib.util
    import sys
    name = "tracklister_secrets_scan_release"
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / "secrets_scan.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
