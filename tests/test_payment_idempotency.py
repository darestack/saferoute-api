"""Tests for idempotent credit granting (prevent double-spend).

Both the Paystack webhook path (``process_webhook``) and the return-URL
verify path (``verify_payment``) may attempt to credit the same transaction.
They must route through the atomic ``grant_credits_once`` SQL function so a
user is never credited twice for one payment.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.payments import process_webhook, verify_payment


def _tx_row(status: str, granted: bool) -> dict:
    return {
        "id": "tx-123",
        "reference": "sr_user-123_starter",
        "amount": 250000,
        "credits_to_add": 1000,
        "status": status,
        "credits_granted": granted,
        "user_id": "user-123",
        "tier": "starter",
    }


def _paystack_success_response() -> MagicMock:
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
    return mock_response


async def _run_verify_payment(execute_query, settings) -> dict:
    """Drive verify_payment with a mocked httpx client + DB."""
    settings.PAYSTACK_SECRET_KEY = "sk_test_123"
    settings.PAYSTACK_BASE_URL = "https://api.paystack.co"

    async def mock_get(*args, **kwargs):
        return _paystack_success_response()

    mock_client = MagicMock()
    mock_client.get = mock_get
    mock_client.aclose = AsyncMock()
    mock_client.__aenter__ = MagicMock(return_value=mock_client)
    mock_client.__aexit__ = MagicMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        return await verify_payment("sr_user-123_starter")


def _is_rpc(rpc_mock, name: str) -> bool:
    """True if ``admin.rpc`` was invoked with the given SQL function name."""
    return any(call.args and call.args[0] == name for call in rpc_mock.call_args_list)


def _grant_rpc_invocations(rpc_mock) -> int:
    return sum(
        1
        for c in rpc_mock.call_args_list
        if c.args and c.args[0] == "grant_credits_once"
    )


@pytest.mark.asyncio
async def test_verify_payment_calls_grant_credits_once():
    with (
        patch("app.services.payments.settings") as mock_settings,
        patch("app.services.payments.execute_query") as mock_execute_query,
        patch("app.services.payments.admin") as mock_admin,
    ):
        mock_execute_query.return_value = MagicMock(data=[_tx_row("pending", False)])

        await _run_verify_payment(mock_execute_query, mock_settings)

        assert _grant_rpc_invocations(mock_admin.rpc) >= 1, (
            "verify_payment must grant credits via grant_credits_once, "
            "not the legacy add_user_credits path"
        )


@pytest.mark.asyncio
async def test_process_webhook_calls_grant_credits_once():
    with (
        patch("app.services.payments.execute_query") as mock_execute_query,
        patch("app.services.payments.admin") as mock_admin,
    ):
        mock_execute_query.return_value = MagicMock(data=[_tx_row("pending", False)])

        await process_webhook(
            "charge.success",
            {"reference": "sr_user-123_starter", "status": "success", "amount": 250000},
        )

        assert _grant_rpc_invocations(mock_admin.rpc) >= 1, (
            "process_webhook must grant credits via grant_credits_once to stay "
            "idempotent with the verify path"
        )


@pytest.mark.asyncio
async def test_neither_path_calls_add_user_credits_directly():
    """Credit addition must route only through grant_credits_once."""
    with (
        patch("app.services.payments.settings") as mock_settings,
        patch("app.services.payments.execute_query") as mock_execute_query,
        patch("app.services.payments.admin") as mock_admin,
    ):
        mock_execute_query.return_value = MagicMock(data=[_tx_row("success", True)])

        await _run_verify_payment(mock_execute_query, mock_settings)
        await process_webhook(
            "charge.success",
            {"reference": "sr_user-123_starter", "status": "success", "amount": 250000},
        )

        for call in mock_admin.rpc.call_args_list:
            assert call.args[0] != "add_user_credits", (
                "Credit addition must go only through grant_credits_once"
            )
