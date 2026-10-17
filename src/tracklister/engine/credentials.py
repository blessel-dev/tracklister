"""The user's own Soulseek account, kept in the system's credential store through keyring.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

Windows Credential Manager on Windows; the macOS Keychain on a Mac (keyring picks the backend itself).
Never written to settings.json, logs or reports. The username is stored as the password of the
fixed account `config.KEYRING_ACCOUNT_KEY`; the password is stored under the username.
"""
from __future__ import annotations

from dataclasses import dataclass

import keyring
import keyring.errors

from tracklister import config
from tracklister.core import osplatform

STORE_NAME_WINDOWS_ES = "Administrador de credenciales de Windows"
STORE_NAME_MACOS_ES = "Llavero de macOS"


def store_name_es() -> str:
    """Where the account is kept, as the user knows it: «Administrador de credenciales de Windows» or
    «Llavero de macOS» (it follows «el»: «en el Llavero de macOS»)."""
    return STORE_NAME_MACOS_ES if osplatform.is_macos() else STORE_NAME_WINDOWS_ES


class CredentialError(Exception):
    """The credential store is unavailable or refused the operation. `msg_es` is user-facing."""

    def __init__(self, msg_es: str):
        super().__init__(msg_es)
        self.msg_es = msg_es


@dataclass(frozen=True, repr=False)
class Credentials:
    username: str
    password: str

    def __repr__(self) -> str:
        return "Credentials(username=***, password=***)"

    __str__ = __repr__


class CredentialStore:
    def __init__(self, service: str = config.KEYRING_SERVICE):
        self.service = service

    def get(self) -> Credentials | None:
        try:
            user = keyring.get_password(self.service, config.KEYRING_ACCOUNT_KEY)
            if not user:
                return None
            password = keyring.get_password(self.service, user)
        except keyring.errors.KeyringError as e:
            raise CredentialError(f"No se pudo leer la cuenta del {store_name_es()} "
                                  f"({type(e).__name__}).") from None
        if not password:
            return None
        return Credentials(user, password)

    def set(self, creds: Credentials) -> None:
        if not creds.username.strip() or not creds.password:
            raise CredentialError("Escribe tu usuario y tu contraseña de Soulseek.")
        try:
            old_user = keyring.get_password(self.service, config.KEYRING_ACCOUNT_KEY)
            keyring.set_password(self.service, creds.username, creds.password)
            keyring.set_password(self.service, config.KEYRING_ACCOUNT_KEY, creds.username)
            if old_user and old_user != creds.username:
                try:
                    keyring.delete_password(self.service, old_user)
                except keyring.errors.PasswordDeleteError:
                    pass
        except keyring.errors.KeyringError as e:
            raise CredentialError(f"No se pudo guardar la cuenta en el {store_name_es()} "
                                  f"({type(e).__name__}).") from None

    def clear(self) -> None:
        try:
            user = keyring.get_password(self.service, config.KEYRING_ACCOUNT_KEY)
            for account in ([user] if user else []) + [config.KEYRING_ACCOUNT_KEY]:
                try:
                    keyring.delete_password(self.service, account)
                except keyring.errors.PasswordDeleteError:
                    pass
        except keyring.errors.KeyringError as e:
            raise CredentialError(f"No se pudo borrar la cuenta del {store_name_es()} "
                                  f"({type(e).__name__}).") from None
