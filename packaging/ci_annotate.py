"""Turn a failed CI job into a few GitHub error annotations: the failing tests and the key log lines.

SPDX-License-Identifier: GPL-3.0-or-later

    python packaging/ci_annotate.py --title-prefix macOS --junit dist/ci/pytest.xml
        --log dist/ci/pytest.log dist/ci/build.log build/pyinstaller.log --smoke dist/ci/smoke.json --max 10
    python packaging/ci_annotate.py --title-prefix macOS --summary dist/ci/pytest.log --junit dist/ci/pytest.xml

Annotations can be read through the public GitHub API without logging in; the full logs cannot. So when
a step of the macOS job fails, this prints at most --max `::error title=...::...` lines, in this order:
1. the failing tests (JUnit XML of pytest), each with the first line of its message;
2. the key lines of the logs: errors, BuildError, the exception line of each Python traceback, and
   codesign or ditto failures, each with the indented lines right after it;
3. the failed checks of the macOS smoke test (its JSON), with their detail.
If none of them says anything, the last line of each log. On a branch the app is also built and smoke-tested
after failed tests (brief mac-1b), so the failing tests leave room for up to half of the annotations of 2 and 3.

--summary prints ONE `::notice` instead, with pytest's own summary line ('5 failed, 1531 passed, 6 skipped in
386.35s'; from the JUnit counts when pytest wrote none), after every test run, passed or failed.

Missing files are skipped. Standard library only, and the exit code is always 0: it reports a failure, it
never causes one.
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
# pytest's last line: '5 failed, 1531 passed, 6 skipped in 386.35s (0:06:26)', '=' around it without -q
SUMMARY_LINE = re.compile(r"^=*\s*(?P<counts>\d+ [a-z]+(?:, \d+ [a-z]+)*) in (?P<secs>\d+(?:\.\d+)?)s\b")
COUNT_WORDS = {"failed", "passed", "skipped", "deselected", "xfailed", "xpassed", "warning", "warnings",
               "error", "errors", "rerun"}


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


def _unique(found: list[tuple[str, str]], skip: set[str] | None = None) -> list[tuple[str, str]]:
    """(title, shortened text) pairs, each text once, in order; texts in `skip` are left out."""
    seen, out = set(skip or ()), []
    for title, text in found:
        text = _short(text)
        if text not in seen:
            seen.add(text)
            out.append((title, text))
    return out


def annotations(prefix: str, junit: list[Path], logs: list[Path], smoke: Path | None,
                limit: int) -> list[str]:
    tests: list[tuple[str, str]] = []
    for path in junit:
        tests += [(f"{prefix} test", f"{test_id}: {msg}") for test_id, msg in junit_failures(path)]
    others: list[tuple[str, str]] = []
    for path in logs:
        for line in log_key_lines(path):
            if tests and PYTEST_SUMMARY.match(line):
                continue                       # pytest's own "FAILED x::y - ..." line: the JUnit one says it
            others.append((f"{prefix} {path.name}", line))
    if smoke is not None:
        others += [(f"{prefix} smoke", line) for line in smoke_failures(smoke)]
    if not tests and not others:
        for path in logs:
            line = last_line(path)
            if line:
                others.append((f"{prefix} {path.name} (última línea)", line))
    tests = _unique(tests)
    others = _unique(others, {text for _, text in tests})
    # a branch build also packages the app after failed tests: many failing tests must not hide why the build
    # or the smoke test failed, so they leave room for up to half of the annotations
    n_tests = min(len(tests), limit - min(len(others), limit // 2))
    chosen = tests[:n_tests] + others[:limit - n_tests]
    return [f"::error title={escape_property(title)}::{escape_data(text)}" for title, text in chosen]


def pytest_summary(log: Path | None) -> str | None:
    """pytest's own last summary line, without its '=' decoration and the (h:mm:ss) after the seconds."""
    if log is None:
        return None
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        m = SUMMARY_LINE.match(line.strip())
        if m and all(part.split(" ", 1)[1] in COUNT_WORDS for part in m.group("counts").split(", ")):
            return f"{m.group('counts')} in {m.group('secs')}s"
    return None


def junit_totals(paths: list[Path]) -> str | None:
    """'1531 passed, 5 failed, 6 skipped' from the counts of the JUnit XML files (None without any)."""
    passed = failed = skipped = errors = 0
    seen = False
    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            continue
        for suite in ([root] if root.tag == "testsuite" else list(root.iter("testsuite"))):
            seen = True
            tests, fails, errs, skips = (int(suite.get(k) or 0) for k in ("tests", "failures", "errors", "skipped"))
            passed += tests - fails - errs - skips
            failed, errors, skipped = failed + fails, errors + errs, skipped + skips
    if not seen:
        return None
    return f"{passed} passed, {failed} failed, {skipped} skipped" + (f", {errors} errors" if errors else "")


def summary_notice(prefix: str, log: Path | None, junit: list[Path]) -> str:
    """The `::notice` with the test totals of the run."""
    text = pytest_summary(log)
    if text is None:
        totals = junit_totals(junit)
        text = (f"{totals} (del JUnit: pytest no escribió su resumen)" if totals
                else "pytest no dejó resumen (¿se cortó antes de terminar?)")
    return f"::notice title={escape_property(prefix + ' pytest')}::{escape_data(text)}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--title-prefix", default="CI")
    ap.add_argument("--junit", type=Path, nargs="*", default=[])
    ap.add_argument("--log", type=Path, nargs="*", default=[])
    ap.add_argument("--smoke", type=Path, default=None)
    ap.add_argument("--max", type=int, default=10)
    ap.add_argument("--summary", type=Path, default=None,
                    help="pytest's log: print only the notice with the test totals (from --junit without a summary)")
    try:
        a = ap.parse_args(argv)
        if a.summary is not None:
            lines = [summary_notice(a.title_prefix, a.summary, a.junit)]
        else:
            lines = annotations(a.title_prefix, a.junit, a.log, a.smoke, max(1, a.max))
    except (SystemExit, Exception) as e:  # noqa: BLE001 - reporting must never fail the job
        print(f"ci_annotate: {type(e).__name__}: {e}")
        return 0
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
