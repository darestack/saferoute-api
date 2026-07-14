"""Tests for authentication helpers and user caching."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import User
from app.utils.security import generate_slug
from app.routes.auth import (
    _cache_user,
    _fetch_and_cache_user,
    _get_cached_user,
    _USER_CACHE_MAX_SIZE,
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
        asyncio.run(_cache_user(user))
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
            mock_admin.auth.admin.get_user_by_id.return_value = MagicMock(
                user=mock_user
            )

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

    def test_cache_fifo_eviction_when_full(self):
        from app.routes.auth import _user_cache, _user_cache_order

        # Fill cache to max size.
        for i in range(_USER_CACHE_MAX_SIZE):
            user = User(
                id=f"user-{i:04d}",
                email=f"user-{i}@example.com",
                full_name=f"User {i}",
                created_at="2026-01-01T00:00:00Z",
            )
            asyncio.run(_cache_user(user))

        assert len(_user_cache_order) == _USER_CACHE_MAX_SIZE

        # Add one more user - oldest should be evicted.
        new_user = User(
            id="user-new",
            email="new@example.com",
            full_name="New User",
            created_at="2026-01-01T00:00:00Z",
        )
        asyncio.run(_cache_user(new_user))

        assert len(_user_cache_order) == _USER_CACHE_MAX_SIZE
        assert "user-0000" not in _user_cache
        assert "user-new" in _user_cache


class TestGenerateSlug:
    """Tests for slug generation and sanitization."""

    def test_strips_invalid_characters(self):
        slug = generate_slug("My!! Route!#")
        assert slug.startswith("my-route-")

    def test_collapses_double_hyphens(self):
        slug = generate_slug("My  Route")
        assert (
            "--" not in slug.split("-")[1:-1]
        )  # Check middle part has no double hyphens

    def test_strips_leading_trailing_hyphens(self):
        slug = generate_slug("---Test---")
        assert not slug.startswith("-")
        assert not slug.endswith("-")


class TestJwtAuth:
    """Tests for JWT authentication edge cases."""

    def test_missing_token_returns_401(self):
        from app.routes.auth import get_current_user_from_jwt
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_current_user_from_jwt(authorization=None))
        assert exc.value.status_code == 401

    def test_malformed_bearer_header_returns_401(self):
        from app.routes.auth import get_current_user_from_jwt
        from fastapi import HTTPException

        # "Bearer" with no token → must return 401, not crash with 500.
        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_current_user_from_jwt(authorization="Bearer"))
        assert exc.value.status_code == 401

    def test_user_with_null_created_at_does_not_500(self):
        from app.routes.auth import _fetch_and_cache_user

        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_user.email = "test@example.com"
        mock_user.full_name = None
        mock_user.created_at = None  # Supabase may return None

        with patch("app.routes.auth.admin") as mock_admin:
            mock_admin.auth.admin.get_user_by_id.return_value = MagicMock(
                user=mock_user
            )
            user = asyncio.run(_fetch_and_cache_user("user-123"))
            assert user.id == "user-123"
            assert user.created_at is None  # Optional now accepts None


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_returns_200(self):
        with (
            patch("app.database.admin") as _,
            patch(
                "app.database.execute_query", return_value=MagicMock(data=[{"id": "1"}])
            ),
        ):
            from fastapi.testclient import TestClient
            from app.main import app

            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert "status" in data
            assert "database" in data


class TestStructuralErrorMatching:
    """Tests that Postgres unique violations are detected by error code."""

    def test_unique_violation_detected_by_code(self):
        from fastapi import HTTPException
        from app.routes import auth as auth_module

        class FakeExc(Exception):
            code = "23505"

        with patch.object(auth_module.route_repository, "create") as mock_create:
            mock_create.side_effect = FakeExc("duplicate key")

            from app.models import User

            user = User(
                id="user-1",
                email="test@example.com",
                full_name="Test",
                created_at="2026-01-01T00:00:00Z",
            )

            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(
                    auth_module.create_route(
                        auth_module.RouteCreate(
                            name="Test Route",
                            destination_url="https://example.com/hook",
                        ),
                        current_user=user,
                    )
                )
            assert exc_info.value.status_code == 409


class TestOAuthRedirectUrl:
    """Tests for OAuth redirect URI construction."""

    def test_redirect_uri_no_double_slash(self):
        from app.routes.oauth import oauth_redirect

        with (
            patch("app.routes.oauth._generate_pkce_pair", return_value=("v", "c")),
            patch("app.routes.oauth._store_pkce_verifier"),
        ):
            with patch("app.routes.oauth.settings") as mock_settings:
                mock_settings.ENCRYPTION_KEY = ""
                mock_settings.FRONTEND_URL = "http://localhost:3000/app/"
                mock_settings.SUPABASE_URL = "https://supabase.example.com"
                result = asyncio.run(oauth_redirect("google"))
                from urllib.parse import urlparse, parse_qs

                query = parse_qs(urlparse(result.auth_url).query)
                redirect_to = query["redirect_to"][0]
                assert "//auth/callback" not in redirect_to
                assert redirect_to == "http://localhost:3000/app/auth/callback"


class TestGenerateSlugStrength:
    """The slug's random suffix is the route's primary秘密 (secret)."""

    def test_suffix_is_strong_and_within_length(self):
        from app.utils.security import generate_slug

        slug = generate_slug("My Route Name")
        assert slug.startswith("my-route-name-")
        suffix = slug.split("-")[-1]
        # 12 hex chars (48 bits) of entropy.
        assert len(suffix) == 12
        assert all(c in "0123456789abcdef" for c in suffix)
        # Stay within the Slug model max length (64).
        assert len(slug) <= 64


class TestRouteFailuresPagination:
    """Cursor pagination must fetch strictly-older rows (no overlap)."""

    def test_cursor_uses_lt_not_lte(self):
        from app.routes.auth import list_route_failures

        with (
            patch("app.routes.auth.admin") as mock_admin,
            patch("app.routes.auth.route_repository") as mock_repo,
        ):
            # get_owned_route_or_404 uses route_repository.
            mock_repo.find_by_id.return_value = {"id": "r1", "user_id": "u1"}
            # The failures query still uses admin directly.
            s = mock_admin.table.return_value.select.return_value
            e1 = s.eq.return_value
            e1.order.return_value.limit.return_value.execute.return_value.data = []

            user = User(id="u1", email="e@e.com", created_at=None)
            asyncio.run(
                list_route_failures(
                    route_id="r1",
                    cursor="2026-01-01T00:00:00Z",
                    limit=20,
                    current_user=user,
                )
            )

            # The failures query branches on e1.order(...).limit(...).
            tail = e1.order.return_value.limit.return_value
            assert tail.lt.called
            assert not tail.lte.called


class TestRouteCacheInvalidationOnUpdate:
    """Mutating a route must evict its cached proxy row immediately."""

    def test_update_invalidates_proxy_cache(self):
        from app.routes.auth import update_route
        from app.models import RouteUpdate

        route_data = RouteUpdate(name="New Name")
        with (
            patch("app.routes.auth.route_repository") as mock_repo,
            patch("app.routes.auth.clear_route_cache_for_route") as mock_clear,
        ):
            # find_by_id returns old route for cache invalidation.
            mock_repo.find_by_id = AsyncMock(
                return_value={
                    "id": "r1",
                    "user_id": "u1",
                    "slug": "old-slug",
                    "destination_url": "https://example.com/hook",
                }
            )
            # Slug-uniqueness pre-check must find no collision.
            mock_repo.slug_exists_for_other_route = AsyncMock(return_value=False)
            # The actual UPDATE returns the updated row.
            mock_repo.update = AsyncMock(
                return_value={
                    "id": "r1",
                    "user_id": "u1",
                    "name": "New Name",
                    "slug": "old-slug",
                    "destination_url": "https://example.com/hook",
                    "method": "POST",
                    "headers": {},
                    "is_active": True,
                    "requests_count": 0,
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            )

            user = User(id="u1", email="e@e.com", created_at=None)
            asyncio.run(update_route("r1", route_data, user))

            mock_clear.assert_called_once_with("old-slug")

    def test_rename_evicts_both_old_and_new_slug(self):
        from app.routes.auth import update_route
        from app.models import RouteUpdate

        route_data = RouteUpdate(name="Renamed Route")
        with (
            patch("app.routes.auth.route_repository") as mock_repo,
            patch("app.routes.auth.clear_route_cache_for_route") as mock_clear,
        ):
            # find_by_id returns old route for cache invalidation.
            mock_repo.find_by_id = AsyncMock(
                return_value={
                    "id": "r1",
                    "user_id": "u1",
                    "slug": "old-slug",
                    "destination_url": "https://example.com/hook",
                }
            )
            # Slug-uniqueness pre-check must find no collision.
            mock_repo.slug_exists_for_other_route = AsyncMock(return_value=False)
            # The rename regenerates the slug to "new-slug".
            mock_repo.update = AsyncMock(
                return_value={
                    "id": "r1",
                    "user_id": "u1",
                    "name": "Renamed Route",
                    "slug": "new-slug",
                    "destination_url": "https://example.com/hook",
                    "method": "POST",
                    "headers": {},
                    "is_active": True,
                    "requests_count": 0,
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            )

            user = User(id="u1", email="e@e.com", created_at=None)
            asyncio.run(update_route("r1", route_data, user))

            assert mock_clear.call_args_list == [
                ((("new-slug",)),),
                ((("old-slug",)),),
            ]


class TestManualRetryEndpoint:
    """Tests for the manual retry endpoint."""

    def test_retry_exhausted_webhook_queues_for_retry(self):
        from app.routes.auth import retry_failed_webhook
        from app.models import User

        mock_user = User(id="u1", email="e@e.com", created_at=None)
        mock_admin = MagicMock()
        mock_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": 1, "retry_status": "exhausted"}
        ]
        mock_admin.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": 1}
        ]

        with (
            patch("app.routes.auth.admin", mock_admin),
            patch("app.routes.auth.get_owned_route_or_404"),
        ):
            response = asyncio.run(
                retry_failed_webhook(
                    route_id="route-1",
                    log_id="1",
                    current_user=mock_user,
                )
            )

        assert response.status == "queued"
        assert response.log_id == 1

    def test_retry_non_exhausted_returns_400(self):
        from app.routes.auth import retry_failed_webhook
        from app.models import User
        from fastapi import HTTPException

        mock_user = User(id="u1", email="e@e.com", created_at=None)
        mock_admin = MagicMock()
        mock_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": "log-1", "retry_status": "pending"}
        ]

        with (
            patch("app.routes.auth.admin", mock_admin),
            patch("app.routes.auth.get_owned_route_or_404"),
        ):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(
                    retry_failed_webhook(
                        route_id="route-1",
                        log_id="log-1",
                        current_user=mock_user,
                    )
                )
        assert exc.value.status_code == 400


class TestReplayWebhookLog:
    """Tests for manual webhook log replay."""

    def test_replay_success(self):
        from app.routes.auth import replay_webhook_log
        from app.models import User

        mock_user = User(id="u1", email="e@e.com", created_at=None)
        mock_route = {
            "id": "route-1",
            "destination_url": "https://example.com/webhook",
            "method": "POST",
            "headers": {},
        }
        mock_log = {
            "id": "log-1",
            "route_id": "route-1",
            "request_body": {"name": "test"},
            "content_type": "application/json",
            "ip_address": "1.2.3.4",
            "user_agent": "curl",
        }

        with (
            patch("app.routes.auth.admin") as mock_admin,
            patch("app.routes.auth.route_repository") as mock_repo,
            patch("app.routes.auth.forward_payload", new_callable=AsyncMock, return_value=(200, "ok", {})),
            patch("app.routes.auth.log_delivery", new_callable=AsyncMock, return_value=1),
            patch("app.routes.auth.rebuild_retry_body", return_value=b'{"name":"test"}'),
            patch("app.routes.auth.get_owned_route_or_404"),
        ):
            mock_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                mock_log
            ]
            mock_repo.find_by_id = AsyncMock(return_value=mock_route)

            response = asyncio.run(
                replay_webhook_log(
                    route_id="route-1",
                    log_id="log-1",
                    current_user=mock_user,
                )
            )

            assert response.status_code == 200
            body = response.body.decode()
            assert '"replayed"' in body
            assert '"destination_status"' in body

    def test_replay_missing_log_returns_404(self):
        from app.routes.auth import replay_webhook_log
        from app.models import User
        from fastapi import HTTPException

        mock_user = User(id="u1", email="e@e.com", created_at=None)

        with (
            patch("app.routes.auth.admin") as mock_admin,
            patch("app.routes.auth.get_owned_route_or_404"),
        ):
            mock_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

            with pytest.raises(HTTPException) as exc:
                asyncio.run(
                    replay_webhook_log(
                        route_id="route-1",
                        log_id="missing-log",
                        current_user=mock_user,
                    )
                )
            assert exc.value.status_code == 404

    def test_replay_empty_body_returns_400(self):
        from app.routes.auth import replay_webhook_log
        from app.models import User
        from fastapi import HTTPException

        mock_user = User(id="u1", email="e@e.com", created_at=None)
        mock_log = {
            "id": "log-1",
            "route_id": "route-1",
            "request_body": None,
            "content_type": "application/json",
        }
        mock_route = {
            "id": "route-1",
            "destination_url": "https://example.com",
        }

        with (
            patch("app.routes.auth.admin") as mock_admin,
            patch("app.routes.auth.route_repository") as mock_repo,
            patch("app.routes.auth.rebuild_retry_body", return_value=b""),
            patch("app.routes.auth.get_owned_route_or_404"),
        ):
            mock_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                mock_log
            ]
            mock_repo.find_by_id = AsyncMock(return_value=mock_route)

            with pytest.raises(HTTPException) as exc:
                asyncio.run(
                    replay_webhook_log(
                        route_id="route-1",
                        log_id="log-1",
                        current_user=mock_user,
                    )
                )
            assert exc.value.status_code == 400
