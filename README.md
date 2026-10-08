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

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE) and `third_party/` for third-party notices.
