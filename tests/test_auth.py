"""Tests for authentication helpers and user caching."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.models import User
from app.routes.auth import (
    _cache_user,
    _fetch_and_cache_user,
    _get_cached_user,
)


class TestUserCache:
    """Tests for user lookup caching."""

    def test_cache_hit_returns_user(self):
        user = User(
            id="user-1",
            email="test@example.com",
            full_name="Test User",
            created_at="2026-01-01T00:00:00Z",
        )
        _cache_user(user)
        cached = asyncio.run(_get_cached_user("user-1"))
        assert cached is not None
        assert cached.id == "user-1"
        assert cached.email == "test@example.com"

    def test_cache_miss_returns_none(self):
        cached = asyncio.run(_get_cached_user("nonexistent"))
        assert cached is None

    def test_fetch_and_cache_user_stores_result(self):
        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_user.email = "cached@example.com"
        mock_user.full_name = "Cached User"
        mock_user.created_at = "2026-01-01T00:00:00Z"

        with patch("app.routes.auth.admin") as mock_admin:
            mock_admin.auth.admin.get_user_by_id.return_value = MagicMock(user=mock_user)

            user = asyncio.run(_fetch_and_cache_user("user-123"))
            assert user.id == "user-123"
            assert user.email == "cached@example.com"

            # Verify it was cached
            cached = asyncio.run(_get_cached_user("user-123"))
            assert cached is not None
            assert cached.id == "user-123"

    def test_fetch_and_cache_user_raises_on_missing(self):
        with patch("app.routes.auth.admin") as mock_admin:
            mock_admin.auth.admin.get_user_by_id.return_value = MagicMock(user=None)

            with pytest.raises(Exception):  # HTTPException
                asyncio.run(_fetch_and_cache_user("missing-user"))
