"""Repository layer for data access abstraction.

Provides interfaces for database operations, enabling testability and
future backend swaps without changing route handlers.
"""

from __future__ import annotations

from typing import Any, Optional, cast

from app.database import admin, execute_query


class RouteRepository:
    """Interface for route data access."""

    async def find_active_by_slug(self, slug: str) -> Optional[dict[str, Any]]:
        raise NotImplementedError

    async def find_by_id(self, route_id: str, user_id: str) -> Optional[dict[str, Any]]:
        raise NotImplementedError

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    async def update(self, route_id: str, user_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    async def delete(self, route_id: str, user_id: str) -> bool:
        raise NotImplementedError

    async def list_by_user(self, user_id: str, limit: int, offset: int) -> list[dict[str, Any]]:
        raise NotImplementedError



    async def slug_exists_for_other_route(self, slug: str, route_id: str) -> bool:
        """Check if a slug is already used by a different route."""
        raise NotImplementedError


class SupabaseRouteRepository(RouteRepository):
    """Supabase implementation of RouteRepository."""

    async def find_active_by_slug(self, slug: str) -> Optional[dict[str, Any]]:
        result = await execute_query(
            admin.table("routes")
            .select("*")
            .eq("slug", slug)
            .eq("is_active", True)
        )
        if result.data:
            return cast(dict[str, Any], result.data[0])
        return None

    async def find_by_id(self, route_id: str, user_id: str) -> Optional[dict[str, Any]]:
        result = await execute_query(
            admin.table("routes")
            .select("*")
            .eq("id", route_id)
            .eq("user_id", user_id)
        )
        if result.data:
            return cast(dict[str, Any], result.data[0])
        return None

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        result = await execute_query(admin.table("routes").insert(data))
        if not result.data:
            raise RuntimeError("Failed to create route")
        return cast(dict[str, Any], result.data[0])

    async def update(self, route_id: str, user_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        result = await execute_query(
            admin.table("routes")
            .update(updates)
            .eq("id", route_id)
            .eq("user_id", user_id)
        )
        if not result.data:
            raise RuntimeError("Route not found")
        return cast(dict[str, Any], result.data[0])

    async def delete(self, route_id: str, user_id: str) -> bool:
        result = await execute_query(
            admin.table("routes")
            .delete()
            .eq("id", route_id)
            .eq("user_id", user_id)
        )
        return bool(result.data)

    async def list_by_user(self, user_id: str, limit: int, offset: int) -> list[dict[str, Any]]:
        result = await execute_query(
            admin.table("routes")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=False)
            .range(offset, offset + limit - 1)
        )
        return result.data or []



    async def slug_exists_for_other_route(self, slug: str, route_id: str) -> bool:
        """Check if a slug is already used by a different route."""
        result = await execute_query(
            admin.table("routes")
            .select("id")
            .eq("slug", slug)
            .neq("id", route_id)
        )
        return bool(result.data)


# Global repository instance.
route_repository = SupabaseRouteRepository()
