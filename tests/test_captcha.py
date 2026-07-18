"""Tests for CAPTCHA verification utilities."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.captcha import verify_recaptcha_token, verify_turnstile_token


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


class TestVerifyRecaptchaToken:
    """Tests for Google reCAPTCHA verification."""

    @pytest.mark.asyncio
    async def test_returns_false_for_empty_token(self):
        assert await verify_recaptcha_token("", "secret", "1.2.3.4") is False
        assert await verify_recaptcha_token("token", "", "1.2.3.4") is False

    @pytest.mark.asyncio
    async def test_returns_true_for_valid_token_with_high_score(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True, "score": 0.9}
        mock_client.post.return_value = mock_response

        with (
            patch("app.utils.captcha.settings.RECAPTCHA_VERIFY_URL", "https://www.google.com/recaptcha/api/siteverify"),
            patch("app.utils.captcha.get_http_client", return_value=mock_client),
        ):
            result = await verify_recaptcha_token("valid-token", "secret", "1.2.3.4")
            assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_for_low_score(self):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True, "score": 0.3}
        mock_client.post.return_value = mock_response

        with (
            patch("app.utils.captcha.settings.RECAPTCHA_VERIFY_URL", "https://www.google.com/recaptcha/api/siteverify"),
            patch("app.utils.captcha.get_http_client", return_value=mock_client),
        ):
            result = await verify_recaptcha_token("token", "secret", "1.2.3.4")
            assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_network_error(self):
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("Network error")

        with (
            patch("app.utils.captcha.settings.RECAPTCHA_VERIFY_URL", "https://www.google.com/recaptcha/api/siteverify"),
            patch("app.utils.captcha.get_http_client", return_value=mock_client),
        ):
            result = await verify_recaptcha_token("token", "secret", "1.2.3.4")
            assert result is False
