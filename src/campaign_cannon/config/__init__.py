"""Configuration — settings and encrypted credential management."""

from campaign_cannon.config.credentials import (
    CredentialError,
    decrypt_credentials,
    encrypt_credentials,
    get_credential,
    store_credential,
)
from campaign_cannon.config.settings import Settings, get_settings

__all__ = [
    "CredentialError",
    "Settings",
    "decrypt_credentials",
    "encrypt_credentials",
    "get_credential",
    "get_settings",
    "store_credential",
]
