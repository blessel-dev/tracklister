"""Count-only secrets scan: how many times each real-credential pattern appears. Never a value.

SPDX-License-Identifier: GPL-3.0-or-later

    .\\.venv\\Scripts\\python.exe tools\\secrets_scan.py [--extra DIR ...]

What is scanned: every file git tracks plus the untracked files that are not ignored (exactly
what would be published on GitHub), and each --extra folder (for example a temporary
TRACKLISTER_HOME after a fake-engine run, or the screenshots folder).

What is counted (the user's real Soulseek account is unknown here and its sldl.conf is never
opened, so the scan looks for SHAPES of real credentials, minus the dummy test values):
- tokens and keys: PEM private keys, AWS/GitHub/Slack/Google keys;
- a Soulseek account written out: sldl.conf-style `username = x` / `password = x` lines, a
  `--user x` / `--pass x` command line, `"password": "x"` in JSON, `password = "x"` in Python;
- this laptop's Windows account name and computer name (a public repo must not carry them).

- (1.0.1, 06 R9) what is left of the real YouTube/SoundCloud comments that the 1.0.0 test fixtures
  carried: their authors' @aliases and display names («alias retirados») and their text («comentarios
  retirados»). Only SHA-256 fingerprints are kept (tools/retired_handles.sha256 and
  tools/retired_comments.sha256), never the names or the text themselves.

Output: one line per pattern with its count and, for a non-zero count, the file paths only.
Exit code 0 when every count is 0, else 1.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Values that are never a real credential: the dummy accounts of the tests and screenshots
# (tests/conftest.py, tests/engine/test_cli_golden.py), redaction markers, placeholders, and the
# prose words that follow a flag in documentation ("Provide --user and --pass").
DUMMY_VALUES = {"usuario-prueba", "clave-prueba", "-raro", "-secreto", "usuario", "contraseña", "contrasena",
                "tu_usuario", "tu-usuario", "tu_contraseña", "tu-contraseña", "user", "pass", "password",
                "username", "and", "or", "y", "o", "con", "de"}
_PLACEHOLDER = re.compile(r"""^(?:<[^>]*>|\{[^}]*\}|\$\{?\w+\}?|%\w+%|\*+|\[censurado\]|\.\.\.|x+|-+)$""",
                          re.IGNORECASE)
# Both engines' `--print json-all` search results carry the PEER's name as "User": {"Username": ...}:
# that is somebody else's public Soulseek name in a recorded fixture, not an account of ours.
_PEER_IN_SEARCH_RESULT = re.compile(r"\"User\"\s*:\s*\{\s*$")
SELF = Path(__file__).resolve()

TEXT_SUFFIXES_NOT_PY = {".md", ".txt", ".conf", ".cfg", ".ini", ".toml", ".yml", ".yaml", ".json", ".bat",
                        ".cmd", ".ps1", ".csv", ".log", ".m3u", ".env", ".spec", ".xml", ".html"}


@dataclass(frozen=True)
class Pattern:
    key: str
    label_es: str
    regex: re.Pattern
    scope: str = "all"          # "all" (also binary files) | "text" | "text_not_py" | "py"
    value_group: int = 0        # >0: the captured value must not be a dummy/placeholder


def _p(key, label, rx, scope="all", group=0, flags=0) -> Pattern:
    return Pattern(key, label, re.compile(rx, flags), scope, group)


PATTERNS: tuple[Pattern, ...] = (
    _p("pem_private_key", "clave privada PEM", r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    _p("aws_access_key", "clave de acceso de AWS", r"(?<![A-Z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Z0-9])"),
    _p("aws_secret_key", "secreto de AWS", r"(?i)aws_secret_access_key\s*[=:]\s*[A-Za-z0-9/+]{40}"),
    _p("github_token", "token de GitHub",
       r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})"),
    _p("slack_token", "token de Slack", r"(?<![A-Za-z0-9])xox[abprs]-[A-Za-z0-9-]{10,}"),
    _p("google_api_key", "clave de API de Google", r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_\-]{35}(?![A-Za-z0-9_\-])"),
    _p("conf_account_line", "cuenta en un archivo de configuracion (usuario = / contrasena =)",
       r"^[ \t]*(?:user|username|login|pass|password|passwd)[ \t]*[=:][ \t]*[\"']?([^\s\"'#;]+)",
       scope="text_not_py", group=1, flags=re.IGNORECASE | re.MULTILINE),
    _p("cli_account", "cuenta en una linea de comandos (--user / --pass con valor)",
       r"(?<![\w-])--(?:user|pass|username|password)(?:=|[ \t]+)[\"']?([^\s\"'`,;()\[\]/][^\s\"'`,;()\[\]]*)",
       scope="text", group=1, flags=re.IGNORECASE),
    _p("json_secret", "secreto en JSON (\"password\": \"...\")",
       r"\"(?:password|pass|passwd|pwd|secret|token|api_?key|access_?token|username|user)\"\s*:\s*\"([^\"]+)\"",
       scope="text", group=1, flags=re.IGNORECASE),
    _p("py_secret_literal", "secreto escrito en el codigo (password = \"...\")",
       r"\b(?:password|passwd|pwd|secret|api_?key|access_?token|soulseek_pass\w*)\s*[:=]\s*(?:str\s*=\s*)?"
       r"[\"']([^\"']+)[\"']",
       scope="py", group=1, flags=re.IGNORECASE),
)


def computer_names() -> set[str]:
    """This computer's name: COMPUTERNAME on Windows. Where it is not set (macOS has no COMPUTERNAME),
    the host name from socket.gethostname(), and also its part before the first dot
    ("mac-de-x.local" -> "mac-de-x")."""
    host = os.environ.get("COMPUTERNAME", "")
    if host:
        return {host}
    import socket
    try:
        name = socket.gethostname()
    except OSError:
        return set()
    return {name, name.split(".", 1)[0]}


def local_identity_patterns() -> tuple[Pattern, ...]:
    """This laptop's Windows account and computer name (values never printed)."""
    out = []
    names = {os.environ.get("USERNAME", ""), Path.home().name}
    for n in sorted(x for x in names if len(x) >= 3):
        out.append(_p("windows_account", "nombre de la cuenta de Windows de este PC",
                      r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])", flags=re.IGNORECASE))
    for host in sorted(x for x in computer_names() if len(x) >= 3):
        out.append(_p("computer_name", "nombre de este PC",
                      r"(?<![A-Za-z0-9])" + re.escape(host) + r"(?![A-Za-z0-9])", flags=re.IGNORECASE))
    return tuple(out)


def is_dummy(value: str) -> bool:
    v = value.strip().strip("\"'")
    return not v or v.lower() in DUMMY_VALUES or bool(_PLACEHOLDER.match(v))


# ---- retired comments (06 R9): fingerprints only ---------------------------------------------------------
RETIRED_HANDLES_FILE = REPO / "tools" / "retired_handles.sha256"
RETIRED_COMMENTS_FILE = REPO / "tools" / "retired_comments.sha256"
_AT_TOKEN = re.compile(r"@[\w.\-]+")
_ESCAPED_SPACE = re.compile(r"\\[nrt]")
_ESCAPED_CHAR = re.compile(r"\\u([0-9a-fA-F]{4})")
_WORD = re.compile(r"[^\W_]+")
NGRAM_HEX = 16


def handle_digest(token: str) -> str:
    """SHA-256 of an @alias as it is compared: lower case, with its '@', without a trailing '.' or '-'
    (the end of a sentence)."""
    return hashlib.sha256(token.strip().rstrip(".-").lower().encode("utf-8")).hexdigest()


def text_words(text: str) -> list[str]:
    """The comparison words of a text: JSON/Python escapes (\\n, \\u2019) undone, accents removed, lower case,
    runs of letters and digits of any script. 'Don\u2019t STOP\\nnow' -> ['don', 't', 'stop', 'now']."""
    text = _ESCAPED_CHAR.sub(lambda m: chr(int(m.group(1), 16)), _ESCAPED_SPACE.sub(" ", text))
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return _WORD.findall(text.lower())


def ngram_digest(words: Sequence[str]) -> str:
    """First NGRAM_HEX hex digits of the SHA-256 of n consecutive comparison words joined by spaces."""
    return hashlib.sha256(" ".join(words).encode("utf-8")).hexdigest()[:NGRAM_HEX]


def _fingerprint_lines(path: Path) -> list[str]:
    """The data lines of a fingerprint file ('#' lines are comments). A missing file is an error: the scan
    must never pass because its list went missing."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


@dataclass
class FingerprintRule:
    """Counts the words or @aliases of a text whose fingerprint is in a list. Never sees a real value."""
    key: str
    label_es: str
    source: Path
    kind: str                       # "handles": SHA-256 of '@alias'; "ngrams": 'n hex16' of n words
    scope: str = "text"
    _handles: frozenset[str] | None = field(default=None, repr=False)
    _ngrams: dict[int, frozenset[str]] | None = field(default=None, repr=False)

    def load(self) -> None:
        if self.kind == "handles":
            if self._handles is None:
                self._handles = frozenset(ln.split()[0].lower() for ln in _fingerprint_lines(self.source))
        elif self._ngrams is None:
            by_n: dict[int, set[str]] = {}
            for ln in _fingerprint_lines(self.source):
                n, digest = ln.split()[:2]
                by_n.setdefault(int(n), set()).add(digest.lower())
            self._ngrams = {n: frozenset(d) for n, d in by_n.items()}

    def size(self) -> int:
        self.load()
        return len(self._handles) if self.kind == "handles" else sum(len(d) for d in self._ngrams.values())

    def count(self, text: str) -> int:
        self.load()
        if self.kind == "handles":
            return sum(1 for m in _AT_TOKEN.finditer(text) if handle_digest(m.group(0)) in self._handles)
        words = text_words(text)
        hits = 0
        for n, digests in self._ngrams.items():
            hits += sum(1 for i in range(len(words) - n + 1) if ngram_digest(words[i:i + n]) in digests)
        return hits


def retired_rules(handles: Path = RETIRED_HANDLES_FILE, comments: Path = RETIRED_COMMENTS_FILE
                  ) -> tuple[FingerprintRule, ...]:
    return (FingerprintRule("retired_handle", "alias retirados (autores de los comentarios reales de los fixtures "
                                              "de la 1.0.0)", Path(handles), "handles"),
            FingerprintRule("retired_comment", "comentarios retirados (texto de los comentarios reales de los "
                                               "fixtures de la 1.0.0)", Path(comments), "ngrams"))


@dataclass
class ScanResult:
    files_scanned: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    files: dict[str, set[str]] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def publishable_files(repo: Path = REPO) -> list[Path]:
    """Tracked + untracked-not-ignored files, as git would publish them."""
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                       capture_output=True, check=True)
    names = [n for n in r.stdout.decode("utf-8", errors="replace").split("\0") if n]
    return [repo / n for n in sorted(set(names)) if (repo / n).is_file()]


def files_under(dirs: Iterable[Path]) -> list[Path]:
    out: list[Path] = []
    for d in dirs:
        d = Path(d)
        if d.is_file():
            out.append(d)
        elif d.is_dir():
            out += [p for p in d.rglob("*") if p.is_file()]
    return out


def _decode(data: bytes) -> tuple[str, bool]:
    """(text, is_text). UTF-16 files (Excel 'Texto Unicode') are decoded as text too."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace"), True
    if b"\x00" in data[:8192]:
        return data.decode("latin-1"), False
    return data.decode("utf-8", errors="replace"), True


def _applies(p: Pattern, path: Path, is_text: bool) -> bool:
    suffix = path.suffix.lower()
    if p.scope == "all":
        return True
    if not is_text:
        return False
    if p.scope == "text":
        return True
    if p.scope == "py":
        return suffix == ".py"
    if p.scope == "text_not_py":
        return suffix in TEXT_SUFFIXES_NOT_PY or (suffix == "" and path.name.startswith("."))
    return False


def scan(paths: Iterable[Path], patterns: Iterable[Pattern] = PATTERNS, *, root: Path | None = None) -> ScanResult:
    pats = list(patterns)
    res = ScanResult(counts={p.key: 0 for p in pats}, labels={p.key: p.label_es for p in pats},
                     files={p.key: set() for p in pats})
    for path in paths:
        if Path(path).resolve() == SELF:            # this file spells the patterns out
            continue
        try:
            data = Path(path).read_bytes()
        except OSError:
            continue
        res.files_scanned += 1
        text, is_text = _decode(data)
        try:
            shown = str(Path(path).relative_to(root)) if root else str(path)
        except ValueError:
            shown = str(path)
        for p in pats:
            if not _applies(p, Path(path), is_text):
                continue
            if isinstance(p, FingerprintRule):
                n = p.count(text)
                if n:
                    res.counts[p.key] += n
                    res.files[p.key].add(shown)
                continue
            n = 0
            for m in p.regex.finditer(text):
                if p.value_group and is_dummy(m.group(p.value_group)):
                    continue
                if p.key == "json_secret" and _PEER_IN_SEARCH_RESULT.search(text[max(0, m.start() - 40):m.start()]):
                    continue
                n += 1
            if n:
                res.counts[p.key] += n
                res.files[p.key].add(shown)
    return res


def count_literals(paths: Iterable[Path], literals: Iterable[str]) -> int:
    """How many times any of `literals` appears in the files (UTF-8, UTF-16-LE and latin-1 bytes,
    case-insensitive). Used after a fake run to prove the account never reaches the disk."""
    needles = []
    for lit in literals:
        if not lit:
            continue
        for enc in ("utf-8", "utf-16-le", "latin-1"):
            try:
                b = lit.encode(enc)
            except UnicodeEncodeError:
                continue
            if b not in needles:
                needles.append(b)
    total = 0
    for path in paths:
        try:
            data = Path(path).read_bytes().lower()
        except OSError:
            continue
        for b in needles:
            total += data.count(b.lower())
    return total


def report_lines(res: ScanResult) -> list[str]:
    lines = [f"Archivos revisados: {res.files_scanned}"]
    for key, n in res.counts.items():
        lines.append(f"{n:5d}  {res.labels[key]} [{key}]")
        for f in sorted(res.files[key]):
            lines.append(f"         en {f}")
    lines.append(f"Total: {res.total}")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--extra", type=Path, action="append", default=[], help="carpeta o archivo extra")
    args = ap.parse_args(argv)
    paths = publishable_files(REPO) + files_under(args.extra)
    res = scan(paths, PATTERNS + local_identity_patterns() + retired_rules(), root=REPO)
    for line in report_lines(res):
        print(line)
    return 0 if res.total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
