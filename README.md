# Tracklister

Desktop app for Windows 10/11 (64-bit). You give it a DJ-set tracklist and it returns a folder of verified audio files from Soulseek, in tracklist order. The window header reads "Tracklister by Blessel".

Status: under construction (v1.0.0). Pending decisions are in [DECISIONES.md](DECISIONES.md).

## Development

```powershell
& "C:\Program Files\Python313\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock.txt
.\.venv\Scripts\python.exe -m pytest -q
```

- Runtime pins: `requirements.lock.txt`. Dev, test and build pins: `requirements-dev.lock.txt`.
- Tests never touch the network or the real keyring (see `tests/conftest.py`).
- Engine tests use a fake engine (`tests/fakes/fake_engine.py`).

## Build the Windows app

```powershell
.\.venv\Scripts\python.exe tools\fetch_engine.py      # pinned engines, SHA-256 checked (public GitHub)
.\.venv\Scripts\python.exe packaging\fetch_ytdlp.py   # pinned yt-dlp.exe, SHA-256 checked
.\.venv\Scripts\python.exe packaging\build.py --zip   # dist\Tracklister\ and dist\release\
.\.venv\Scripts\python.exe packaging\smoke_test.py    # the exe starts without Python: first-run screen
```

- `packaging/tracklister.spec`: PyInstaller onedir, windowed, no UPX, the "T" icon.
- `packaging/build.py` adds the engine zips, yt-dlp and every licence text next to the exe, then refuses the
  bundle if anything is missing or does not belong (tests, scipy, `.tmp`, user files, a wrong SHA-256).
- `dist\release\`: `Tracklister-<version>-win64.zip`, the engines' source archives and `SHA256SUMS.txt`.
- Release: pushing a tag `v<version>` runs `.github/workflows/release.yml` on a Windows runner (tests, build,
  smoke test) and publishes those files as a GitHub Release. The tag must match `__version__`.

## Licence

Tracklister is free software: GPL-3.0-or-later (GNU General Public License, version 3 or, at your option,
any later version). See [LICENSE](LICENSE). Third-party notices, licences and source links:
[third_party/NOTICES.md](third_party/NOTICES.md).
