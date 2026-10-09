# Tracklister: licence and third-party notices

Resumen: Tracklister es software libre (GPL-3.0-or-later). Lleva dentro programas y bibliotecas de
otros autores, cada uno con su licencia. Aquí están todos, con su versión, su licencia y dónde está
su código fuente. Los textos completos de las licencias van en la carpeta de la app (rutas abajo).

## Tracklister

Copyright (C) 2026 Tracklister contributors.

This program is free software: you can redistribute it and/or modify it under the terms of the
GNU General Public License as published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without
even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

- Full licence text: `LICENSE` in the repo, `LICENSE.txt` next to `Tracklister.exe`.
- Source code: https://github.com/OWNER_PLACEHOLDER/tracklister (the owner is the single constant
  `GITHUB_OWNER` in `src/tracklister/config.py`, filled in when the repo is published).
- Brand assets: the Blessel logo (`assets/logo/`, `assets/lockup/`) is the creator's signature and
  the header texture comes from his own cover photo. They credit him; the product name never
  contains "Blessel". In line with GPL-3.0 section 7(e), no rights under trademark law are granted
  for that name or logo.

## Fonts (embedded, unmodified)

| Font | Version | Licence | Copyright | Source |
|---|---|---|---|---|
| Inter | 4.1 | OFL-1.1 | Copyright (c) 2016 The Inter Project Authors | https://github.com/rsms/inter |
| JetBrains Mono | 2.304 | OFL-1.1 | Copyright 2020 The JetBrains Mono Project Authors | https://github.com/JetBrains/JetBrainsMono |

Licence texts: `src/tracklister/assets/fonts/OFL-Inter.txt` and `OFL-JetBrainsMono.txt`; in the
app, `_internal\tracklister\assets\fonts\`.

## Soulseek engines (separate programs, shipped unmodified)

Tracklister never links the engines: it runs them as separate processes through their
command-line interface. Each one is the official release binary, verified by SHA-256.

| Engine | Version | Licence | Binary (SHA-256) |
|---|---|---|---|
| Sockseek, by fiso64 (default) | 3.0.5 | AGPL-3.0 | `sockseek_3.0.5_win-x64.zip` (`1b5c1189dcfc24cc9fea22dc67a58b7a5f0a127d0367355cf2a8718100044802`) |
| sldl (slsk-batchdl), by fiso64 (fallback) | 2.6.0 | GPL-3.0 | `sldl_win-x86_self-contained.zip` (`6e39232c8c22f9b4e5f6a635dae85fdc405e50bcc56392351001d8964cf29a63`) |

- Corresponding source, the exact tags:
  - https://github.com/fiso64/sockseek/tree/v3.0.5 (archive https://github.com/fiso64/sockseek/archive/refs/tags/v3.0.5.zip)
  - https://github.com/fiso64/sockseek/tree/v2.6.0 (archive https://github.com/fiso64/sockseek/archive/refs/tags/v2.6.0.zip)
  - Every Tracklister release on GitHub also attaches both archives as `sockseek-3.0.5-source.zip`
    and `sldl-2.6.0-source.zip`.
- Licence texts: `third_party/engines/<engine>/LICENSE` (with `SOURCE.md`); in the app,
  `engines\<engine>\LICENSE`.
- Libraries compiled into the engine binaries, as listed in the project files of those tags and
  with the licences their NuGet packages declare:
  - Soulseek.NET (GPL-3.0-only in 10.0.2 for Sockseek; GPL-3.0-or-later in 8.5.0 for sldl);
  - TagLibSharp 2.3.0 (LGPL-2.1-only);
  - YoutubeExplode, HtmlAgilityPack, SpotifyAPI.Web and SpotifyAPI.Web.Auth (MIT);
  - Google.Apis.YouTube.v3 (Apache-2.0);
  - Sockseek 3.0.5 only: AngleSharp, Spectre.Console, Microsoft.Extensions.Logging and the ASP.NET
    Core SignalR client (MIT);
  - SmallestCSVParser and, in sldl 2.6.0, Goblinfactory.Konsole: see their projects;
  - the .NET runtime (MIT).
  The `*.csproj` files of each source archive list the exact versions.

## yt-dlp (separate program, shipped unmodified)

| Program | Version | Licence | Binary (SHA-256) |
|---|---|---|---|
| yt-dlp | 2026.08.19 | The Unlicense | `yt-dlp.exe` (`66674953fe251b89f4d08c5f0e35e0728679bd67ab3d7d05c0562af101dd3e7a`) |

- Source: https://github.com/yt-dlp/yt-dlp/tree/2026.08.19
- The official exe is a PyInstaller bundle that also contains Python and other components. Their
  licences are listed in `THIRD_PARTY_LICENSES.txt`, copied unchanged from the tag.
- Licence texts: `third_party/yt-dlp/`; in the app, `tools\yt-dlp\`.
- "Actualizar yt-dlp" in Ajustes replaces the copy in `%LOCALAPPDATA%\Tracklister\tools\` with
  the newest official release (`yt-dlp -U`).

## Inside Tracklister.exe (PyInstaller bundle)

| Component | Version | Licence | Source |
|---|---|---|---|
| CPython | 3.13 | PSF-2.0 | https://www.python.org/ |
| PyInstaller bootloader | 6.22.3 | GPL-2.0-or-later WITH Bootloader-exception | https://github.com/pyinstaller/pyinstaller |
| PySide6 (Essentials), with Qt 6.12 | 6.12.0 | LGPL-3.0-only (Tracklister uses the LGPL option of LGPL-3.0/GPL-2.0/GPL-3.0) | https://code.qt.io/cgit/pyside/pyside-setup.git/, https://download.qt.io/official_releases/qt/ |
| shiboken6 | 6.12.0 | LGPL-3.0-only | https://code.qt.io/cgit/pyside/pyside-setup.git/ |
| numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0; it bundles OpenBLAS (BSD-3-Clause), LAPACK (BSD-3-Clause-Open-MPI) and the GCC runtime (GPL-3.0-or-later WITH GCC-exception-3.1) | https://github.com/numpy/numpy |
| soundfile | 0.14.0 | BSD-3-Clause | https://github.com/bastibe/python-soundfile |
| libsndfile (shipped with soundfile) | 1.2.2 | LGPL-2.1-or-later | https://github.com/libsndfile/libsndfile, build: https://github.com/bastibe/libsndfile-binaries |
| cffi | 2.1.1 | MIT-0 | https://github.com/python-cffi/cffi |
| pycparser | 3.1 | BSD-3-Clause | https://github.com/eliben/pycparser |
| openpyxl | 3.1.5 | MIT | https://foss.heptapod.net/openpyxl/openpyxl |
| et_xmlfile | 2.0.0 | MIT | https://foss.heptapod.net/openpyxl/et_xmlfile |
| RapidFuzz | 3.14.6 | MIT | https://github.com/rapidfuzz/RapidFuzz |
| mutagen | 1.48.1 | GPL-2.0-or-later | https://github.com/quodlibet/mutagen |
| keyring | 25.7.0 | MIT | https://github.com/jaraco/keyring |
| jaraco.classes | 3.4.0 | MIT | https://github.com/jaraco/jaraco.classes |
| jaraco.context | 6.1.2 | MIT | https://github.com/jaraco/jaraco.context |
| jaraco.functools | 4.6.0 | MIT | https://github.com/jaraco/jaraco.functools |
| more-itertools | 11.1.0 | MIT | https://github.com/more-itertools/more-itertools |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause | https://github.com/enthought/pywin32-ctypes |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| requests | 2.34.2 | Apache-2.0 | https://github.com/psf/requests |
| certifi | 2026.7.22 | MPL-2.0 | https://github.com/certifi/python-certifi |
| charset-normalizer | 3.5.2 | MIT | https://github.com/jawah/charset_normalizer |
| idna | 3.20 | BSD-3-Clause | https://github.com/kjd/idna |
| urllib3 | 2.8.0 | MIT | https://github.com/urllib3/urllib3 |
| OpenSSL (libssl-3.dll, libcrypto-3.dll, from CPython) | 3.0 | Apache-2.0 | https://www.openssl.org/source/ |
| Microsoft Visual C++ runtime (vcruntime140*.dll, msvcp140*.dll) | - | Microsoft Distributable Code | https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files |

- Licence texts in the app folder, copied at build time from each package's metadata:
  `licenses\<package>-<version>\`, plus `licenses\python-<version>\LICENSE.txt`,
  `licenses\pyinstaller-<version>\COPYING.txt` and `licenses\openssl-<version>\LICENSE.txt`.
  PySide6 and shiboken6 get the LGPL-3.0 text (`third_party/licenses/LGPL-3.0.txt`); the GPL-3.0
  text it builds on is `LICENSE.txt`. libsndfile's LGPL-2.1 text is
  `_internal\_soundfile_data\COPYING`.
- CPython also incorporates other software (Expat, libmpdec, zlib, bzip2, liblzma, libffi,
  HACL\*...). Their licences: `licenses\python-<version>\LICENSE.txt` and
  https://docs.python.org/3.13/license.html#licenses-and-acknowledgements-for-incorporated-software.
- Qt itself incorporates third-party code; see https://doc.qt.io/qt-6/licenses-used-in-qt.html.
- Qt, PySide6, shiboken6 and libsndfile are separate DLLs in `_internal\`. As the LGPL allows,
  you can replace them with your own compatible builds of the same versions.
- The canonical texts in `third_party/licenses/` come from https://www.gnu.org/licenses/lgpl-3.0.txt
  and https://www.apache.org/licenses/LICENSE-2.0.txt.
