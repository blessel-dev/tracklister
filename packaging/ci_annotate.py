"""Turn a failed CI job into a few GitHub error annotations: the failing tests and the key log lines.

SPDX-License-Identifier: GPL-3.0-or-later

    python packaging/ci_annotate.py --title-prefix macOS --junit dist/ci/pytest.xml
        --log dist/ci/pytest.log dist/ci/build.log build/pyinstaller.log --smoke dist/ci/smoke.json --max 10

Annotations can be read through the public GitHub API without logging in; the full logs cannot. So when
a step of the macOS job fails, this prints at most --max `::error title=...::...` lines, in this order:
1. the failing tests (JUnit XML of pytest), each with the first line of its message;
2. the key lines of the logs: errors, BuildError, the exception line of each Python traceback, and
   codesign or ditto failures, each with the indented lines right after it;
3. the failed checks of the macOS smoke test (its JSON), with their detail.
If none of them says anything, the last line of each log. Missing files are skipped. Standard library
only, and the exit code is always 0: it reports a failure, it never causes one.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET  # noqa: S405 - the XML is this job's own pytest output
from pathlib import Path

MAX_TEXT = 400
KEY_LINE = re.compile(
    r"(?i)(^\s*ERROR\b|\bERROR:|\bBuildError\b|^\s*error:|\bcodesign\b.*\b(fail\w*|invalid|error|not signed)\b|"
    r"\bnot signed at all\b|\bsealed resource\b|^\s*ditto:|\bditto\b.*\b(fail\w*|error)\b|^FAILED\b)")
TRACEBACK = "Traceback (most recent call last)"
PYTEST_SUMMARY = re.compile(r"^(FAILED|ERROR) \S+::")


def escape_data(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_property(text: str) -> str:
    return escape_data(text).replace(":", "%3A").replace(",", "%2C")


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 1] + "…"


def junit_failures(path: Path) -> list[tuple[str, str]]:
    """[(test id, first line of its failure or error message)] from a pytest --junitxml file."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return []
    out = []
    for case in root.iter("testcase"):
        for kind in ("failure", "error"):
            el = case.find(kind)
            if el is None:
                continue
            first = (el.get("message") or el.text or kind).strip().splitlines()
            test_id = "::".join(x for x in (case.get("classname"), case.get("name")) if x)
            out.append((test_id or "?", first[0] if first else kind))
            break
    return out


def log_key_lines(path: Path) -> list[str]:
    """The key lines of a log, each followed by up to 3 indented detail lines; for a traceback, its
    exception line."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if TRACEBACK in line:
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j][:1].isspace()):
                j += 1
            if j < len(lines):
                out.append(f"Traceback: {lines[j].strip()}")
            i = j + 1
            continue
        if KEY_LINE.search(line):
            details = []
            j = i + 1
            while j < len(lines) and len(details) < 3 and lines[j][:1].isspace() and lines[j].strip():
                details.append(lines[j].strip())
                j += 1
            out.append(" / ".join([line.strip()] + details))
            i = j
            continue
        i += 1
    return out


def last_line(path: Path) -> str | None:
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    except OSError:
        return None
    return lines[-1].strip() if lines else None


def smoke_failures(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    details = (data.get("info") or {}).get("details") or {}
    return [f"{name}: {details.get(name) or 'falló'}" for name, ok in (data.get("checks") or {}).items() if not ok]


def annotations(prefix: str, junit: list[Path], logs: list[Path], smoke: Path | None,
                limit: int) -> list[str]:
    found: list[tuple[str, str]] = []
    for path in junit:
        found += [(f"{prefix} test", f"{test_id}: {msg}") for test_id, msg in junit_failures(path)]
    tests_reported = bool(found)
    for path in logs:
        for line in log_key_lines(path):
            if tests_reported and PYTEST_SUMMARY.match(line):
                continue                       # pytest's own "FAILED x::y - ..." line: the JUnit one says it
            found.append((f"{prefix} {path.name}", line))
    if smoke is not None:
        found += [(f"{prefix} smoke", line) for line in smoke_failures(smoke)]
    if not found:
        for path in logs:
            line = last_line(path)
            if line:
                found.append((f"{prefix} {path.name} (última línea)", line))
    seen, out = set(), []
    for title, text in found:
        text = _short(text)
        if text in seen:
            continue
        seen.add(text)
        out.append(f"::error title={escape_property(title)}::{escape_data(text)}")
        if len(out) >= limit:
            break
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--title-prefix", default="CI")
    ap.add_argument("--junit", type=Path, nargs="*", default=[])
    ap.add_argument("--log", type=Path, nargs="*", default=[])
    ap.add_argument("--smoke", type=Path, default=None)
    ap.add_argument("--max", type=int, default=10)
    try:
        a = ap.parse_args(argv)
        lines = annotations(a.title_prefix, a.junit, a.log, a.smoke, max(1, a.max))
    except (SystemExit, Exception) as e:  # noqa: BLE001 - reporting must never fail the job
        print(f"ci_annotate: {type(e).__name__}: {e}")
        return 0
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
