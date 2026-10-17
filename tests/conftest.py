"""Global test safety net. Owner: core (frozen during the parallel phase).

Autouse for EVERY test:
- TRACKLISTER_HOME -> a temp dir, so no test touches the real %APPDATA%/%LOCALAPPDATA%.
- An in-memory keyring backend, so no test touches Windows Credential Manager.
- A socket guard: any connection to a non-loopback address fails the test. Enrichment/update
  tests must use recorded fixtures (replay transport); engine tests use the FAKE engine.
  This laptop must never reach Soulseek (server.slsknet.org:2242) or any peer.

On request (1.1): `as_macos` / `as_windows` simulate that platform's policy for one test, so the macOS
branches run on Windows and the Windows ones on the macOS runner (tracklister.core.osplatform).
"""
from __future__ import annotations

import socket

import keyring
import keyring.backend
import pytest

from tracklister.core import osplatform

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture
def as_macos():
    """Simulate macOS's POLICY (tracklister.core.osplatform: paths, texts, pins, names, keys) for one test.
    Request it BEFORE any fixture that builds widgets: def test_x(as_macos, window)."""
    with osplatform.simulate(osplatform.MACOS):
        yield


@pytest.fixture
def as_windows():
    """The same for Windows, so a Windows text or table is also checked on the macOS runner."""
    with osplatform.simulate(osplatform.WINDOWS):
        yield


class MemoryKeyring(keyring.backend.KeyringBackend):
    """Fake keyring backend for tests (never persisted)."""
    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.store:
            import keyring.errors
            raise keyring.errors.PasswordDeleteError(username)
        del self.store[(service, username)]


@pytest.fixture(autouse=True)
def _tracklister_home(tmp_path, monkeypatch):
    home = tmp_path / "tlhome"
    home.mkdir()
    monkeypatch.setenv("TRACKLISTER_HOME", str(home))
    return home


@pytest.fixture(autouse=True)
def fake_keyring():
    previous = keyring.get_keyring()
    kr = MemoryKeyring()
    keyring.set_keyring(kr)
    try:
        yield kr
    finally:
        keyring.set_keyring(previous)


def _host_of(address) -> str:
    if isinstance(address, tuple) and address:
        return str(address[0])
    return str(address)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Blocks every non-loopback connect / DNS lookup, and fails the test at teardown if any was
    attempted: app code that swallows errors (the update check returns None on ANY exception)
    must not turn a regression into a silent pass. The list of attempts is the fixture value."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    blocked: list[str] = []

    def refuse(what: str):
        blocked.append(what)
        raise RuntimeError(what)

    def guard(self, address):
        host = _host_of(address)
        if self.family == getattr(socket, "AF_UNIX", object()) or host in _LOOPBACK:
            return real_connect(self, address)
        refuse(f"Network access blocked in tests: {address!r}")

    def guard_ex(self, address):
        host = _host_of(address)
        if host in _LOOPBACK:
            return real_connect_ex(self, address)
        refuse(f"Network access blocked in tests: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket.socket, "connect_ex", guard_ex)

    def no_dns(*args, **kwargs):
        host = args[0] if args else kwargs.get("host")
        if host in _LOOPBACK or host is None:
            return real_getaddrinfo(*args, **kwargs)
        refuse(f"DNS lookup blocked in tests: {host!r}")

    real_getaddrinfo = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", no_dns)
    yield blocked
    if blocked:
        attempts, blocked[:] = list(blocked), []
        pytest.fail("A test tried to reach the network: " + "; ".join(attempts), pytrace=False)
