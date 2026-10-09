"""Packaging contract: the PyInstaller spec, the release workflow, the licences and .gitignore.

SPDX-License-Identifier: GPL-3.0-or-later

Static checks only (no PyInstaller run, no network). The real build is checked by
packaging/build.py (bundle contents) and packaging/smoke_test.py (the exe starts without Python).
"""
from __future__ import annotations

import ast
import hashlib
import re
import subprocess
from pathlib import Path

from tests.release.helpers import REPO, load
from tracklister import config
from tracklister.engine.spec import ENGINE_PINS, SOURCE_ARCHIVES, asset_name
from tracklister.net.update_check import owner_configured

SPEC = REPO / "packaging" / "tracklister.spec"
WORKFLOW = REPO / ".github" / "workflows" / "release.yml"
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


# ---- GitHub Actions release workflow ----------------------------------------------------------------------------
def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_runs_on_a_version_tag_on_windows():
    wf = _workflow()
    assert re.search(r'^on:\n  push:\n    tags:\n      - "v\*"\n', wf, re.MULTILINE)
    assert "pull_request" not in wf and "schedule:" not in wf and "workflow_dispatch" not in wf
    assert re.search(r"^    runs-on: windows-\d{4}$", wf, re.MULTILINE)


def test_workflow_actions_are_pinned_by_commit():
    uses = re.findall(r"uses:\s*([^\s#]+)", _workflow())
    assert uses and all(re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u) for u in uses), uses


def test_workflow_tests_builds_smoke_tests_then_publishes_with_checksums():
    wf = _workflow()
    order = ["packaging\\ci_prepare.py", "requirements-dev.lock.txt", "tools\\fetch_engine.py",
             "packaging\\fetch_ytdlp.py", "-m pytest", "packaging\\build.py --zip", "packaging\\smoke_test.py",
             "gh release create"]
    positions = [wf.find(s) for s in order]
    assert -1 not in positions and positions == sorted(positions), dict(zip(order, positions))
    assert "Get-ChildItem dist\\release -File" in wf              # every release file, SHA256SUMS.txt included
    build = load("build")
    assert build.SUMS_NAME == "SHA256SUMS.txt" and build.ZIP_NAME == f"Tracklister-{config.APP_VERSION}-win64.zip"


def test_workflow_permissions_and_token():
    wf = _workflow()
    assert re.search(r"^permissions:\n  contents: read$", wf, re.MULTILINE)
    assert re.search(r"^    permissions:\n      contents: write ", wf, re.MULTILINE)
    assert "secrets." not in wf and "${{ github.token }}" in wf
    assert "persist-credentials: false" in wf


def test_workflow_owner_is_the_placeholder_constant(monkeypatch):
    wf = _workflow()
    ci = load("ci_prepare")
    m = re.search(r"^  OWNER_PLACEHOLDER: (\S+)", wf, re.MULTILINE)
    assert m and m.group(1) == ci.PLACEHOLDER == "OWNER_PLACEHOLDER"
    assert '--placeholder "$env:OWNER_PLACEHOLDER"' in wf and '--owner "$env:GITHUB_REPOSITORY_OWNER"' in wf
    assert not re.search(r"github\.com/(?!OWNER_PLACEHOLDER)[\w-]+/tracklister", wf)   # no real owner written in
    monkeypatch.setattr(config, "GITHUB_OWNER", ci.PLACEHOLDER)
    assert not owner_configured()                                   # the app also treats it as "not published"


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


def _lock(path: Path) -> list[tuple[str, str]]:
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            name, _, version = line.partition("==")
            out.append((name, version))
    return out


def test_notices_list_every_bundled_python_package():
    rows = [ln for ln in NOTICES.read_text(encoding="utf-8").splitlines() if ln.startswith("|")]
    pins = _lock(REPO / "requirements.lock.txt")
    assert len(pins) >= 20
    dev = dict(_lock(REPO / "requirements-dev.lock.txt"))
    for name, version in pins + [("PyInstaller", dev["pyinstaller"])]:
        assert any(_norm(name) in _norm(r) and f"| {version} |" in r for r in rows), f"{name} {version}"


def test_notices_cover_fonts_engines_and_ytdlp():
    notices = NOTICES.read_text(encoding="utf-8")
    assert re.search(r"\| Inter \| 4\.1 \| OFL-1\.1 \|", notices)
    assert re.search(r"\| JetBrains Mono \| 2\.304 \| OFL-1\.1 \|", notices)
    fonts = REPO / "src" / "tracklister" / "assets" / "fonts"
    assert (fonts / "OFL-Inter.txt").is_file() and (fonts / "OFL-JetBrainsMono.txt").is_file()
    for engine_id, pin in ENGINE_PINS.items():
        for needle in (pin.version, pin.asset_sha256, asset_name(pin), pin.source_url, SOURCE_ARCHIVES[engine_id][0],
                       f"{engine_id}-source.zip"):
            assert needle in notices, (engine_id, needle)
        for name in ("LICENSE", "SOURCE.md"):
            assert (REPO / "third_party" / "engines" / engine_id / name).is_file()
    assert "| AGPL-3.0 |" in notices and "| GPL-3.0 |" in notices
    y = load("fetch_ytdlp")
    assert y.VERSION in notices and y.EXE_SHA256 in notices and "THIRD_PARTY_LICENSES.txt" in notices
    source = (y.THIRD_PARTY / "SOURCE.md").read_text(encoding="utf-8")
    assert y.VERSION in source and y.EXE_SHA256 in source
    assert (y.THIRD_PARTY / "LICENSE").read_text(encoding="utf-8").startswith(
        "This is free and unencumbered software released into the public domain.")
    assert "THIRD-PARTY LICENSES" in (y.THIRD_PARTY / "THIRD_PARTY_LICENSES.txt").read_text(encoding="utf-8")


# ---- .gitignore: scratch, builds and binaries never reach the repo or the zip ------------------------------------------
IGNORED = [".tmp/x.txt", ".tmp/capturas-1/shot.png", "dist/Tracklister/Tracklister.exe", "dist/release/x.zip",
           "build/pyinstaller/x.toc", "entrega/Tracklister-1.0.0-win64.zip", ".venv/Scripts/python.exe",
           "third_party/engines/bin/sockseek_3.0.5_win-x64.zip", "third_party/yt-dlp/bin/yt-dlp.exe",
           "third_party/yt-dlp/bin/yt-dlp.exe.part", "settings.json", "sldl.conf", "credentials.json"]
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
