"""Credential store on the FAKE keyring backend (conftest fake_keyring).

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import keyring
import keyring.backend
import keyring.errors
import pytest

from tracklister import config
from tracklister.engine.credentials import CredentialError, Credentials, CredentialStore, store_name_es


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


class BrokenKeyring(keyring.backend.KeyringBackend):
    """A credential store that refuses everything (a locked Keychain, a broken Credential Manager)."""
    priority = 1

    def get_password(self, service, username):
        raise keyring.errors.KeyringLocked("locked")

    def set_password(self, service, username, password):
        raise keyring.errors.KeyringLocked("locked")

    def delete_password(self, service, username):
        raise keyring.errors.KeyringLocked("locked")


def _messages() -> list[str]:
    st = CredentialStore()
    out = []
    for call in (st.get, lambda: st.set(Credentials("usuario-prueba", "clave-prueba")), st.clear):
        with pytest.raises(CredentialError) as e:
            call()
        out.append(e.value.msg_es)
    return out


def test_windows_store_messages_are_those_of_1_0(as_windows, fake_keyring):
    keyring.set_keyring(BrokenKeyring())
    assert store_name_es() == "Administrador de credenciales de Windows"
    assert _messages() == [
        "No se pudo leer la cuenta del Administrador de credenciales de Windows (KeyringLocked).",
        "No se pudo guardar la cuenta en el Administrador de credenciales de Windows (KeyringLocked).",
        "No se pudo borrar la cuenta del Administrador de credenciales de Windows (KeyringLocked)."]


def test_mac_store_messages_name_the_keychain(as_macos, fake_keyring):
    keyring.set_keyring(BrokenKeyring())
    assert store_name_es() == "Llavero de macOS"
    msgs = _messages()
    assert msgs == ["No se pudo leer la cuenta del Llavero de macOS (KeyringLocked).",
                    "No se pudo guardar la cuenta en el Llavero de macOS (KeyringLocked).",
                    "No se pudo borrar la cuenta del Llavero de macOS (KeyringLocked)."]
    assert not any("Windows" in m or "usuario-prueba" in m or "clave-prueba" in m for m in msgs)
