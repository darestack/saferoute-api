import asyncio
import time
from collections import OrderedDict

_CIRCUIT_BREAKER_THRESHOLD = 5
_CIRCUIT_BREAKER_COOLDOWN_SECONDS = 60
_CIRCUIT_BREAKER_MAX_ENTRIES = 1_000

_circuit_breaker_state: OrderedDict[str, dict] = OrderedDict()
_circuit_breaker_lock = asyncio.Lock()


async def is_circuit_breaker_open(url: str) -> bool:
    """Return True if the circuit breaker for this URL is open."""
    async with _circuit_breaker_lock:
        state = _circuit_breaker_state.get(url)
        if not state:
            return False

        if state.get("opened_at") is None:
            return False

        now = time.monotonic()
        if now - state["opened_at"] >= _CIRCUIT_BREAKER_COOLDOWN_SECONDS:
            # Cooldown expired; allow one probe request (half-open).
            state["opened_at"] = None
            state["failures"] = 0
            return False

        return True


async def record_circuit_breaker_success(url: str) -> None:
    """Reset circuit breaker state after a successful request."""
    async with _circuit_breaker_lock:
        _circuit_breaker_state.pop(url, None)


async def record_circuit_breaker_failure(url: str) -> None:
    """Record a failure and open the circuit if threshold is reached."""
    async with _circuit_breaker_lock:
        state = _circuit_breaker_state.setdefault(
            url, {"failures": 0, "opened_at": None}
        )
        _circuit_breaker_state.move_to_end(url)
        state["failures"] += 1
        if state["failures"] >= _CIRCUIT_BREAKER_THRESHOLD:
            state["opened_at"] = time.monotonic()

        # Bounded eviction: drop oldest quarter when over the limit.
        if len(_circuit_breaker_state) > _CIRCUIT_BREAKER_MAX_ENTRIES:
            evict_count = max(1, _CIRCUIT_BREAKER_MAX_ENTRIES // 4)
            for _ in range(evict_count):
                _circuit_breaker_state.popitem(last=False)


async def clear_route_circuit_breaker(url: str) -> None:
    """Clear circuit breaker state for a URL (e.g. after route update)."""
    async with _circuit_breaker_lock:
        _circuit_breaker_state.pop(url, None)
