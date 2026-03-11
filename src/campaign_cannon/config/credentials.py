"""Encrypted credential store for platform API keys.

Uses Fernet symmetric encryption (AES-128-CBC under the hood) keyed
by the CANNON_MASTER_KEY environment variable.
"""

from __future__ import annotations

import json

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from campaign_cannon.config.settings import get_settings
from campaign_cannon.db.models import Platform, PlatformCredential


class CredentialError(Exception):
    """Raised when credential encryption or decryption fails."""


def _get_fernet() -> Fernet:
    """Build a Fernet cipher from the configured master key."""
    key = get_settings().master_key
    if not key:
        raise CredentialError("CANNON_MASTER_KEY is not set — cannot encrypt/decrypt credentials")
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, Exception) as exc:
        raise CredentialError(f"Invalid CANNON_MASTER_KEY: {exc}") from exc


def encrypt_credentials(cred_dict: dict) -> str:
    """Serialize *cred_dict* to JSON and encrypt with Fernet.

    Returns the encrypted blob as a UTF-8 string.
    """
    fernet = _get_fernet()
    payload = json.dumps(cred_dict).encode("utf-8")
    return fernet.encrypt(payload).decode("utf-8")


def decrypt_credentials(encrypted_blob: str) -> dict:
    """Decrypt a Fernet-encrypted blob and return the original dict."""
    fernet = _get_fernet()
    try:
        decrypted = fernet.decrypt(encrypted_blob.encode("utf-8"))
        return json.loads(decrypted)
    except InvalidToken as exc:
        raise CredentialError(
            "Failed to decrypt credentials — wrong key or corrupted data"
        ) from exc


def store_credential(
    session: Session,
    platform: Platform,
    cred_dict: dict,
) -> PlatformCredential:
    """Encrypt *cred_dict* and persist as a PlatformCredential row.

    Deactivates any previously-active credential for the same platform.
    """
    # Deactivate existing active credentials for this platform
    session.query(PlatformCredential).filter(
        PlatformCredential.platform == platform,
        PlatformCredential.is_active.is_(True),
    ).update({"is_active": False})

    encrypted = encrypt_credentials(cred_dict)
    credential = PlatformCredential(
        platform=platform,
        encrypted_credentials=encrypted,
        is_active=True,
    )
    session.add(credential)
    session.flush()
    return credential


def get_credential(session: Session, platform: Platform) -> dict:
    """Fetch the active credential for *platform* and return decrypted dict.

    Raises ``CredentialError`` if no active credential exists.
    """
    row = (
        session.query(PlatformCredential)
        .filter(
            PlatformCredential.platform == platform,
            PlatformCredential.is_active.is_(True),
        )
        .first()
    )
    if row is None:
        raise CredentialError(f"No active credential found for {platform.value}")
    return decrypt_credentials(row.encrypted_credentials)
