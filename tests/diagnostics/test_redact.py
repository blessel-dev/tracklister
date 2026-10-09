"""Redactor: own secrets, IPs, peers -> peer-N, user profile path.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import os

import pytest

from tracklister.diagnostics.redact import CENSORED, Redactor, assert_no_secrets


def test_secrets_case_insensitive_and_ips():
    r = Redactor(secrets=["usuario-prueba", "clave-prueba"], own_ips=["83.45.1.200"])
    t = r.redact("[soulseek] Logging in as USUARIO-prueba.. pass=clave-prueba from 83.45.1.200 and 10.0.0.7 "
                 "and fe80::1 and 2001:db8::8a2e:370:7334")
    assert "usuario" not in t.lower() and "clave" not in t.lower()
    assert "83.45" not in t and "10.0.0.7" not in t and "fe80" not in t and "2001:db8" not in t
    assert t.count(CENSORED) >= 6


def test_keeps_times_versions_and_ratios():
    r = Redactor(secrets=["s3cr3t"])
    t = "2026-10-09 23:51:27 Sockseek 3.0.5 sldl 2.6.0 4:05 44.1kHz 12:00"
    assert r.redact(t) == t


def test_peers_are_stable_pseudonyms():
    r = Redactor()
    assert r.peer("dj_mike") == "peer-1" and r.peer("anna") == "peer-2" and r.peer("dj_mike") == "peer-1"
    assert r.redact("dj_mike\\Music and anna and dj_mike2") == "peer-1\\Music and peer-2 and dj_mike2"


def test_user_profile_path(monkeypatch, tmp_path):
    prof = r"C:\Users\Juanito"
    monkeypatch.setenv("USERPROFILE", prof)
    r = Redactor()
    assert r.redact(r"C:\Users\Juanito\Music\x.flac") == r"%USERPROFILE%\Music\x.flac"
    assert r.redact("C:/Users/Juanito/Music") == "%USERPROFILE%/Music"
    assert "Juanito" not in r.redact(r'{"p":"C:\\Users\\Juanito\\Music"}')


def test_assert_no_secrets():
    assert_no_secrets("todo limpio", ["usuario-prueba"])
    with pytest.raises(AssertionError):
        assert_no_secrets("hola USUARIO-PRUEBA", ["usuario-prueba"])


@pytest.mark.parametrize("text,expected", [
    ("Connecting to 203.0.113.7:2242", "Connecting to [censurado]:2242"),          # ip:port (.NET endpoint)
    ("IP:203.0.113.7", "IP:[censurado]"),                                           # after a colon
    ("addr=203.0.113.7.", "addr=[censurado]."),                                     # before a full stop
    ("Listening on 0.0.0.0:49998, peer 198.51.100.23:51234.", "Listening on [censurado]:49998, peer [censurado]:51234."),
    ("[203.0.113.7]:2242 / (10.0.0.7)", "[[censurado]]:2242 / ([censurado])"),
    ("::ffff:203.0.113.7", "::ffff:[censurado]"),
])
def test_r3_b2_ipv4_with_a_port_after_a_colon_or_before_a_full_stop(text, expected):
    """Audit round 3, B2: these three forms came back unchanged. The user pastes this report in a chat."""
    out = Redactor().redact(text)
    assert out == expected
    assert "203.0.113" not in out and "198.51" not in out and "10.0.0" not in out


@pytest.mark.parametrize("text", [
    "Sockseek 3.0.5 / sldl 2.6.0 / Tracklister 1.0.0 / yt-dlp 2026.08.19",           # versions
    "01:02:03 23:51:27 4:05 1:02:03.5",                                              # times
    "Duraci\u00f3n 245 s (4:05), 320 kbps, 1411.2 kbps, 44.1 kHz, 48.0kHz, 12.5 MB, 1,9MB",   # durations, bitrates
    "Windows 10.0.19045.3803", "1.2.3.4.5", "999.1.1.1", "v1.2.3.4567",             # not an IPv4
])
def test_r3_b2_versions_times_durations_and_bitrates_are_kept(text):
    assert Redactor().redact(text) == text


def test_very_short_secrets_only_as_whole_tokens():
    r = Redactor(secrets=["jo", "7"])
    out = r.redact("[003] SongJob: searching: Jo - Joy Division 7 | Logging in as jo..")
    assert out == "[003] SongJob: searching: [censurado] - Joy Division [censurado] | Logging in as [censurado].."
    assert_no_secrets(out, ["jo", "7"])
    assert os.environ.get("PATH")
