"""Payment processing service for credit pack purchases.

Integrates with Paystack for one-time payment collection and verification.
"""

from __future__ import annotations
import hashlib
import hmac
import logging
from typing import Any
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

import httpx
from fastapi import HTTPException, status

from app.config import settings
from app.database import admin, execute_query
from app.monitoring import add_breadcrumb  # noqa: E402

logger = logging.getLogger(__name__)

_TIER_CREDITS = {
    "starter": 1000,
    "builder": 10000,
    "agency": 50000,
}
_TIER_AMOUNTS_KOBO = {
    "starter": 500_00,  # 5.00 USD in kobo (assuming USD, will adjust for NGN)
    "builder": 2500_00,  # 25.00 USD
    "agency": 7500_00,  # 75.00 USD
}

# Paystack amounts in kobo (NGN)
_TIER_AMOUNTS_NGN_KOBO = {
    "starter": 2500_00,  # ₦2,500 (~$5 at ~₦500/$)
    "builder": 12500_00,  # ₦12,500 (~$25)
    "agency": 37500_00,  # ₦37,500 (~$75)
}


def get_tier_credits(tier: str) -> int:
    """Return the number of credits for a given tier."""
    tier = tier.lower()
    if tier not in _TIER_CREDITS:
        raise ValueError(f"Invalid tier: {tier}")
    return _TIER_CREDITS[tier]


def get_tier_amount_kobo(tier: str) -> int:
    """Return the amount in kobo for a given tier."""
    tier = tier.lower()
    if tier not in _TIER_AMOUNTS_NGN_KOBO:
        raise ValueError(f"Invalid tier: {tier}")
    return _TIER_AMOUNTS_NGN_KOBO[tier]


async def initialize_payment(
    user_id: str,
    tier: str,
    email: str,
) -> dict[str, Any]:
    """Initialize a Paystack payment for a credit pack.

    Args:
        user_id: The user's UUID.
        tier: The pricing tier (starter/builder/agency).
        email: Customer email for Paystack receipt.

    Returns:
        Dict with authorization_url, reference, amount, currency.

    Raises:
        HTTPException: 500 if Paystack initialization fails.
    """
    if not settings.PAYSTACK_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment system not configured",
        )

    amount = get_tier_amount_kobo(tier)
    credits = get_tier_credits(tier)
    reference = f"sr_{user_id[:8]}_{tier}"

    # Ensure reference is unique
    existing = await execute_query(
        admin.table("payment_transactions")
        .select("reference")
        .eq("reference", reference)
        .limit(1)
    )
    if existing.data:
        reference = f"sr_{user_id[:8]}_{tier}_{int(hashlib.sha256(email.encode()).hexdigest()[:8], 16) % 10000}"

    payload = {
        "email": email,
        "amount": amount,
        "currency": "NGN",
        "reference": reference,
        "metadata": {
            "user_id": user_id,
            "tier": tier,
            "credits": credits,
        },
        "callback_url": settings.FRONTEND_URL + "/dashboard.html",
    }

    try:
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
            reraise=True,
        )
        async def _post_with_retry(
            client: httpx.AsyncClient,
            url: str,
            json: dict[str, Any],
        ) -> httpx.Response:
            return await client.post(url, json=json)

        client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )
        try:
            response = await _post_with_retry(
                client,
                f"{settings.PAYSTACK_BASE_URL}/transaction/initialize",
                payload,
            )
        finally:
            await client.aclose()

        if response.status_code != 200:
            logger.error("Paystack initialize failed: %s", response.text)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to initialize payment",
            )

        data = response.json()
        if not data.get("status"):
            logger.error("Paystack initialize error: %s", data)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=data.get("message", "Payment initialization failed"),
            )

        # Store pending transaction
        await execute_query(
            admin.table("payment_transactions").insert({
                "user_id": user_id,
                "reference": reference,
                "amount": amount,
                "currency": "NGN",
                "tier": tier,
                "credits_to_add": credits,
                "status": "pending",
                "paystack_response": data,
            })
        )

        add_breadcrumb(
            f"Payment initialized: {tier} pack",
            category="payment",
            level="info",
            data={"user_id": user_id, "tier": tier, "amount": amount, "reference": reference},
        )

        return {
            "authorization_url": data["data"]["authorization_url"],
            "reference": reference,
            "amount": amount,
            "currency": "NGN",
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Paystack initialization error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment initialization failed",
        ) from exc


async def verify_payment(reference: str, user_id: str | None = None) -> dict[str, Any]:
    """Verify a Paystack payment and credit the user's account if successful.

    Args:
        reference: Paystack transaction reference.
        user_id: Optional owner user ID for access control.

    Returns:
        Dict with verification status and credit details.

    Raises:
        HTTPException: 404 if transaction not found or not owned by caller,
            500 if verification fails.
    """
    if not settings.PAYSTACK_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment system not configured",
        )

    # Look up transaction
    tx_result = await execute_query(
        admin.table("payment_transactions")
        .select("*")
        .eq("reference", reference)
        .limit(1)
    )
    if not tx_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found",
        )

    tx = tx_result.data[0]
    if user_id is not None and tx.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found",
        )
    if tx["status"] == "success":
        return {
            "status": "success",
            "reference": reference,
            "amount": tx["amount"],
            "credits_added": tx["credits_to_add"],
            "new_balance": 0,  # Caller can fetch from /v1/me
        }

    try:
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
            reraise=True,
        )
        async def _get_with_retry(
            client: httpx.AsyncClient,
            url: str,
        ) -> httpx.Response:
            return await client.get(url)

        client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            },
            timeout=10.0,
        )
        try:
            response = await _get_with_retry(
                client,
                f"{settings.PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            )
        finally:
            await client.aclose()

        if response.status_code != 200:
            logger.error("Paystack verify failed: %s", response.text)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to verify payment",
            )

        data = response.json()
        if not data.get("status"):
            logger.error("Paystack verify error: %s", data)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=data.get("message", "Payment verification failed"),
            )

        paystack_status = data["data"].get("status")
        is_success = paystack_status == "success"

        # Update transaction
        await execute_query(
            admin.table("payment_transactions")
            .update({
                "status": "success" if is_success else "failed",
                "paystack_response": data,
            })
            .eq("reference", reference)
        )

        if is_success:
            # Credit the user's account
            await execute_query(
                admin.rpc("add_user_credits", {
                    "p_user_id": tx["user_id"],
                    "p_amount": tx["credits_to_add"],
                })
            )
            # Update tier
            await execute_query(
                admin.table("user_profiles")
                .update({"tier": tx["tier"]})
                .eq("id", tx["user_id"])
            )

        return {
            "status": paystack_status,
            "reference": reference,
            "amount": tx["amount"],
            "credits_added": tx["credits_to_add"] if is_success else 0,
            "new_balance": 0,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Paystack verification error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment verification failed",
        ) from exc


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify Paystack webhook signature.

    Args:
        payload: Raw request body bytes.
        signature: X-Paystack-Signature header value.

    Returns:
        True if signature is valid, False otherwise.
    """
    if not settings.PAYSTACK_SECRET_KEY:
        return False

    expected = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode(),
        payload,
        hashlib.sha512,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


async def process_webhook(event: str, data: dict[str, Any]) -> None:
    """Process a Paystack webhook event.

    Args:
        event: Event type (charge.success, charge.failed, etc.).
        data: Event data payload.
    """
    webhook_url = getattr(settings, "PAYSTACK_WEBHOOK_URL", "")
    if webhook_url:
        logger.debug("Processing Paystack webhook from %s", webhook_url)
    reference = data.get("reference")
    if not reference:
        logger.warning("Paystack webhook missing reference")
        return

    if event == "charge.success":
        # Mark transaction as success and credit user
        tx_result = await execute_query(
            admin.table("payment_transactions")
            .select("*")
            .eq("reference", reference)
            .limit(1)
        )

        if tx_result.data:
            tx = tx_result.data[0]
            if tx["status"] != "success":
                await execute_query(
                    admin.table("payment_transactions")
                    .update({
                        "status": "success",
                        "paystack_response": data,
                    })
                    .eq("reference", reference)
                )
                await execute_query(
                    admin.rpc("add_user_credits", {
                        "p_user_id": tx["user_id"],
                        "p_amount": tx["credits_to_add"],
                    })
                )
                await execute_query(
                    admin.table("user_profiles")
                    .update({"tier": tx["tier"]})
                    .eq("id", tx["user_id"])
                )
                logger.info("Credited %s credits to user %s via webhook", tx["credits_to_add"], tx["user_id"])
    elif event == "charge.failed":
        await execute_query(
            admin.table("payment_transactions")
            .update({
                "status": "failed",
                "paystack_response": data,
            })
            .eq("reference", reference)
        )
