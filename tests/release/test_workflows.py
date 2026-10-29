"""The GitHub Actions workflows (1.1): release.yml builds Windows and macOS and publishes ONE Release, only for
a v* tag; a push to branch mac is a test build that publishes nothing; pages.yml is untouched.

SPDX-License-Identifier: GPL-3.0-or-later

Static checks with PyYAML (a dev pin). YAML 1.1 reads the key `on` as the boolean True.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
import yaml

from tests.release.helpers import REPO, load
from tracklister import config
from tracklister.net.update_check import owner_configured

WORKFLOWS = REPO / ".github" / "workflows"
RELEASE = WORKFLOWS / "release.yml"
PAGES = WORKFLOWS / "pages.yml"
CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
SETUP_PYTHON = "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
UPLOAD = "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9"      # v7.0.2
DOWNLOAD = "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333"  # v8.0.2
# pages.yml at a6a1199 (the website workflow, frozen in 1.1): LF-normalised SHA-256 and size
PAGES_SHA256 = "c33ed0025823978d6801c1d6b43fa3855acbeac9e30f72a048748dc80e473ef0"
PAGES_BYTES = 2755


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _steps(job: str) -> list[dict]:
    return _load(RELEASE)["jobs"][job]["steps"]


def _all_steps() -> list[tuple[str, dict]]:
    return [(job, step) for job, spec in _load(RELEASE)["jobs"].items() for step in spec["steps"]]


def test_release_runs_on_v_tags_and_on_branch_mac_only():
    wf = _load(RELEASE)
    assert "on" not in wf and wf[True] == {"push": {"tags": ["v*"], "branches": ["mac"]}}
    text = RELEASE.read_text(encoding="utf-8")
    assert "pull_request" not in text and "schedule:" not in text and "workflow_dispatch" not in text
    assert wf["concurrency"] == {"group": "release-${{ github.ref }}", "cancel-in-progress": False}


def test_three_jobs_with_their_runners_needs_and_permissions():
    wf = _load(RELEASE)
    jobs = wf["jobs"]
    assert list(jobs) == ["windows", "macos", "publish"]
    assert wf["permissions"] == {"contents": "read"}
    assert (jobs["windows"]["runs-on"], jobs["macos"]["runs-on"], jobs["publish"]["runs-on"]) == (
        "windows-2025", "macos-15", "ubuntu-24.04")          # a fixed image: ubuntu-latest moves to Ubuntu 26
    assert "needs" not in jobs["windows"] and "needs" not in jobs["macos"]
    assert jobs["publish"]["needs"] == ["windows", "macos"]                   # 1.1.0 only when both builds pass
    assert jobs["windows"]["permissions"] == jobs["macos"]["permissions"] == {"contents": "read"}
    assert jobs["publish"]["permissions"] == {"contents": "write"}            # the only job that can write
    assert jobs["windows"]["defaults"]["run"]["shell"] == "pwsh"
    assert jobs["macos"]["defaults"]["run"]["shell"] == jobs["publish"]["defaults"]["run"]["shell"] == "bash"
    assert jobs["macos"]["timeout-minutes"] == 75


def test_every_action_is_pinned_to_a_full_commit_sha_with_its_version():
    for path in (RELEASE, PAGES):
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if "uses:" in ln]
        assert lines
        for ln in lines:
            assert re.search(r"uses:\s*[\w.-]+/[\w.-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$", ln), (path.name, ln)
    uses = {step["uses"] for _, step in _all_steps() if "uses" in step}
    assert uses == {CHECKOUT, SETUP_PYTHON, UPLOAD, DOWNLOAD}
    for _, step in _all_steps():
        if step.get("uses") == CHECKOUT:
            assert step["with"] == {"persist-credentials": False}


def _run_of(step: dict) -> str:
    return step.get("run", "")


def test_the_windows_job_keeps_its_steps_and_only_uploads_instead_of_publishing():
    """1.0.x steps, in order and with the same commands; the one change in them is the --ref-type of
    ci_prepare (a branch build has no tag). The last step keeps the files for the publish job."""
    steps = _steps("windows")
    expected = [
        ("Check out the tagged commit", CHECKOUT, None),
        ("Set up Python 3.13", SETUP_PYTHON, None),
        ("Check the tag and the GitHub owner", None,
         'python packaging\\ci_prepare.py --tag "$env:GITHUB_REF_NAME" --ref-type "$env:GITHUB_REF_TYPE" '
         '--owner "$env:GITHUB_REPOSITORY_OWNER" --repo "$env:REPO_NAME" --placeholder "$env:OWNER_PLACEHOLDER"'),
        ("Create the venv from the exact pins", None,
         "python -m venv .venv\nif ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n"
         ".\\.venv\\Scripts\\python.exe -m pip install --no-input -r requirements-dev.lock.txt\n"),
        ("Fetch the pinned engines (SHA-256 verified)", None, ".\\.venv\\Scripts\\python.exe tools\\fetch_engine.py"),
        ("Fetch the pinned yt-dlp (SHA-256 verified)", None, ".\\.venv\\Scripts\\python.exe packaging\\fetch_ytdlp.py"),
        ("Run the tests (offline, fake engine)", None, ".\\.venv\\Scripts\\python.exe -m pytest -q"),
        ("Build the app and the release files", None,
         ".\\.venv\\Scripts\\python.exe packaging\\build.py --zip --no-identity-scan"),
        ("Smoke-test the exe without Python on PATH", None,
         ".\\.venv\\Scripts\\python.exe packaging\\smoke_test.py --offscreen --screenshot dist\\smoke\\first-run.png"),
    ]
    assert len(steps) == len(expected) + 1
    for step, (name, uses, run) in zip(steps, expected):
        assert step["name"] == name and step.get("uses") == uses and step.get("run") == run, step
    assert steps[2]["env"] == {"REPO_NAME": "${{ github.event.repository.name }}"}
    assert steps[6]["env"] == {"QT_QPA_PLATFORM": "offscreen"}
    upload = steps[-1]
    assert upload["uses"] == UPLOAD and upload["with"] == {
        "name": "windows-release", "path": "dist/release/Tracklister-*-win64.zip\ndist/release/*-source.zip\n",
        "if-no-files-found": "error"}


def test_the_macos_job_builds_tests_smoke_tests_and_uploads_the_zip_unchanged():
    steps = _steps("macos")
    runs = [_run_of(s) for s in steps]
    order = ["sw_vers", "packaging/ci_prepare.py", "--only-binary=:all: -r requirements-dev.lock.txt",
             "packaging/check_lock.py", "tools/fetch_engine.py", "packaging/fetch_ytdlp.py", "-m pytest -q",
             "packaging/build.py --zip --no-identity-scan", "packaging/smoke_test_macos.py --offscreen"]
    found = [next((i for i, r in enumerate(runs) if needle in r), None) for needle in order]
    assert None not in found and found == sorted(found), dict(zip(order, found))
    assert '--ref-type "$GITHUB_REF_TYPE"' in runs[found[1]]
    tests = runs[found[6]]
    assert "set -o pipefail" in tests and "--junitxml=dist/ci/pytest.xml" in tests and "| tee dist/ci/pytest.log" in tests
    assert next(s for s in steps if "-m pytest" in _run_of(s))["env"] == {"QT_QPA_PLATFORM": "offscreen"}
    build = runs[found[7]]
    assert "set -o pipefail" in build and "| tee dist/ci/build.log" in build
    assert "--json dist/ci/smoke.json" in runs[found[8]]
    upload = [s for s in steps if s.get("uses") == UPLOAD]
    assert len(upload) == 1 and steps.index(upload[0]) > found[8]
    assert upload[0]["with"] == {"path": "dist/release/Tracklister-*-macos-arm64.zip", "archive": False,
                                 "if-no-files-found": "error"}
    explain = steps[-1]
    assert explain["if"] == "failure()" and explain["run"].startswith("python packaging/ci_annotate.py --title-prefix macOS")
    for needle in ("--junit dist/ci/pytest.xml", "dist/ci/build.log", "build/pyinstaller.log",
                   "--smoke dist/ci/smoke.json", "--max 10"):
        assert needle in explain["run"]
    # 1.1b: the ids the conditions read, and the totals notice right after the tests
    tests_step = steps[found[6]]
    assert (tests_step["id"], steps[found[7]]["id"], steps[found[8]]["id"]) == ("tests", "build", "smoke")
    summary = steps[found[6] + 1]
    assert summary["name"] == "Report the test totals (annotation)" and summary["run"] == (
        "python packaging/ci_annotate.py --title-prefix macOS --summary dist/ci/pytest.log --junit dist/ci/pytest.xml")
    assert not [s["name"] for s in steps if "continue-on-error" in s]     # a failed step always turns the job red


# ---- 1.1b: what runs in the macOS job, simulated with GitHub's rules for `if:` ----------------------------------

_TOKEN = re.compile(r"'[^']*'|&&|\|\||==|!=|!|\(|\)|[A-Za-z_][\w.-]*\(\)|[A-Za-z_][\w.-]*")


def _gh_if(expr: str | None, ctx: dict) -> bool:
    """A step's `if:` as GitHub Actions evaluates it, for the expressions of the macOS job: the status functions,
    !, &&, ||, ==, !=, parentheses, 'strings', github.ref_type and steps.<id>.outcome. Without a status function
    GitHub puts `success() &&` in front; no `if:` at all is `success()`."""
    text = (expr or "").strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2].strip()
    text = text or "success()"
    if not re.search(r"\b(success|failure|cancelled|always)\(\)", text):
        text = f"success() && ({text})"
    assert not _TOKEN.sub("", text).strip(), f"cannot read: {expr!r}"
    py = []
    for t in _TOKEN.findall(text):
        if t in ("&&", "||", "!"):
            py.append({"&&": " and ", "||": " or ", "!": " not "}[t])
        elif t in ("==", "!=", "(", ")") or t.startswith("'"):
            py.append(t)
        elif t.endswith("()"):
            py.append(repr(ctx[t[:-2]]))
        elif t == "github.ref_type":
            py.append(repr(ctx["ref_type"]))
        elif t.startswith("steps.") and t.endswith(".outcome"):
            py.append(repr(ctx["steps"].get(t[len("steps."):-len(".outcome")], "")))
        else:
            raise AssertionError(f"unexpected {t!r} in {expr!r}")
    return bool(eval("".join(py), {"__builtins__": {}}, {}))  # noqa: S307 - this repository's own workflow


def _run_macos_job(ref_type: str, failing: set[str]) -> tuple[dict[str, str], str]:
    """The macOS job of a push of `ref_type` where the steps in `failing` (by id, or by name) fail and every other
    step that runs succeeds: (the outcome of each step by name, the job's conclusion)."""
    outcomes: dict[str, str] = {}
    by_id: dict[str, str] = {}
    failed = False
    for step in _steps("macos"):
        ctx = {"success": not failed, "failure": failed, "cancelled": False, "always": True, "ref_type": ref_type,
               "steps": by_id}
        if _gh_if(step.get("if"), ctx):
            outcome = "failure" if {step.get("id"), step["name"]} & failing else "success"
        else:
            outcome = "skipped"
        outcomes[step["name"]] = outcome
        if step.get("id"):
            by_id[step["id"]] = outcome
        failed = failed or outcome == "failure"
    return outcomes, "failure" if failed else "success"


S_TESTS, S_TOTALS = "Run the tests (offline, fake engine)", "Report the test totals (annotation)"
S_BUILD, S_SMOKE = "Build, sign and zip the app", "Smoke-test the app"
S_UPLOAD = "Keep the macOS zip as it is (the artifact is the zip itself)"
S_EXPLAIN, S_VENV = "Explain the failure (annotations)", "Create the venv from the exact pins (wheels only)"
ALL_OK = {S_TESTS, S_TOTALS, S_BUILD, S_SMOKE, S_UPLOAD}


@pytest.mark.parametrize("ref_type,failing,ran,conclusion", [
    # a branch push: failed tests do not stop the build and the smoke test; the zip only goes up when all passed
    ("branch", set(), ALL_OK, "success"),
    ("branch", {"tests"}, {S_TESTS, S_TOTALS, S_BUILD, S_SMOKE, S_EXPLAIN}, "failure"),
    ("branch", {"tests", "build"}, {S_TESTS, S_TOTALS, S_BUILD, S_EXPLAIN}, "failure"),
    ("branch", {"tests", "smoke"}, {S_TESTS, S_TOTALS, S_BUILD, S_SMOKE, S_EXPLAIN}, "failure"),
    ("branch", {"build"}, {S_TESTS, S_TOTALS, S_BUILD, S_EXPLAIN}, "failure"),
    ("branch", {"smoke"}, {S_TESTS, S_TOTALS, S_BUILD, S_SMOKE, S_EXPLAIN}, "failure"),
    ("branch", {S_VENV}, {S_EXPLAIN}, "failure"),              # no venv: nothing after it is worth running
    # a v* tag stays strict: any failure stops the job there
    ("tag", set(), ALL_OK, "success"),
    ("tag", {"tests"}, {S_TESTS, S_TOTALS, S_EXPLAIN}, "failure"),
    ("tag", {"build"}, {S_TESTS, S_TOTALS, S_BUILD, S_EXPLAIN}, "failure"),
    ("tag", {"smoke"}, {S_TESTS, S_TOTALS, S_BUILD, S_SMOKE, S_EXPLAIN}, "failure"),
], ids=["branch-ok", "branch-tests", "branch-tests-build", "branch-tests-smoke", "branch-build", "branch-smoke",
        "branch-venv", "tag-ok", "tag-tests", "tag-build", "tag-smoke"])
def test_a_branch_build_still_packages_after_failed_tests_and_a_tag_stays_strict(ref_type, failing, ran, conclusion):
    outcomes, got = _run_macos_job(ref_type, failing)
    watched = {S_TESTS, S_TOTALS, S_BUILD, S_SMOKE, S_UPLOAD, S_EXPLAIN}
    assert {name for name in watched if outcomes[name] != "skipped"} == ran, outcomes
    assert got == conclusion                                  # failed tests always leave the job red


def test_the_condition_reader_follows_github_s_rules():
    ctx = {"success": False, "failure": True, "cancelled": False, "always": True, "ref_type": "branch",
           "steps": {"tests": "failure"}}
    assert not _gh_if(None, ctx) and not _gh_if("steps.tests.outcome == 'failure'", ctx)   # success() && ... added
    assert _gh_if("failure()", ctx) and _gh_if("${{ !cancelled() && steps.tests.outcome != 'success' }}", ctx)
    assert not _gh_if("${{ success() || github.ref_type == 'tag' }}", ctx)


def test_publish_downloads_both_artifacts_and_runs_dry_on_branches():
    steps = _steps("publish")
    downloads = [s for s in steps if s.get("uses") == DOWNLOAD]
    assert [d["with"] for d in downloads] == [
        {"name": "windows-release", "path": "dist/publish/in"},
        {"pattern": "Tracklister-*-macos-arm64.zip", "skip-decompress": True, "merge-multiple": True,
         "path": "dist/publish/in"}]                                           # v8 would unzip it otherwise
    gather = next(s for s in steps if "publish_release.py" in _run_of(s))
    assert gather["env"] == {"MODE": "${{ github.ref_type == 'tag' && 'publish' || 'dry-run' }}"}
    assert "--files dist/publish/in --out dist/publish/out --notes dist/publish/release-notes.md" in gather["run"]
    assert '--mode "$MODE"' in gather["run"] and "if" not in gather              # the dry run runs on branches too
    assert steps.index(gather) > max(steps.index(d) for d in downloads)


def test_only_a_v_tag_step_publishes_and_it_never_creates_a_tag():
    mentions = [(job, s) for job, s in _all_steps() if "gh release" in _run_of(s)]
    assert len(mentions) == 1
    job, step = mentions[0]
    assert job == "publish" and step == _steps("publish")[-1]
    assert step["if"] == "github.ref_type == 'tag' && startsWith(github.ref, 'refs/tags/v')"
    assert "--verify-tag" in step["run"] and "gh release create" in step["run"]
    assert 'if [ "$GITHUB_REF_TYPE" != "tag" ]' in step["run"]               # checked again inside the step
    assert step["env"] == {"GH_TOKEN": "${{ github.token }}", "TAG": "${{ github.ref_name }}"}
    tokens = [(j, s) for j, s in _all_steps() if "github.token" in str(s) or "secrets." in str(s)]
    assert tokens == [mentions[0]]
    for _, s in _all_steps():
        run = _run_of(s)
        assert not re.search(r"\bgit\s+(tag|push)\b", run), run
        assert "git/refs" not in run and "/tags" not in run.replace("refs/tags/v*", "")
    assert "secrets." not in RELEASE.read_text(encoding="utf-8")


def test_owner_is_the_placeholder_constant(monkeypatch):
    wf = RELEASE.read_text(encoding="utf-8")
    ci = load("ci_prepare")
    assert _load(RELEASE)["env"]["OWNER_PLACEHOLDER"] == ci.PLACEHOLDER == "OWNER_PLACEHOLDER"
    for job in ("windows", "macos"):
        prepare = next(s for s in _steps(job) if "ci_prepare.py" in _run_of(s))
        assert "--placeholder" in prepare["run"] and "OWNER_PLACEHOLDER" in prepare["run"]
        assert "GITHUB_REPOSITORY_OWNER" in prepare["run"] and "--ref-type" in prepare["run"]
    assert not re.search(r"github\.com/(?!OWNER_PLACEHOLDER)[\w-]+/tracklister", wf)   # no real owner written in
    monkeypatch.setattr(config, "GITHUB_OWNER", ci.PLACEHOLDER)
    assert not owner_configured()                                   # the app also treats it as "not published"


def test_pages_is_unchanged_and_never_runs_from_branch_mac():
    raw = PAGES.read_bytes().replace(b"\r\n", b"\n")
    assert (len(raw), hashlib.sha256(raw).hexdigest()) == (PAGES_BYTES, PAGES_SHA256)
    on = _load(PAGES)[True]
    assert set(on) == {"push", "workflow_dispatch"} and on["push"]["branches"] == ["main"]
    assert "tags" not in on["push"] and "mac" not in str(on)


def test_the_release_names_line_up_with_the_scripts():
    build, pub = load("build"), load("publish_release")
    assert build.zip_name("win32") == pub.win_zip_name() and build.zip_name("darwin") == pub.mac_zip_name()
    assert build.SUMS_NAME == pub.SUMS_NAME == "SHA256SUMS.txt"
    assert re.fullmatch(r"Tracklister-\*-macos-arm64\.zip", _steps("publish")[3]["with"]["pattern"])
