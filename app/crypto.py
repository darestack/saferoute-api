"""Transparent encryption helpers for sensitive route fields.

Uses ``cryptography`` Fernet symmetric encryption so ``webhook_secret`` is
never stored or transmitted in plaintext. The encryption key is controlled
by the ``ENCRYPTION_KEY`` environment variable.

The helpers tolerate plaintext values during the migration window: if
``ENCRYPTION_KEY`` is missing or decryption fails, the original value is
returned unchanged so the application continues to function while secrets
are being rotated.
"""

import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)

_FALLBACK_PREFIX = "safe_plain:"
_VERSION_PREFIX = "v1:"


def _derive_key(raw_key: str) -> Optional[bytes]:
    """Derive a 32-byte URL-safe base64 key from the raw setting value.

    Args:
        raw_key: The ``ENCRYPTION_KEY`` environment value.

    Returns:
        A base64-encoded 32-byte key suitable for :class:`Fernet`, or
        ``None`` if the input is empty or invalid.
    """
    if not raw_key:
        return None

    if raw_key.startswith("base64:"):
        candidate = raw_key[7:]
        try:
            decoded = base64.urlsafe_b64decode(candidate)
            if len(decoded) == 32:
                return candidate.encode("utf-8")
        except Exception:
            pass
        return None

    digest = hashlib.sha256(raw_key.encode("utf-8")).digest()
    candidate = base64.urlsafe_b64encode(digest).decode("utf-8")

    try:
        Fernet(candidate.encode("utf-8"))
        return candidate.encode("utf-8")
    except Exception:
        logger.exception("Failed to derive encryption key")
        return None


_fernet: Optional[Fernet] = None


def _get_fernet() -> Optional[Fernet]:
    """Return a cached :class:`Fernet` instance or ``None``."""
    global _fernet

    if _fernet is not None:
        return _fernet

    key = _derive_key(settings.ENCRYPTION_KEY)
    if key is None:
        return None

    _fernet = Fernet(key)
    return _fernet


def encrypt_webhook_secret(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a webhook secret for storage.

    Supports key rotation via versioned prefix. Future versions can decrypt
    older versions during rotation windows.

    Args:
        plaintext: The plaintext secret, or ``None``.

    Returns:
        The encrypted secret as a string, or ``None`` if the input was
        ``None``. If encryption is not configured, returns the original
        value prefixed with ``safe_plain:`` so callers can distinguish
        encrypted from plaintext data.
    """
    if plaintext is None:
        return None

    fernet = _get_fernet()
    if fernet is None:
        return f"{_FALLBACK_PREFIX}{plaintext}"

    encrypted = fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")
    return f"{_VERSION_PREFIX}{encrypted}"


def decrypt_webhook_secret(ciphertext: Optional[str]) -> Optional[str]:
    """Decrypt a stored webhook secret.

    Handles versioned encrypted values, plaintext fallback prefix, and
    raw ciphertext when encryption is not configured.

    Args:
        ciphertext: The encrypted secret from the database, or ``None``.

    Returns:
        The plaintext secret, or ``None`` if the input was ``None``.
        Falls back to returning the value unchanged if decryption fails
        or encryption is not configured.
    """
    if ciphertext is None:
        return None

    if ciphertext.startswith(_FALLBACK_PREFIX):
        return ciphertext[len(_FALLBACK_PREFIX) :]

    if ciphertext.startswith(_VERSION_PREFIX):
        ciphertext = ciphertext[len(_VERSION_PREFIX) :]

    fernet = _get_fernet()
    if fernet is None:
        return ciphertext

    try:
        return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.warning("Failed to decrypt webhook secret; returning raw value")
        return ciphertext
    except Exception:
        logger.exception("Unexpected error decrypting webhook secret")
        return ciphertext
