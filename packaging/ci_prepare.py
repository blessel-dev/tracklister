"""Release checks for GitHub Actions: the tag matches the app version, and the GitHub owner is set.

SPDX-License-Identifier: GPL-3.0-or-later

    python packaging/ci_prepare.py --tag v1.0.0 --owner <repository owner> [--repo tracklister]

- The tag must be exactly "v" + tracklister.__version__, and pyproject.toml must say the same
  version. Otherwise the job stops: an exe that reports another version would make the in-app
  update notice wrong forever. Pre-releases ("v1.0.1rc1") follow the same rule.
- GITHUB_OWNER (src/tracklister/config.py) is the single constant that points the update check
  and the MusicBrainz User-Agent at the published repo. If it is still the placeholder, this
  script fills it in with the repository owner for THIS build only (the runner's checkout; nothing
  is committed) and prints a warning. If it names another owner (a fork), it is kept, with a warning.

Exit code 0 when the build may go on, 1 otherwise. Messages use GitHub's ::error:: / ::warning::.
"""
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "src" / "tracklister" / "config.py"
INIT = REPO / "src" / "tracklister" / "__init__.py"
PYPROJECT = REPO / "pyproject.toml"
PLACEHOLDER = "OWNER_PLACEHOLDER"           # the value of GITHUB_OWNER until the repo is published
_OWNER_LINE = re.compile(r'^(GITHUB_OWNER\s*=\s*)"([^"]*)"', re.MULTILINE)
_REPO_LINE = re.compile(r'^GITHUB_REPO\s*=\s*"([^"]*)"', re.MULTILINE)
_VALID_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


def app_version(init: Path = INIT) -> str:
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', init.read_text(encoding="utf-8"), re.MULTILINE)
    if not m:
        raise ValueError(f"no __version__ in {init}")
    return m.group(1)


def pyproject_version(path: Path | None = None) -> str:
    with open(path or PYPROJECT, "rb") as f:
        data = tomllib.load(f)
    try:
        return str(data["project"]["version"])
    except (KeyError, TypeError) as e:
        raise ValueError("no hay [project] version en pyproject.toml") from e


def check_versions(app: str, pyproject: str) -> str | None:
    """Error message, or None when pyproject.toml and the app say the same version."""
    if app != pyproject:
        return (f"La versión de pyproject.toml ({pyproject}) no coincide con la de la app ({app}, "
                "src/tracklister/__init__.py). Pon la misma en los dos.")
    return None


def check_tag(tag: str, version: str) -> str | None:
    """Error message, or None when the tag is v<version>."""
    if tag != f"v{version}":
        return (f"La etiqueta {tag!r} no coincide con la versión de la app ({version}). "
                f"Sube la versión en src/tracklister/__init__.py o usa la etiqueta v{version}.")
    return None


def set_owner(config_text: str, owner: str, placeholder: str = PLACEHOLDER) -> tuple[str, list[str]]:
    """(new config text, warnings). Raises ValueError for an invalid owner or config."""
    m = _OWNER_LINE.search(config_text)
    if not m:
        raise ValueError("GITHUB_OWNER no aparece en config.py")
    if not _VALID_OWNER.match(owner or ""):
        raise ValueError(f"Propietario de GitHub no válido: {owner!r}")
    current = m.group(2)
    if current == placeholder:
        new = config_text[:m.start()] + f'{m.group(1)}"{owner}"' + config_text[m.end():]
        return new, [f"GITHUB_OWNER seguía siendo {placeholder}: esta build usa {owner!r}. "
                     f"Para que el código del repo diga lo mismo, pon GITHUB_OWNER = \"{owner}\" en "
                     "src/tracklister/config.py."]
    if current.lower() != owner.lower():
        return config_text, [f"GITHUB_OWNER es {current!r} y el repo es de {owner!r} (¿un fork?): "
                             "el aviso de actualización seguirá mirando el repo de GITHUB_OWNER."]
    return config_text, []


def check_repo_name(config_text: str, repo_name: str | None) -> list[str]:
    m = _REPO_LINE.search(config_text)
    if repo_name and m and m.group(1).lower() != repo_name.lower():
        return [f"GITHUB_REPO es {m.group(1)!r} pero el repo se llama {repo_name!r}: el aviso de "
                "actualización buscará en el nombre de GITHUB_REPO."]
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", required=True, help="the pushed tag, e.g. v1.0.0 (GITHUB_REF_NAME)")
    ap.add_argument("--owner", required=True, help="the repository owner (github.repository_owner)")
    ap.add_argument("--repo", default=None, help="the repository name (github.event.repository.name)")
    ap.add_argument("--placeholder", default=PLACEHOLDER, help="the placeholder value of GITHUB_OWNER")
    a = ap.parse_args(argv)
    try:
        error = check_versions(app_version(), pyproject_version()) or check_tag(a.tag, app_version())
    except ValueError as e:
        error = str(e)
    if error:
        print(f"::error::{error}")
        return 1
    text = CONFIG.read_text(encoding="utf-8")
    try:
        new, warnings = set_owner(text, a.owner, a.placeholder)
    except ValueError as e:
        print(f"::error::{e}")
        return 1
    warnings += check_repo_name(new, a.repo)
    if new != text:
        CONFIG.write_text(new, encoding="utf-8", newline="\n")
    for w in warnings:
        print(f"::warning::{w}")
    print(f"OK: etiqueta {a.tag}, versión {app_version()}, propietario {a.owner}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
