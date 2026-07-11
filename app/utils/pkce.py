"""PKCE (Proof Key for Code Exchange) utilities for OAuth flows.

Provides reusable PKCE generation for OAuth authentication flows.
"""

from __future__ import annotations
import base64
import hashlib
import logging
import secrets
from typing import Optional

from supabase import Client

logger = logging.getLogger(__name__)

PKCE_CODE_VERIFIER_LENGTH = 64


def generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code verifier and code challenge.

    Returns:
        A tuple of ``(code_verifier, code_challenge)``.
    """
    code_verifier = secrets.token_urlsafe(PKCE_CODE_VERIFIER_LENGTH)
    hashed = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(hashed).rstrip(b"=").decode("utf-8")
    return code_verifier, code_challenge


def store_pkce_verifier(
    admin_client: "Client", code_challenge: str, code_verifier: str
) -> None:
    """Persist a PKCE verifier to the ``pkce_verifiers`` table.

    This replaces the in-memory dict so the verifier survives across
    serverless invocations and multi-worker deployments.

    Args:
        admin_client: The Supabase admin client.
        code_challenge: The S256 challenge sent to the OAuth provider.
        code_verifier: The corresponding verifier to store.
    """
    try:
        admin_client.table("pkce_verifiers").insert(
            {
                "code_challenge": code_challenge,
                "code_verifier": code_verifier,
            }
        ).execute()
    except Exception:
        logger.exception("Failed to store PKCE verifier")
        raise


def retrieve_and_delete_pkce_verifier(
    admin_client: "Client", code_challenge: str
) -> Optional[str]:
    """Atomically retrieve and delete a PKCE verifier from the database.

    Uses the ``consume_pkce_verifier`` SQL function to prevent reuse races.

    Args:
        admin_client: The Supabase admin client.
        code_challenge: The S256 challenge to look up.

    Returns:
        The code verifier string, or ``None`` if not found.
    """
    try:
        result = admin_client.rpc(
            "consume_pkce_verifier", {"p_code_challenge": code_challenge}
        ).execute()

        if result.data:
            return result.data[0]["code_verifier"]  # type: ignore[return-value, index, call-overload]
    except Exception:
        logger.exception("Failed to retrieve PKCE verifier")

    return None
