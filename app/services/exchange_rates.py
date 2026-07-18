"""Exchange rate service for currency conversion.

Uses official exchange rate sources with caching to minimize API calls.
"""

from __future__ import annotations
import asyncio
import logging
import time
from collections import OrderedDict

from fastapi import HTTPException, status
from app.database import get_http_client

logger = logging.getLogger(__name__)

# Free API: open.er-api.com (powered by openexchangerates.org data)
_EXCHANGE_RATE_URL = "https://open.er-api.com/v6/latest/USD"

# Cache TTL: 1 hour (exchange rates don't change minute-to-minute)
_CACHE_TTL_SECONDS = 3600

# Bound the in-memory rate cache so it cannot grow without limit as new
# currency codes are requested. Oldest entries are evicted first (LRU).
_RATE_CACHE_MAX_ENTRIES = 256
_rate_cache: "OrderedDict[str, tuple[float, int]]" = OrderedDict()
_rate_cache_lock = asyncio.Lock()


async def get_exchange_rate(to_currency: str) -> float:
    """Get the exchange rate from USD to the target currency.

    Uses cached rates when available (< 1 hour old).

    Args:
        to_currency: ISO 4217 currency code (e.g., "NGN", "EUR", "GBP").

    Returns:
        Exchange rate (1 USD = X target currency).

    Raises:
        HTTPException: 502 if rate fetch fails.
    """
    to_currency = to_currency.upper()

    # Return cached rate if fresh (LRU promotion under lock).
    async with _rate_cache_lock:
        cached = _rate_cache.get(to_currency)
        if cached:
            _rate_cache.move_to_end(to_currency)
            rate, ts = cached
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return rate

    # Fetch fresh rates
    try:
        client = get_http_client()
        response = await client.get(_EXCHANGE_RATE_URL, timeout=5.0)
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to fetch exchange rates",
            )

        data = response.json()
        rates = data.get("rates", {})

        if to_currency not in rates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Currency {to_currency} not supported",
            )

        rate = float(rates[to_currency])
        # Cache the requested currency plus a few common ones while we're here.
        async with _rate_cache_lock:
            _rate_cache[to_currency] = (rate, int(time.time()))
            for currency in ["EUR", "GBP", "ZAR", "KES", "GHS", "CAD", "AUD"]:
                if currency in rates:
                    _rate_cache[currency] = (float(rates[currency]), int(time.time()))
            while len(_rate_cache) > _RATE_CACHE_MAX_ENTRIES:
                _rate_cache.popitem(last=False)

        return rate

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Exchange rate fetch failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Exchange rate service unavailable",
        ) from exc


async def convert_usd_to_local(usd_amount: float, to_currency: str) -> float:
    """Convert USD amount to local currency.

    Args:
        usd_amount: Amount in USD.
        to_currency: ISO 4217 currency code.

    Returns:
        Amount in target currency.
    """
    if to_currency.upper() == "USD":
        return usd_amount

    rate = await get_exchange_rate(to_currency)
    return round(usd_amount * rate, 2)


def format_price(amount: float, currency: str) -> str:
    """Format a price for display.

    Args:
        amount: Numeric amount.
        currency: ISO 4217 currency code.

    Returns:
        Formatted price string.
    """
    symbols = {
        "USD": "$",
        "NGN": "₦",
        "EUR": "€",
        "GBP": "£",
        "ZAR": "R",
        "KES": "KSh",
        "GHS": "GH₵",
        "CAD": "C$",
        "AUD": "A$",
    }
    symbol = symbols.get(currency.upper(), currency)
    return f"{symbol}{amount:,.2f}"
