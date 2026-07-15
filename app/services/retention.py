import logging
from typing import Optional

from app.database import admin, execute_query
from app.config import settings
from app.models import CleanupResponse

logger = logging.getLogger(__name__)


async def run_cleanup(keep_days: int | None = None) -> CleanupResponse:
    """Run periodic retention cleanup to bound database growth.

    Prunes expired PKCE verifiers, idempotency cache entries, rate-limit
    windows, and old webhook delivery logs (plus their dead-letter rows).

    Args:
        keep_days: How many days of webhook delivery history to retain.
            Clamped to the inclusive range [1, 365].

    Returns:
        JSON-serializable dict with cleanup stats.
    """
    # Fail safe on retention: never delete everything, never keep forever.
    keep_days = max(1, min(int(keep_days or settings.RETENTION_DAYS), 365))

    async def _safe_count_rpc(fn_name: str, params: Optional[dict] = None) -> int:
        """Invoke a SQL cleanup function that returns a row count, tolerating missing functions."""
        try:
            result = await execute_query(admin.rpc(fn_name, params or {}))
            if isinstance(result.data, list) and result.data:
                value = result.data[0]
                if isinstance(value, dict):
                    # Prefer known count column names; fall back to first value.
                    for key in ("webhook_logs_removed", "count", "removed", "total"):
                        if key in value:
                            return int(value[key])
                    return int(next(iter(value.values())))
                if isinstance(value, (int, float)):
                    return int(value)
            return 0
        except Exception:
            logger.warning("Cleanup step %s failed", fn_name)
            return 0

    async def _safe_void_rpc(fn_name: str, params: Optional[dict] = None) -> bool:
        """Invoke a SQL cleanup function that returns void, tolerating missing functions."""
        try:
            await execute_query(admin.rpc(fn_name, params or {}))
            return True
        except Exception:
            logger.warning("Cleanup step %s failed", fn_name)
            return False

    webhook_logs_removed = await _safe_count_rpc(
        "cleanup_webhook_logs", {"p_keep_days": keep_days}
    )
    rate_limits_cleaned_count = await _safe_void_rpc("cleanup_rate_limits")
    pkce_verifiers_cleaned_count = await _safe_void_rpc("cleanup_pkce_verifiers")
    idempotency_cache_cleaned_count = await _safe_void_rpc("cleanup_idempotency_cache")

    return CleanupResponse(
        webhook_logs_removed=webhook_logs_removed,
        rate_limits_cleaned=rate_limits_cleaned_count,
        pkce_verifiers_cleaned=pkce_verifiers_cleaned_count,
        idempotency_cache_cleaned=idempotency_cache_cleaned_count,
        keep_days=keep_days,
    )
