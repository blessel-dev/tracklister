# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Tracklister.exe: ONEDIR, windowed, no UPX, icon from the brand assets.
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Normally run by packaging/build.py, which also verifies the pins and puts the engines, yt-dlp,
# the licences and NOTICES next to the exe. Direct use (repo root):
#   .venv\Scripts\python.exe -m PyInstaller packaging\tracklister.spec --noconfirm --clean
#       --distpath dist --workpath build\pyinstaller
#
# The app never imports scipy, sklearn, Pillow or pytest (dev/brand-build only, see
# requirements-dev.lock.txt), so they are excluded. build.py checks the result.
import re
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

SPEC_DIR = Path(SPECPATH).resolve()          # noqa: F821 - provided by PyInstaller
REPO = SPEC_DIR.parent
SRC = REPO / "src"
PKG = SRC / "tracklister"
ASSETS = PKG / "assets"
ICON = ASSETS / "icon" / "tracklister.ico"

APP_NAME = "Tracklister"                      # the product name never contains "Blessel"

# Modules that only the tests, the brand tools or the build use. None is imported by src/.
EXCLUDES = [
    "scipy", "sklearn", "PIL", "pytest", "_pytest", "pytestqt", "pluggy", "iniconfig", "pygments",
    "colorama", "PyInstaller", "setuptools", "pkg_resources",
    "tkinter", "_tkinter", "turtle", "turtledemo", "idlelib", "pydoc_data",
    "tests", "tools",
]


def read_version() -> str:
    text = (PKG / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE).group(1)


def tracklister_modules() -> list[str]:
    """Every module of the package, so lazily imported ones (inputs/enrich/net...) always ship."""
    names = []
    for path in sorted(PKG.rglob("*.py")):
        parts = list(path.relative_to(SRC).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        names.append(".".join(parts))
    return names


def asset_datas() -> list[tuple[str, str]]:
    """src/tracklister/assets/** -> <bundle>/tracklister/assets/** (what assets_dir() expects)."""
    out = []
    for path in sorted(ASSETS.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix in (".py", ".pyc") or path.name == ".gitattributes":
            continue
        out.append((str(path), str(path.relative_to(SRC).parent)))
    return out


def version_numbers(version: str) -> tuple[int, int, int, int]:
    """The four numbers of the Windows file version: '1.0.1' -> (1, 0, 1, 0). A pre-release
    ('1.0.1rc1', '1.1.0-beta.2', '2.0.0.dev3') keeps its release numbers; the full text still goes
    in FileVersion/ProductVersion."""
    m = re.match(r"^\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?", version)
    if not m:
        raise ValueError(f"versión no válida: {version!r}")
    major, minor, patch = (int(x) if x else 0 for x in m.groups())
    return major, minor, patch, 0


def version_resource(version: str) -> VSVersionInfo:
    nums = version_numbers(version)
    strings = [
        StringStruct("CompanyName", APP_NAME),
        StringStruct("FileDescription", APP_NAME),
        StringStruct("FileVersion", version),
        StringStruct("InternalName", APP_NAME),
        StringStruct("LegalCopyright", "Copyright (C) 2026 Tracklister contributors. GPL-3.0-or-later"),
        StringStruct("OriginalFilename", f"{APP_NAME}.exe"),
        StringStruct("ProductName", APP_NAME),
        StringStruct("ProductVersion", version),
    ]
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums, mask=0x3F, flags=0x0, OS=0x40004,
                          fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[StringFileInfo([StringTable("0C0A04B0", strings)]),     # es-ES, Unicode
              VarFileInfo([VarStruct("Translation", [0x0C0A, 1200])])],
    )


VERSION = read_version()

a = Analysis(  # noqa: F821
    [str(SPEC_DIR / "entry.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=asset_datas(),
    hiddenimports=tracklister_modules(),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(ICON)],
    version=version_resource(VERSION),
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
