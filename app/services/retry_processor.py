import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from app.database import admin, execute_query
from app.config import settings
from app.models import RetryProcessResponse
from app.utils.retry import should_retry, calculate_next_retry, get_retry_window_cutoff
from app.utils.transform import render_template

logger = logging.getLogger(__name__)

_MAX_RETRIES = settings.MAX_RETRIES
_RETRY_BATCH_SIZE = settings.RETRY_BATCH_SIZE
_RETRY_CLAIM_STALE_SECONDS = settings.RETRY_CLAIM_STALE_SECONDS
_MAX_LOG_BODY_BYTES = settings.MAX_LOG_BODY_BYTES


async def reap_stale_retries() -> None:
    """Reset entries stranded in 'retrying' back to 'pending'."""
    reaper_cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=_RETRY_CLAIM_STALE_SECONDS)
    ).isoformat()
    try:
        await execute_query(
            admin.table("webhook_logs")
            .update({"retry_status": "pending"})
            .eq("retry_status", "retrying")
            .lt("updated_at", reaper_cutoff)
        )
    except Exception:
        logger.warning("Retry reaper failed")


def rebuild_retry_body(log_entry: dict[str, Any]) -> bytes:
    """Rebuild the request body from a stored webhook log entry.

    Args:
        log_entry: The webhook log entry containing ``request_body`` and
            ``content_type``.

    Returns:
        Reconstructed request body bytes, or ``b""`` if unavailable.

    Raises:
        ValueError: If the content type cannot be reconstructed.
    """
    stored_body = log_entry.get("request_body", {})
    content_type = log_entry.get("content_type", "")

    if not stored_body:
        return b""

    if "application/json" in content_type or isinstance(stored_body, (dict, list)):
        return json.dumps(stored_body).encode("utf-8")

    if "application/x-www-form-urlencoded" in content_type:
        from urllib.parse import urlencode

        return urlencode(stored_body).encode("utf-8")

    if content_type in (
        "application/xml",
        "text/xml",
        "application/protobuf",
        "application/octet-stream",
    ):
        raise ValueError(f"Cannot reconstruct body for content type: {content_type}")

    return str(stored_body).encode("utf-8")


async def update_retry_outcome(
    log_id: int,
    retry_count: int,
    new_status: str,
    status_code: int,
    next_retry: Optional[str],
    log_entry: dict[str, Any],
    response_body: str,
) -> dict[str, Any]:
    """Update the webhook log with the retry outcome and return a result dict.

    Args:
        log_id: The webhook log entry ID.
        retry_count: The current retry attempt count.
        new_status: The final retry status ("succeeded", "exhausted", etc.).
        status_code: HTTP status from the destination.
        next_retry: ISO timestamp of next retry, or ``None``.
        log_entry: The original webhook log entry.
        response_body: Response body from the destination.

    Returns:
        Outcome dict with ``log_id``, ``retry_count``, ``status_code``, and
        ``outcome`` fields.
    """
    result = await execute_query(
        admin.table("webhook_logs")
        .update(
            {
                "retry_count": retry_count,
                "retry_status": new_status,
                "status_code": status_code,
                "next_retry_at": next_retry,
            }
        )
        .eq("id", log_id)
    )
    if not result.data:
        logger.warning("Retry status update failed for log_id=%s", log_id)

    outcome: dict[str, Any] = {
        "log_id": log_id,
        "retry_count": retry_count,
        "status_code": status_code,
        "outcome": new_status,
    }

    if new_status == "exhausted":
        failure_result = await execute_query(
            admin.table("webhook_failures").insert(
                {
                    "route_id": log_entry["route_id"],
                    "webhook_log_id": log_id,
                    "status_code": status_code,
                    "response_body": response_body[:_MAX_LOG_BODY_BYTES]
                    if response_body
                    else None,
                    "ip_address": log_entry.get("ip_address"),
                    "user_agent": log_entry.get("user_agent"),
                    "retry_count": retry_count,
                    "max_retries": _MAX_RETRIES,
                }
            )
        )
        if not failure_result.data:
            logger.warning("Dead-letter insert failed for log_id=%s", log_id)

    return outcome


async def process_pending_retries(forward_payload_fn) -> dict[str, Any]:
    """Process pending webhook delivery retries."""
    now = datetime.now(timezone.utc).isoformat()

    await reap_stale_retries()

    pending = await execute_query(
        admin.table("webhook_logs")
        .select(
            "*, routes!inner(destination_url, method, headers, "
            "transform_headers, transform_body_template)"
        )
        .eq("retry_status", "pending")
        .lte("next_retry_at", now)
        .lt("retry_count", _MAX_RETRIES)
        .gte("created_at", get_retry_window_cutoff())
        .limit(_RETRY_BATCH_SIZE)
    )

    results = []

    for log_entry in pending.data or []:
        route_info = log_entry.get("routes", {})
        log_id = log_entry["id"]
        retry_count = log_entry["retry_count"] + 1
        destination_url = route_info.get("destination_url", "")

        if not destination_url:
            new_status = "exhausted"
            next_retry = None
            result = await execute_query(
                admin.table("webhook_logs")
                .update(
                    {
                        "retry_count": retry_count,
                        "retry_status": new_status,
                        "next_retry_at": next_retry,
                    }
                )
                .eq("id", log_id)
            )
            if not result.data:
                logger.warning(
                    "Retry mark-exhausted update failed for log_id=%s", log_id
                )
            results.append(
                {
                    "log_id": log_id,
                    "retry_count": retry_count,
                    "status_code": 0,
                    "outcome": new_status,
                }
            )
            continue

        claim_result = await execute_query(
            admin.table("webhook_logs")
            .update({"retry_status": "retrying"})
            .eq("id", log_id)
            .eq("retry_status", "pending")
        )
        if not claim_result.data:
            logger.warning("Retry already claimed for log_id=%s, skipping", log_id)
            continue

        try:
            body = rebuild_retry_body(log_entry)
        except ValueError:
            outcome = await update_retry_outcome(
                log_id, retry_count, "exhausted", 0, None, log_entry, ""
            )
            results.append(outcome)
            continue

        forward_body = body
        transform_template = route_info.get("transform_body_template")
        stored_body = log_entry.get("request_body", {})
        if transform_template and isinstance(stored_body, dict):
            rendered = render_template(transform_template, stored_body)
            forward_body = rendered.encode("utf-8")

        outbound_headers = dict(route_info.get("headers", {}))
        transform_headers = route_info.get("transform_headers", {})
        if transform_headers:
            outbound_headers.update(transform_headers)

        status_code, response_body, response_headers = await forward_payload_fn(
            method=route_info.get("method", "POST"),
            url=destination_url,
            body=forward_body,
            headers=outbound_headers,
        )

        if 200 <= status_code < 300:
            new_status = "succeeded"
            next_retry = None
        elif should_retry(status_code) and retry_count < _MAX_RETRIES:
            new_status = "pending"
            next_retry = calculate_next_retry(retry_count)
        else:
            new_status = "exhausted"
            next_retry = None

        outcome = await update_retry_outcome(
            log_id,
            retry_count,
            new_status,
            status_code,
            next_retry,
            log_entry,
            response_body,
        )
        results.append(outcome)

    return RetryProcessResponse(processed=len(results), results=results)
