"""Tests for Paystack payment integration."""

from __future__ import annotations

import hashlib
import hmac

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.payments import (
    get_tier_credits,
    get_tier_amount_usd,
    initialize_payment,
    verify_payment,
    verify_webhook_signature,
    process_webhook,
)


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

    def test_get_tier_amount_usd_starter(self):
        assert get_tier_amount_usd("starter") == 5.00

    def test_get_tier_amount_usd_builder(self):
        assert get_tier_amount_usd("builder") == 25.00

    def test_get_tier_amount_usd_agency(self):
        assert get_tier_amount_usd("agency") == 75.00


class TestInitializePayment:
    """Tests for payment initialization."""

    @pytest.mark.asyncio
    async def test_initialize_payment_success(self):
        with (
            patch("app.services.payments.settings") as mock_settings,
            patch("app.services.payments.execute_query") as mock_execute_query,
            patch("app.services.exchange_rates.get_exchange_rate", return_value=500.0),
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
            assert result["usd_amount"] == 5.00
            assert result["display_currency"] == "USD"

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
            tx_row = {
                "id": "tx-123",
                "reference": "sr_user-123_starter",
                "amount": 250000,
                "credits_to_add": 1000,
                "status": "success",
                "user_id": "user-123",
                "tier": "starter",
            }
            # Call 1: transaction lookup. Call 2: balance read (must include
            # "credits" now that verify_payment populates new_balance).
            mock_execute_query.side_effect = [
                MagicMock(data=[tx_row]),
            ]

            result = await verify_payment("sr_user-123_starter")

            assert result["status"] == "success"
            assert result["reference"] == "sr_user-123_starter"
            assert result["amount"] == 250000
            assert result["credits_added"] == 1000
            assert result["new_balance"] == 0

    @pytest.mark.asyncio
    async def test_verify_payment_success_from_paystack(self):
        with (
            patch("app.services.payments.settings") as mock_settings,
            patch("app.services.payments.execute_query") as mock_execute_query,
        ):
            mock_settings.PAYSTACK_SECRET_KEY = "sk_test_123"
            mock_settings.PAYSTACK_BASE_URL = "https://api.paystack.co"

            pending_tx = {
                "id": "tx-123",
                "reference": "sr_user-123_starter",
                "amount": 250000,
                "credits_to_add": 1000,
                "status": "pending",
                "user_id": "user-123",
                "tier": "starter",
            }
            # Calls: lookup, conditional transition (returns the row on first
            # success flip), balance read. The add-credits/tier RPCs also call
            # execute_query, so supply responses for those too.
            mock_execute_query.side_effect = [
                MagicMock(data=[pending_tx]),  # lookup
                MagicMock(data=[pending_tx]),  # conditional status update
                MagicMock(data=None),  # add_user_credits rpc (ignored)
                MagicMock(data=None),  # tier update (ignored)
                MagicMock(data=[{"credits": 6000}]),  # balance read
            ]

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

    @pytest.mark.asyncio
    async def test_verify_payment_idempotent_on_duplicate(self):
        """A second verify of an already-credited reference must not re-credit.

        The conditional UPDATE (.eq("status", "pending")) returns no row when
        the transaction is already success, so add_user_credits is skipped.
        """
        with (
            patch("app.services.payments.settings") as mock_settings,
            patch("app.services.payments.execute_query") as mock_execute_query,
        ):
            mock_settings.PAYSTACK_SECRET_KEY = "sk_test_123"
            mock_settings.PAYSTACK_BASE_URL = "https://api.paystack.co"

            pending_tx = {
                "id": "tx-123",
                "reference": "sr_user-123_starter",
                "amount": 250000,
                "credits_to_add": 1000,
                "status": "success",
                "user_id": "user-123",
                "tier": "starter",
            }
            mock_execute_query.side_effect = [
                MagicMock(data=[pending_tx]),  # lookup (already success)
            ]

            result = await verify_payment("sr_user-123_starter")

            assert result["status"] == "success"
            assert result["credits_added"] == 1000
            assert result["new_balance"] == 0
            # Only the lookup ran; no add_user_credits RPC
            # should have been issued for an already-success transaction.
            updates = [
                c
                for c in mock_execute_query.call_args_list
                if "add_user_credits" in str(c)
            ]
            assert updates == []


class TestWebhookSignature:
    """Tests for Paystack webhook signature verification."""

    @patch("app.services.payments.settings")
    def test_verify_webhook_signature_valid(self, mock_settings):
        mock_settings.PAYSTACK_SECRET_KEY = "sk_test_123"
        payload = b'{"event": "charge.success"}'
        signature = hmac.new(b"sk_test_123", payload, hashlib.sha512).hexdigest()

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
                data=[
                    {
                        "id": "tx-123",
                        "reference": "sr_user-123_starter",
                        "amount": 250000,
                        "credits_to_add": 1000,
                        "status": "pending",
                        "user_id": "user-123",
                        "tier": "starter",
                    }
                ]
            )

            await process_webhook(
                "charge.success",
                {
                    "reference": "sr_user-123_starter",
                    "status": "success",
                    "amount": 250000,
                },
            )

            assert mock_execute_query.call_count >= 2

    @pytest.mark.asyncio
    async def test_process_webhook_charge_failed(self):
        with patch("app.services.payments.execute_query") as mock_execute_query:
            await process_webhook(
                "charge.failed",
                {
                    "reference": "sr_user-123_starter",
                },
            )

            assert mock_execute_query.call_count >= 1

    @pytest.mark.asyncio
    async def test_process_webhook_missing_reference(self):
        with patch("app.services.payments.execute_query") as mock_execute_query:
            await process_webhook("charge.success", {})

            mock_execute_query.assert_not_called()


class TestPaymentReferenceUniqueness:
    """Tests for payment reference collision handling."""

    @pytest.mark.asyncio
    async def test_reference_includes_unique_suffix_on_collision(self):
        with (
            patch("app.services.payments.settings") as mock_settings,
            patch("app.services.payments.execute_query") as mock_execute_query,
            patch("secrets.token_hex", return_value="abcd1234"),
        ):
            mock_settings.PAYSTACK_SECRET_KEY = "sk_test_123"
            mock_settings.PAYSTACK_BASE_URL = "https://api.paystack.co"
            mock_settings.FRONTEND_URL = "http://localhost:8000"

            # First call: reference collision exists.
            mock_execute_query.return_value = MagicMock(
                data=[{"reference": "sr_user-123_starter"}]
            )

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "status": True,
                "data": {
                    "authorization_url": "https://checkout.paystack.com/test",
                    "reference": "sr_user-123_starter_abcd1234",
                    "amount": 250000,
                    "currency": "NGN",
                },
            }

            async def mock_post(*args, **kwargs):
                return mock_response

            mock_client = MagicMock()
            mock_client.post = mock_post
            mock_client.aclose = AsyncMock()

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await initialize_payment(
                    user_id="user-123",
                    tier="starter",
                    email="test@example.com",
                )

            assert result["reference"] == "sr_user-123_starter_abcd1234"
            assert "abcd1234" in result["reference"]
