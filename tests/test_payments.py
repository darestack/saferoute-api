"""Tests for Paystack payment integration."""

from __future__ import annotations
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.payments import (
    get_tier_credits,
    get_tier_amount_kobo,
    initialize_payment,
    verify_payment,
    verify_webhook_signature,
    process_webhook,
)
from app.config import Settings


class TestTierHelpers:
    """Tests for tier credit and amount helpers."""

    def test_get_tier_credits_starter(self):
        assert get_tier_credits("starter") == 1000

    def test_get_tier_credits_builder(self):
        assert get_tier_credits("builder") == 10000

    def test_get_tier_credits_agency(self):
        assert get_tier_credits("agency") == 50000

    def test_get_tier_credits_case_insensitive(self):
        assert get_tier_credits("STARTER") == 1000

    def test_get_tier_credits_invalid(self):
        with pytest.raises(ValueError, match="Invalid tier"):
            get_tier_credits("invalid")

    def test_get_tier_amount_kobo_starter(self):
        assert get_tier_amount_kobo("starter") == 250000

    def test_get_tier_amount_kobo_builder(self):
        assert get_tier_amount_kobo("builder") == 1250000

    def test_get_tier_amount_kobo_agency(self):
        assert get_tier_amount_kobo("agency") == 3750000


class TestInitializePayment:
    """Tests for payment initialization."""

    @pytest.mark.asyncio
    async def test_initialize_payment_success(self):
        with (
            patch("app.services.payments.settings") as mock_settings,
            patch("app.services.payments.execute_query") as mock_execute_query,
        ):
            mock_settings.PAYSTACK_SECRET_KEY = "sk_test_123"
            mock_settings.PAYSTACK_BASE_URL = "https://api.paystack.co"
            mock_settings.FRONTEND_URL = "http://localhost:8000"

            mock_execute_query.return_value = MagicMock(data=[])

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": True,
                "data": {
                    "authorization_url": "https://checkout.paystack.com/test",
                    "reference": "sr_user-123_starter",
                    "amount": 250000,
                    "currency": "NGN",
                },
            }

            async def mock_post(*args, **kwargs):
                return mock_response

            async def mock_aclose():
                pass

            mock_client = MagicMock()
            mock_client.post = mock_post
            mock_client.aclose = mock_aclose
            mock_client.__aenter__ = MagicMock(return_value=mock_client)
            mock_client.__aexit__ = MagicMock(return_value=False)

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await initialize_payment(
                    user_id="user-123",
                    tier="starter",
                    email="test@example.com",
                )

            assert result["authorization_url"] == "https://checkout.paystack.com/test"
            assert result["reference"] == "sr_user-123_starter"
            assert result["amount"] == 250000
            assert result["currency"] == "NGN"

    @pytest.mark.asyncio
    async def test_initialize_payment_no_secret_key(self):
        with patch("app.services.payments.settings") as mock_settings:
            mock_settings.PAYSTACK_SECRET_KEY = ""

            with pytest.raises(HTTPException, match="Payment system not configured"):
                await initialize_payment(
                    user_id="user-123",
                    tier="starter",
                    email="test@example.com",
                )


class TestVerifyPayment:
    """Tests for payment verification."""

    @pytest.mark.asyncio
    async def test_verify_payment_already_success(self):
        with (
            patch("app.services.payments.settings") as mock_settings,
            patch("app.services.payments.execute_query") as mock_execute_query,
        ):
            mock_settings.PAYSTACK_SECRET_KEY = "sk_test_123"
            mock_settings.PAYSTACK_BASE_URL = "https://api.paystack.co"
            mock_execute_query.return_value = MagicMock(
                data=[{
                    "id": "tx-123",
                    "reference": "sr_user-123_starter",
                    "amount": 250000,
                    "credits_to_add": 1000,
                    "status": "success",
                    "user_id": "user-123",
                    "tier": "starter",
                }]
            )

            result = await verify_payment("sr_user-123_starter")

            assert result["status"] == "success"
            assert result["reference"] == "sr_user-123_starter"
            assert result["amount"] == 250000
            assert result["credits_added"] == 1000

    @pytest.mark.asyncio
    async def test_verify_payment_success_from_paystack(self):
        with (
            patch("app.services.payments.settings") as mock_settings,
            patch("app.services.payments.execute_query") as mock_execute_query,
        ):
            mock_settings.PAYSTACK_SECRET_KEY = "sk_test_123"
            mock_settings.PAYSTACK_BASE_URL = "https://api.paystack.co"

            mock_execute_query.return_value = MagicMock(
                data=[{
                    "id": "tx-123",
                    "reference": "sr_user-123_starter",
                    "amount": 250000,
                    "credits_to_add": 1000,
                    "status": "pending",
                    "user_id": "user-123",
                    "tier": "starter",
                }]
            )

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": True,
                "data": {
                    "status": "success",
                    "reference": "sr_user-123_starter",
                    "amount": 250000,
                },
            }

            async def mock_get(*args, **kwargs):
                return mock_response

            async def mock_aclose2():
                pass

            mock_client = MagicMock()
            mock_client.get = mock_get
            mock_client.aclose = mock_aclose2
            mock_client.__aenter__ = MagicMock(return_value=mock_client)
            mock_client.__aexit__ = MagicMock(return_value=False)

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await verify_payment("sr_user-123_starter")

            assert result["status"] == "success"
            assert result["credits_added"] == 1000


class TestWebhookSignature:
    """Tests for Paystack webhook signature verification."""

    @patch("app.services.payments.settings")
    def test_verify_webhook_signature_valid(self, mock_settings):
        mock_settings.PAYSTACK_SECRET_KEY = "sk_test_123"
        payload = b'{"event": "charge.success"}'
        import hashlib
        import hmac
        signature = hmac.new(
            b"sk_test_123", payload, hashlib.sha512
        ).hexdigest()

        assert verify_webhook_signature(payload, signature) is True

    @patch("app.services.payments.settings")
    def test_verify_webhook_signature_invalid(self, mock_settings):
        mock_settings.PAYSTACK_SECRET_KEY = "sk_test_123"
        payload = b'{"event": "charge.success"}'

        assert verify_webhook_signature(payload, "invalid_signature") is False

    @patch("app.services.payments.settings")
    def test_verify_webhook_signature_no_key(self, mock_settings):
        mock_settings.PAYSTACK_SECRET_KEY = ""
        payload = b'{"event": "charge.success"}'

        assert verify_webhook_signature(payload, "any_signature") is False


class TestProcessWebhook:
    """Tests for webhook event processing."""

    @pytest.mark.asyncio
    async def test_process_webhook_charge_success(self):
        with patch("app.services.payments.execute_query") as mock_execute_query:
            mock_execute_query.return_value = MagicMock(
                data=[{
                    "id": "tx-123",
                    "reference": "sr_user-123_starter",
                    "amount": 250000,
                    "credits_to_add": 1000,
                    "status": "pending",
                    "user_id": "user-123",
                    "tier": "starter",
                }]
            )

            await process_webhook("charge.success", {
                "reference": "sr_user-123_starter",
                "status": "success",
                "amount": 250000,
            })

            assert mock_execute_query.call_count >= 2

    @pytest.mark.asyncio
    async def test_process_webhook_charge_failed(self):
        with patch("app.services.payments.execute_query") as mock_execute_query:
            await process_webhook("charge.failed", {
                "reference": "sr_user-123_starter",
            })

            assert mock_execute_query.call_count >= 1

    @pytest.mark.asyncio
    async def test_process_webhook_missing_reference(self):
        with patch("app.services.payments.execute_query") as mock_execute_query:
            await process_webhook("charge.success", {})

            mock_execute_query.assert_not_called()
