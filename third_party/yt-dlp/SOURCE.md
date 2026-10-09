# yt-dlp 2026.08.19 (bundled with Tracklister as tools\yt-dlp.exe)

- Upstream: https://github.com/yt-dlp/yt-dlp
- Licence: The Unlicense (public domain); `LICENSE` in this folder, copied unchanged from the tag.
- The official Windows build is a PyInstaller bundle that also contains Python and other
  third-party components. Their licences are in `THIRD_PARTY_LICENSES.txt` in this folder,
  copied unchanged from the tag.
- Exact tag: https://github.com/yt-dlp/yt-dlp/tree/2026.08.19
- Binary: `yt-dlp.exe` from https://github.com/yt-dlp/yt-dlp/releases/tag/2026.08.19
  - SHA-256 (GitHub Releases API `digest`, cross-checked with the release's `SHA2-256SUMS`):
    `66674953fe251b89f4d08c5f0e35e0728679bd67ab3d7d05c0562af101dd3e7a`
- Licence texts at the tag (downloaded on 2026-10-09):
  - `LICENSE`: `7e12e5df4bae12cb21581ba157ced20e1986a0508dd10d0e8a4ab9a4cf94e85c`
  - `THIRD_PARTY_LICENSES.txt`: `472aefe951c7db35e1657c1d13fd337140511ed6f2b329205105ad441c5a02b7`
- Sin modificar: Tracklister ships the official exe unmodified and only runs it as a separate
  process. On first run the app copies it to `%LOCALAPPDATA%\Tracklister\tools\`, where
  "Actualizar yt-dlp" (`yt-dlp -U`) replaces it with the newest official release.
- Fetch and verify: `.venv\Scripts\python.exe packaging\fetch_ytdlp.py`.
