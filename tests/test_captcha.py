"""Tests for CAPTCHA verification utilities."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.captcha import verify_turnstile_token


class TestVerifyTurnstileToken:
    """Tests for Cloudflare Turnstile verification."""

    @pytest.mark.asyncio
    async def test_returns_false_for_empty_token(self):
        assert await verify_turnstile_token("", "secret", "1.2.3.4") is False
        assert await verify_turnstile_token("token", "", "1.2.3.4") is False

    @pytest.mark.asyncio
    async def test_returns_true_for_valid_token(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_client.post.return_value = mock_response

        with patch("app.utils.captcha.get_http_client", return_value=mock_client):
            result = await verify_turnstile_token("valid-token", "secret", "1.2.3.4")
            assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_for_invalid_token(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": False}
        mock_client.post.return_value = mock_response

        with patch("app.utils.captcha.get_http_client", return_value=mock_client):
            result = await verify_turnstile_token("invalid-token", "secret", "1.2.3.4")
            assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_http_error(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client.post.return_value = mock_response

        with patch("app.utils.captcha.get_http_client", return_value=mock_client):
            result = await verify_turnstile_token("token", "secret", "1.2.3.4")
            assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_network_error(self):
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("Network error")

        with patch("app.utils.captcha.get_http_client", return_value=mock_client):
            result = await verify_turnstile_token("token", "secret", "1.2.3.4")
            assert result is False
