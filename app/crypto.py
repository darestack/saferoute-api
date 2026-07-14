"""Transparent encryption helpers for sensitive route fields.

Uses ``cryptography`` Fernet symmetric encryption so ``webhook_secret`` is
never stored or transmitted in plaintext. The encryption key is controlled
by the ``ENCRYPTION_KEY`` environment variable.

The helpers tolerate plaintext values during the migration window: if
``ENCRYPTION_KEY`` is missing or decryption fails, the original value is
returned unchanged so the application continues to function while secrets
are being rotated.
"""

from __future__ import annotations
import base64
import hashlib
import json
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


def clear_fernet_cache() -> None:
    """Drop the cached :class:`Fernet` instance.

    Call this after ``ENCRYPTION_KEY`` rotation so the next encryption/decryption
    operation derives and caches a fresh instance. Without this, the old key
    remains cached until process restart.
    """
    global _fernet
    _fernet = None


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

    Raises:
        RuntimeError: If encryption is required (production) but not
            configured. The plaintext fallback is only permitted outside
            production to keep CI and non-prod deploys runnable.
    """
    if plaintext is None:
        return None

    fernet = _get_fernet()
    if fernet is None:
        if settings.is_production:
            raise RuntimeError(
                "ENCRYPTION_KEY is not configured or invalid; "
                "cannot encrypt webhook secret in production"
            )
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

    had_version_prefix = ciphertext.startswith(_VERSION_PREFIX)
    if had_version_prefix:
        ciphertext = ciphertext[len(_VERSION_PREFIX) :]

    fernet = _get_fernet()
    if fernet is None:
        if had_version_prefix:
            raise ValueError(
                "Cannot decrypt webhook secret: encryption is not configured "
                "(missing ENCRYPTION_KEY) but the stored value is encrypted"
            )
        return ciphertext

    try:
        return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "Failed to decrypt webhook secret: invalid encryption key or corrupted data"
        ) from exc
    except Exception:
        logger.exception("Unexpected error decrypting webhook secret")
        raise


def decrypt_webhook_secrets(raw: Optional[str | list[str]]) -> list[str]:
    """Decrypt stored webhook secrets into a list of plaintext values.

    Supports both the legacy single-secret format (a single encrypted
    string) and the new multi-secret format (a JSON array of encrypted
    strings). This enables zero-downtime secret rotation: a route can
    hold both the current and previous secrets simultaneously.

    Args:
        raw: The raw database value. May be ``None``, a single encrypted
            string, or a list of encrypted strings.

    Returns:
        A list of decrypted plaintext secrets. Returns an empty list
        if ``raw`` is ``None`` or empty.
    """
    if not raw:
        return []

    if isinstance(raw, list):
        candidates = raw
    elif isinstance(raw, str):
        candidates = [raw]
    else:
        return []

    secrets: list[str] = []
    for ciphertext in candidates:
        try:
            secret = decrypt_webhook_secret(ciphertext)
            if secret:
                secrets.append(secret)
        except Exception:
            logger.exception("Failed to decrypt webhook secret during rotation")
    return secrets
