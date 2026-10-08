"""Credential store on the FAKE keyring backend (conftest fake_keyring)."""
from __future__ import annotations

import pytest

from tracklister import config
from tracklister.engine.credentials import CredentialError, Credentials, CredentialStore


def test_roundtrip_and_layout(fake_keyring):
    st = CredentialStore()
    assert st.get() is None
    st.set(Credentials("usuario-prueba", "clave-prueba"))
    assert st.get() == Credentials("usuario-prueba", "clave-prueba")
    assert fake_keyring.store[(config.KEYRING_SERVICE, config.KEYRING_ACCOUNT_KEY)] == "usuario-prueba"
    assert fake_keyring.store[(config.KEYRING_SERVICE, "usuario-prueba")] == "clave-prueba"


def test_changing_account_removes_old_password(fake_keyring):
    st = CredentialStore()
    st.set(Credentials("viejo", "x1"))
    st.set(Credentials("nuevo", "x2"))
    assert (config.KEYRING_SERVICE, "viejo") not in fake_keyring.store
    assert st.get() == Credentials("nuevo", "x2")


def test_clear(fake_keyring):
    st = CredentialStore()
    st.set(Credentials("usuario-prueba", "clave-prueba"))
    st.clear()
    assert st.get() is None and fake_keyring.store == {}
    st.clear()  # idempotent


def test_repr_never_shows_secrets():
    c = Credentials("usuario-prueba", "clave-prueba")
    for s in (repr(c), str(c), f"{c}", f"{c!r}"):
        assert "usuario-prueba" not in s and "clave-prueba" not in s


def test_empty_values_refused():
    with pytest.raises(CredentialError):
        CredentialStore().set(Credentials("", "x"))
    with pytest.raises(CredentialError):
        CredentialStore().set(Credentials("u", ""))
