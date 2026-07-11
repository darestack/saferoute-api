"""Tests for shared utility modules."""

from unittest.mock import MagicMock
from typing import Any

import pytest
from fastapi import HTTPException

from app.utils.routes import (
    assert_owned_route_exists,
    get_owned_route_or_404,
    route_to_response,
)


class TestRouteUtilities:
    """Tests for reusable route row helpers."""
    def test_route_to_response_strips_sensitive_fields(
        self, sample_route: dict[str, Any]
    ) -> None:
        response = route_to_response(sample_route, api_key="sk_live_full")

        assert response["id"] == sample_route["id"]
        assert response["api_key"] == "sk_live_full"
        assert response["has_webhook_secret"] is False
        assert response["has_transform"] is False
        assert "api_key_hash" not in response
        assert "webhook_secret" not in response

    def test_route_to_response_sets_feature_flags(
        self, sample_route: dict[str, Any]
    ) -> None:
        sample_route["webhook_secret"] = "safe_plain:secret"
        sample_route["transform_headers"] = {"X-Event": "{{ event }}"}

        response = route_to_response(sample_route)

        assert response["has_webhook_secret"] is True
        assert response["has_transform"] is True
        assert response["transform_headers"] == {"X-Event": "{{ event }}"}

    def test_get_owned_route_or_404_returns_first_row(
        self, sample_route: dict[str, Any]
    ) -> None:
        admin_client = MagicMock()
        query = admin_client.table.return_value.select.return_value
        query.eq.return_value = query
        query.execute.return_value.data = [sample_route]

        route = get_owned_route_or_404(
            admin_client,
            route_id="route-1",
            user_id="user-1",
            columns="id,slug",
        )

        assert route is sample_route
        admin_client.table.assert_called_once_with("routes")
        admin_client.table.return_value.select.assert_called_once_with("id,slug")
        assert query.eq.call_count == 2

    def test_get_owned_route_or_404_raises_for_missing_route(self) -> None:
        admin_client = MagicMock()
        query = admin_client.table.return_value.select.return_value
        query.eq.return_value = query
        query.execute.return_value.data = []

        with pytest.raises(HTTPException) as exc_info:
            get_owned_route_or_404(admin_client, "missing", "user-1")

        assert exc_info.value.status_code == 404

    def test_assert_owned_route_exists_uses_minimal_projection(
        self, sample_route: dict[str, Any]
    ) -> None:
        admin_client = MagicMock()
        query = admin_client.table.return_value.select.return_value
        query.eq.return_value = query
        query.execute.return_value.data = [{"id": sample_route["id"]}]

        assert_owned_route_exists(admin_client, "route-1", "user-1")

        admin_client.table.return_value.select.assert_called_once_with("id")
