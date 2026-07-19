"""Secret rotation tracking and checking.

Tracks when application secrets were last rotated and identifies stale
secrets that exceed the configured maximum age.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.config import settings
from app.database import admin, execute_query
from app.models import SecretRotationCheck, SecretRotationResponse

logger = logging.getLogger(__name__)


async def record_secret_rotation(secret_name: str, owner: Optional[str] = None) -> None:
    """Record that a secret was rotated.

    Args:
        secret_name: Name/identifier of the rotated secret.
        owner: Optional owner/team responsible for the secret.
    """
    try:
        await execute_query(
            admin.table("secret_rotation_checks")
            .upsert(
                {
                    "secret_name": secret_name,
                    "last_rotated_at": datetime.now(timezone.utc).isoformat(),
                    "owner": owner,
                },
                on_conflict="secret_name",
            )
        )
    except Exception:
        logger.exception("Failed to record secret rotation for %s", secret_name)


async def check_stale_secrets(max_age_days: Optional[int] = None) -> SecretRotationResponse:
    """Check for secrets that haven't been rotated within the allowed age.

    Args:
        max_age_days: Maximum age in days before a secret is considered stale.
            Defaults to SECRET_ROTATION_MAX_AGE_DAYS setting.

    Returns:
        SecretRotationResponse with lists of stale and all checked secrets.
    """
    max_age = max_age_days or settings.SECRET_ROTATION_MAX_AGE_DAYS
    cutoff = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=max_age)

    try:
        result = await execute_query(
            admin.table("secret_rotation_checks")
            .select("*")
            .order("last_rotated_at", desc=False)
        )

        checks = []
        stale_secrets = []
        for row in result.data:
            last_rotated = datetime.fromisoformat(row["last_rotated_at"].replace("Z", "+00:00"))
            days_since = (datetime.now(timezone.utc) - last_rotated).days
            is_stale = last_rotated < cutoff

            check = SecretRotationCheck(
                secret_name=row["secret_name"],
                last_rotated_at=last_rotated,
                owner=row.get("owner"),
                is_stale=is_stale,
                days_since_rotation=days_since,
            )
            checks.append(check)
            if is_stale:
                stale_secrets.append(check)

        return SecretRotationResponse(
            stale_secrets=stale_secrets,
            total_checked=len(checks),
            stale_count=len(stale_secrets),
            max_age_days=max_age,
        )
    except Exception:
        logger.exception("Failed to check secret rotation")
        return SecretRotationResponse(
            stale_secrets=[],
            total_checked=0,
            stale_count=0,
            max_age_days=max_age,
        )
