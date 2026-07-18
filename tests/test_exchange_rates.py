"""Tests for exchange rate service."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.exchange_rates import (
    convert_usd_to_local,
    format_price,
    get_exchange_rate,
)


class TestGetExchangeRate:
    """Tests for get_exchange_rate function."""

    @pytest.mark.asyncio
    async def test_returns_cached_rate_when_fresh(self):
        """Should return cached rate if less than 1 hour old."""
        with patch("app.services.exchange_rates._rate_cache", {"NGN": (1500.0, int(time.time()))}):
            rate = await get_exchange_rate("NGN")
            assert rate == 1500.0

    @pytest.mark.asyncio
    async def test_fetches_fresh_rate_when_cache_stale(self):
        """Should fetch fresh rate when cache is stale."""
        stale_ts = int(time.time()) - 7200  # 2 hours ago
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "rates": {"NGN": 1600.0, "EUR": 0.92}
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with (
            patch("app.services.exchange_rates._rate_cache", {"NGN": (1500.0, stale_ts)}),
            patch("app.services.exchange_rates.get_http_client", return_value=mock_client),
        ):
            rate = await get_exchange_rate("NGN")
            assert rate == 1600.0

    @pytest.mark.asyncio
    async def test_raises_502_on_api_failure(self):
        """Should raise HTTPException 502 when API fails."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("API down")

        with patch("app.services.exchange_rates.get_http_client", return_value=mock_client):
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc:
                await get_exchange_rate("NGN")
            assert exc.value.status_code == 502
            assert "Exchange rate service unavailable" in exc.value.detail

    @pytest.mark.asyncio
    async def test_raises_404_for_unsupported_currency(self):
        """Should raise HTTPException for unsupported currency."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"rates": {"USD": 1.0}}
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with (
            patch("app.services.exchange_rates._rate_cache", {}),
            patch("app.services.exchange_rates.get_http_client", return_value=mock_client),
        ):
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc:
                await get_exchange_rate("XYZ")
            assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_raises_502_on_non_200_response(self):
        """Should raise HTTPException when API returns non-200."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with (
            patch("app.services.exchange_rates._rate_cache", {}),
            patch("app.services.exchange_rates.get_http_client", return_value=mock_client),
        ):
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc:
                await get_exchange_rate("NGN")
            assert exc.value.status_code == 502


class TestConvertUsdToLocal:
    """Tests for convert_usd_to_local function."""

    @pytest.mark.asyncio
    async def test_converts_usd_to_local_currency(self):
        """Should convert USD to target currency."""
        with patch("app.services.exchange_rates.get_exchange_rate", return_value=1500.0):
            result = await convert_usd_to_local(10.0, "NGN")
            assert result == 15000.0

    @pytest.mark.asyncio
    async def test_returns_same_amount_for_usd(self):
        """Should return same amount when target is USD."""
        result = await convert_usd_to_local(10.0, "USD")
        assert result == 10.0


class TestFormatPrice:
    """Tests for format_price function."""

    def test_formats_usd(self):
        """Should format USD price correctly."""
        assert format_price(5.0, "USD") == "$5.00"

    def test_formats_ngn(self):
        """Should format NGN price correctly."""
        assert format_price(2500.0, "NGN") == "₦2,500.00"

    def test_formats_eur(self):
        """Should format EUR price correctly."""
        assert format_price(25.0, "EUR") == "€25.00"

    def test_formats_unknown_currency(self):
        """Should use currency code as symbol for unknown currencies."""
        assert format_price(100.0, "XYZ") == "XYZ100.00"

    def test_handles_case_insensitive(self):
        """Should handle case-insensitive currency codes."""
        assert format_price(5.0, "usd") == "$5.00"
        assert format_price(5.0, "NgN") == "₦5.00"
