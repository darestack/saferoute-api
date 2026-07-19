"""Security event audit logging.

Provides a lightweight helper to insert audit log entries into the
``audit_logs`` table. All calls are fire-and-forget to avoid adding
latency to the hot path; failures are logged but never raise.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.database import admin, execute_query

logger = logging.getLogger(__name__)


async def log_audit_event(
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Insert an audit log entry.

    Args:
        action: The event type (e.g. ``api_key.rotated``).
        resource_type: The kind of resource affected (e.g. ``route``).
        resource_id: Optional identifier of the affected resource.
        user_id: Optional UUID of the acting user.
        ip_address: Optional client IP address.
        user_agent: Optional user-agent string.
        metadata: Optional additional context as a JSON-serializable dict.
    """
    try:
        await execute_query(
            admin.table("audit_logs")
            .insert(
                {
                    "user_id": user_id,
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "ip_address": ip_address,
                    "user_agent": user_agent,
                    "metadata": metadata or {},
                }
            )
        )
    except Exception:
        logger.exception("Failed to write audit log for action=%s", action)
