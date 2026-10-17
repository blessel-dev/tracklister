"""Redaction of engine output and of the Diagnostico report.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

- Secrets (own username/password) -> "[censurado]" (the engines print the login username).
- Any IPv4/IPv6 literal (validated with `ipaddress`, so "23:51:27" or "3.0.5" stay) and the
  user's own IPs -> "[censurado]". IPv4 has its own pass first, so "1.2.3.4:2242", "IP:1.2.3.4"
  and "1.2.3.4." are caught too (the port stays).
- Peer names registered with peer() -> "peer-1", "peer-2"... (stable per Redactor).
- The user's home folder (it contains the account name) -> "%USERPROFILE%" on Windows, "~" on macOS.

redact(text, peers=False) skips the peer names (1.0.1, R7): the Diagnóstico puts the pseudonym in the
peer column itself, and a peer called "50", "6" or "?" must never turn «título distinto (50%)» into
«(peer-6%)» or «? MB» into «peer-1 MB» (audit r4-3 N8). Secrets, IPs and the profile path still go.
"""
from __future__ import annotations

import ipaddress
import os
import re
from pathlib import Path
from typing import Iterable

from tracklister.core import osplatform

CENSORED = "[censurado]"
HOME_LABEL_WINDOWS = "%USERPROFILE%"
HOME_LABEL_MACOS = "~"


def home_label() -> str:
    """What the user's home folder becomes in a redacted text: %USERPROFILE% on Windows, ~ on macOS."""
    return HOME_LABEL_MACOS if osplatform.is_macos() else HOME_LABEL_WINDOWS
# Dedicated IPv4 pass (audit round 3, B2), before the generic one: also an endpoint 'ip:port' (how .NET
# prints it), 'IP:1.2.3.4' and an address at the end of a sentence ('...1.2.3.4.'). Four dotted numbers,
# not part of a longer dotted number; ipaddress.IPv4Address decides. '3.0.5', '01:02:03' never match.
_IPV4_CANDIDATE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d|\.\d)")
_IP_CANDIDATE = re.compile(r"(?<![\w.:])[0-9A-Fa-f:.]*[.:][0-9A-Fa-f:.]*(?![\w.:])")


def _ipv4_or_same(m: re.Match) -> str:
    try:
        ipaddress.IPv4Address(m.group(0))
    except ValueError:
        return m.group(0)
    return CENSORED


def _is_ip(token: str) -> bool:
    t = token.strip("[]")
    if t.count(".") == 3 and ":" not in t:
        try:
            ipaddress.IPv4Address(t)
            return True
        except ValueError:
            return False
    if t.count(":") >= 2:
        try:
            ipaddress.IPv6Address(t)
            return True
        except ValueError:
            return False
    return False


class Redactor:
    def __init__(self, secrets: Iterable[str] = (), own_ips: Iterable[str] = ()):
        self._secrets: list[str] = []
        for s in secrets:
            self.add_secret(s)
        self._own_ips = [ip for ip in own_ips if ip]
        self._peers: dict[str, str] = {}
        profile = os.environ.get("USERPROFILE") or str(Path.home())
        self._profiles = sorted({p for p in (profile, str(Path.home())) if p and len(p) > 3}, key=len, reverse=True)
        self._home_label = home_label()

    def add_secret(self, s: str | None) -> None:
        if s and s not in self._secrets:
            self._secrets.append(s)
            self._secrets.sort(key=len, reverse=True)

    @property
    def secrets(self) -> list[str]:
        return list(self._secrets)

    def peer(self, name: str) -> str:
        """Stable pseudonym for a peer name within this report."""
        if name not in self._peers:
            self._peers[name] = f"peer-{len(self._peers) + 1}"
        return self._peers[name]

    def _sub_ci(self, text: str, needle: str, repl: str) -> str:
        return re.sub(re.escape(needle), lambda _m: repl, text, flags=re.IGNORECASE)

    def redact(self, text: str, *, peers: bool = True) -> str:
        """Censor secrets, IPs and the profile path; with peers=True also the registered peer names."""
        if not text:
            return text
        out = text
        for s in self._secrets:
            out = re.sub(secret_pattern(s), lambda _m: CENSORED, out, flags=re.IGNORECASE)
        for p in self._profiles:
            for variant in (p, p.replace("\\", "/"), p.replace("\\", "\\\\")):
                out = self._sub_ci(out, variant, self._home_label)
        for ip in self._own_ips:
            out = out.replace(ip, CENSORED)
        out = _IPV4_CANDIDATE.sub(_ipv4_or_same, out)
        out = _IP_CANDIDATE.sub(lambda m: CENSORED if _is_ip(m.group(0)) else m.group(0), out)
        if peers:
            for name in sorted(self._peers, key=len, reverse=True):
                out = re.sub(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", lambda _m, n=name: self._peers[n], out)
        return out


SHORT_SECRET = 4


def secret_pattern(s: str) -> str:
    """Regex for a secret. Very short ones (< 4 chars) only match as a whole token, so that a
    one-letter account name does not wipe every letter of the engine's output."""
    if len(s) < SHORT_SECRET:
        return r"(?<![A-Za-z0-9])" + re.escape(s) + r"(?![A-Za-z0-9])"
    return re.escape(s)


def assert_no_secrets(text: str, secrets: Iterable[str]) -> None:
    """Raise AssertionError if any secret survived (case-insensitive, same rule as redact)."""
    for s in secrets:
        if s and re.search(secret_pattern(s), text, flags=re.IGNORECASE):
            raise AssertionError("el informe contiene un dato privado sin censurar")
