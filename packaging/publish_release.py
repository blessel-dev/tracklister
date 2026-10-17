"""Gather the GitHub Release files of both builds: the two zips, the engines' sources, ONE SHA256SUMS.txt
and the notes.

SPDX-License-Identifier: GPL-3.0-or-later

    python packaging/publish_release.py --files dist/publish/in --out dist/publish/out
                                        --notes dist/publish/release-notes.md --mode dry-run|publish

Run by the `publish` job of .github/workflows/release.yml after the Windows and macOS jobs, with no venv
(standard library only). It never publishes anything itself: the workflow's last step does, and only for
a v* tag. This script:

1. finds, anywhere under --files (the downloaded artifacts), exactly one Tracklister-<v>-win64.zip, one
   Tracklister-<v>-macos-arm64.zip and the <id>-source.zip of every engine source archive, where <v> is
   the app version of this commit. A missing, repeated or unexpected zip stops it (exit code 1);
2. copies them to --out and writes ONE SHA256SUMS.txt for all of them (coreutils format, sorted), so the
   two platform jobs never write two different checksum files;
3. fills packaging/release-notes.md ({version}, {zip_name} = the Windows zip, {sums}, {mac_zip_name})
   into --notes. While that template has no macOS section ({mac_zip_name}), a dry run (branch push)
   appends a clearly marked placeholder, and a publish run (tag) refuses: a tag never publishes
   placeholder notes;
4. prints SHA256SUMS.txt and the notes, each in its own log group.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(REPO / "src") not in sys.path:
    sys.path.append(str(REPO / "src"))      # appended, so nothing on sys.path is shadowed

from tracklister import __version__  # noqa: E402
from tracklister.engine.spec import SOURCE_ARCHIVES  # noqa: E402

TEMPLATE = HERE / "release-notes.md"
SUMS_NAME = "SHA256SUMS.txt"
MAC_MARKER = "<!-- MARCADOR (fase D): notas de macOS pendientes -->"


def win_zip_name(version: str = __version__) -> str:
    return f"Tracklister-{version}-win64.zip"


def mac_zip_name(version: str = __version__) -> str:
    return f"Tracklister-{version}-macos-arm64.zip"


def expected_names(version: str = __version__) -> list[str]:
    return [win_zip_name(version), mac_zip_name(version)] + [f"{eid}-source.zip" for eid in SOURCE_ARCHIVES]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_release_files(root: Path, version: str = __version__) -> tuple[dict[str, Path], list[str]]:
    """({file name: path} of the expected zips under `root`, problems). Only zips count; other files are
    ignored."""
    wanted = expected_names(version)
    found: dict[str, list[Path]] = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_file() and p.name.lower().endswith(".zip"):
            found.setdefault(p.name, []).append(p)
    problems = []
    for name in wanted:
        paths = found.get(name, [])
        if not paths:
            problems.append(f"falta {name}")
        elif len(paths) > 1:
            problems.append(f"{name} aparece {len(paths)} veces: "
                            + ", ".join(str(p.relative_to(root)) for p in paths))
    for name in sorted(set(found) - set(wanted)):
        problems.append(f"zip inesperado: {name} (la versión de este commit es {version})")
    return {name: found[name][0] for name in wanted if len(found.get(name, [])) == 1}, problems


def sums_text(files: list[Path]) -> str:
    return "".join(f"{sha256_file(p)}  {p.name}\n" for p in sorted(files, key=lambda x: x.name))


def notes_text(template: str, version: str, sums: str, *, mode: str) -> tuple[str | None, str | None]:
    """(notes, error). Without {mac_zip_name} in the template: a dry run appends a marked placeholder,
    a publish run gives an error instead of notes."""
    text = (template.replace("{version}", version).replace("{zip_name}", win_zip_name(version))
            .replace("{sums}", sums.strip()))
    if "{mac_zip_name}" in template:
        return text.replace("{mac_zip_name}", mac_zip_name(version)), None
    if mode == "publish":
        return None, ("packaging/release-notes.md todavía no tiene la sección de macOS ({mac_zip_name}): "
                      "no se publica una release con notas a medias. Escríbela antes de crear la etiqueta.")
    placeholder = (f"\n{MAC_MARKER}\n"
                   f"**[MARCADOR, solo en esta prueba]** Mac con Apple Silicon: `{mac_zip_name(version)}`. "
                   "Las notas de macOS se escriben antes de publicar la 1.1.0; esta ejecución no publica nada.\n")
    return text.rstrip("\n") + "\n" + placeholder, None


def _group(title: str, body: str) -> None:
    print(f"::group::{title}")
    print(body.rstrip("\n"))
    print("::endgroup::")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--files", type=Path, required=True, help="where the downloaded artifacts are")
    ap.add_argument("--out", type=Path, required=True, help="folder for the Release files (emptied first)")
    ap.add_argument("--notes", type=Path, required=True, help="where to write the Release notes")
    ap.add_argument("--mode", choices=("dry-run", "publish"), required=True,
                    help="dry-run on a branch push (placeholders allowed), publish on a v* tag")
    a = ap.parse_args(argv)
    if not a.files.is_dir():
        print(f"::error title=Publicar::No existe la carpeta de artefactos {a.files}")
        return 1
    listing = sorted(str(p.relative_to(a.files)) for p in a.files.rglob("*") if p.is_file())
    _group(f"Artefactos descargados ({len(listing)})", "\n".join(listing) or "(ninguno)")
    files, problems = find_release_files(a.files)
    for problem in problems:
        print(f"::error title=Publicar::{problem}")
    if problems:
        # the log needs a login; the annotations do not: say what the downloads really were
        print(f"::error title=Publicar::Descargado: {', '.join(listing[:12]) or '(nada)'}")
        return 1
    template = TEMPLATE.read_text(encoding="utf-8")
    # the notes are checked before anything is written: a tag without macOS notes stops here
    _, error = notes_text(template, __version__, "", mode=a.mode)
    if error:
        print(f"::error title=Publicar::{error}")
        return 1
    shutil.rmtree(a.out, ignore_errors=True)
    a.out.mkdir(parents=True)
    copies = []
    for name, src in files.items():
        dst = a.out / name
        shutil.copy2(src, dst)
        copies.append(dst)
    sums = sums_text(copies)
    (a.out / SUMS_NAME).write_text(sums, encoding="ascii", newline="\n")
    notes, _ = notes_text(template, __version__, sums, mode=a.mode)
    a.notes.parent.mkdir(parents=True, exist_ok=True)
    a.notes.write_text(notes, encoding="utf-8", newline="\n")
    _group(SUMS_NAME, sums)
    _group(f"Notas de la release ({a.mode})", notes)
    print(f"OK {len(copies) + 1} archivos en {a.out} ({a.mode}"
          + (", no se publica nada)" if a.mode == "dry-run" else ")"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
