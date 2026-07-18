"""Tests for repository layer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.repositories import SupabaseRouteRepository, route_repository


class TestSupabaseRouteRepository:
    """Tests for SupabaseRouteRepository."""

    @pytest.fixture
    def repo(self):
        return SupabaseRouteRepository()

    @pytest.mark.asyncio
    async def test_find_active_by_slug_returns_route(self, repo):
        mock_result = MagicMock()
        mock_result.data = [{"id": "r1", "slug": "test", "is_active": True}]

        with patch("app.repositories.execute_query", return_value=mock_result):
            route = await repo.find_active_by_slug("test")
            assert route == {"id": "r1", "slug": "test", "is_active": True}

    @pytest.mark.asyncio
    async def test_find_active_by_slug_returns_none_when_not_found(self, repo):
        mock_result = MagicMock()
        mock_result.data = []

        with patch("app.repositories.execute_query", return_value=mock_result):
            route = await repo.find_active_by_slug("missing")
            assert route is None

    @pytest.mark.asyncio
    async def test_find_by_id_returns_route(self, repo):
        mock_result = MagicMock()
        mock_result.data = [{"id": "r1", "user_id": "u1"}]

        with patch("app.repositories.execute_query", return_value=mock_result):
            route = await repo.find_by_id("r1", "u1")
            assert route == {"id": "r1", "user_id": "u1"}

    @pytest.mark.asyncio
    async def test_create_returns_created_route(self, repo):
        mock_result = MagicMock()
        mock_result.data = [{"id": "r1", "slug": "test"}]

        with patch("app.repositories.execute_query", return_value=mock_result):
            route = await repo.create({"slug": "test"})
            assert route == {"id": "r1", "slug": "test"}

    @pytest.mark.asyncio
    async def test_create_raises_on_failure(self, repo):
        mock_result = MagicMock()
        mock_result.data = []

        with patch("app.repositories.execute_query", return_value=mock_result):
            with pytest.raises(RuntimeError, match="Failed to create route"):
                await repo.create({"slug": "test"})

    @pytest.mark.asyncio
    async def test_update_returns_updated_route(self, repo):
        mock_result = MagicMock()
        mock_result.data = [{"id": "r1", "name": "Updated"}]

        with patch("app.repositories.execute_query", return_value=mock_result):
            route = await repo.update("r1", "u1", {"name": "Updated"})
            assert route == {"id": "r1", "name": "Updated"}

    @pytest.mark.asyncio
    async def test_delete_returns_true_when_deleted(self, repo):
        mock_result = MagicMock()
        mock_result.data = [{"id": "r1"}]

        with patch("app.repositories.execute_query", return_value=mock_result):
            result = await repo.delete("r1", "u1")
            assert result is True

    @pytest.mark.asyncio
    async def test_delete_returns_false_when_not_found(self, repo):
        mock_result = MagicMock()
        mock_result.data = []

        with patch("app.repositories.execute_query", return_value=mock_result):
            result = await repo.delete("missing", "u1")
            assert result is False

    @pytest.mark.asyncio
    async def test_list_by_user_returns_routes(self, repo):
        mock_result = MagicMock()
        mock_result.data = [
            {"id": "r1", "user_id": "u1"},
            {"id": "r2", "user_id": "u1"},
        ]

        with patch("app.repositories.execute_query", return_value=mock_result):
            routes = await repo.list_by_user("u1", 10, 0)
            assert len(routes) == 2
            assert routes[0]["id"] == "r1"

    @pytest.mark.asyncio
    async def test_list_by_user_returns_empty_when_no_routes(self, repo):
        mock_result = MagicMock()
        mock_result.data = []

        with patch("app.repositories.execute_query", return_value=mock_result):
            routes = await repo.list_by_user("u1", 10, 0)
            assert routes == []

    @pytest.mark.asyncio
    async def test_slug_exists_for_other_route_true(self, repo):
        mock_result = MagicMock()
        mock_result.data = [{"id": "r2"}]

        with patch("app.repositories.execute_query", return_value=mock_result):
            exists = await repo.slug_exists_for_other_route("test", "r1")
            assert exists is True

    @pytest.mark.asyncio
    async def test_slug_exists_for_other_route_false(self, repo):
        mock_result = MagicMock()
        mock_result.data = []

        with patch("app.repositories.execute_query", return_value=mock_result):
            exists = await repo.slug_exists_for_other_route("test", "r1")
            assert exists is False


class TestGlobalRouteRepository:
    """Tests for the global route_repository instance."""

    def test_route_repository_is_supabase_instance(self):
        assert isinstance(route_repository, SupabaseRouteRepository)
