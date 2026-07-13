"""Reusable helpers for route rows and route ownership checks."""

from __future__ import annotations

from typing import Any, Optional, cast

from fastapi import HTTPException, status


def route_to_response(
    route: dict[str, Any], api_key: Optional[str] = None
) -> dict[str, Any]:
    """Build a public API response dictionary from a raw route row.

    Sensitive columns such as ``api_key_hash`` and encrypted webhook secrets are
    intentionally omitted. Derived booleans communicate whether optional
    security or transform features are configured without exposing secret
    values.
    """
    response: dict[str, Any] = {
        "id": route["id"],
        "user_id": route["user_id"],
        "name": route["name"],
        "slug": route["slug"],
        "destination_url": route["destination_url"],
        "method": route["method"],
        "headers": route["headers"],
        "is_active": route["is_active"],
        "requests_count": route["requests_count"],
        "last_used_at": route.get("last_used_at"),
        "api_key_prefix": route.get("api_key_prefix"),
        "rate_limit": route.get("rate_limit", 30),
        "has_webhook_secret": bool(route.get("webhook_secret")),
        "has_transform": bool(
            route.get("transform_body_template") or route.get("transform_headers")
        ),
        "transform_headers": route.get("transform_headers") or {},
        "transform_body_template": route.get("transform_body_template"),
        "created_at": route["created_at"],
        "updated_at": route["updated_at"],
    }
    if api_key is not None:
        response["api_key"] = api_key
    return response


async def get_owned_route_or_404(
    admin_client: Any,
    route_id: str,
    user_id: str,
    columns: str = "*",
) -> dict[str, Any]:
    """Return a route owned by a user or raise a standard 404 response."""
    from app.database import execute_query

    result = await execute_query(
        admin_client.table("routes")
        .select(columns)
        .eq("id", route_id)
        .eq("user_id", user_id)
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route not found",
        )

    return cast(dict[str, Any], result.data[0])


async def assert_owned_route_exists(admin_client: Any, route_id: str, user_id: str) -> None:
    """Raise 404 unless a route exists and belongs to the user."""
    await get_owned_route_or_404(admin_client, route_id, user_id, columns="id")
