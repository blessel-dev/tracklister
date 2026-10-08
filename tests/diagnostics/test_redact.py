"""Redactor: own secrets, IPs, peers -> peer-N, user profile path."""
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
    assert os.environ.get("USERPROFILE") is not None or True
