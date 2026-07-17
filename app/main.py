"""SafeRoute API entrypoint.

Configures the FastAPI application with security middleware, CORS, and
trusted host restrictions. Mounts the proxy router so the app is runnable
both locally and on Vercel via the Mangum ASGI handler.
"""

from __future__ import annotations
import asyncio
import os
import time
import logging
import uuid
from contextlib import asynccontextmanager

from typing import Callable, Awaitable, Any, MutableMapping, TypeAlias
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.logging_config import configure_logging, request_id_var
from app.monitoring import init_monitoring  # noqa: E402

# Configure logging before any other imports that use loggers.
configure_logging(environment=settings.ENVIRONMENT)

# Initialize monitoring backends (Sentry, OpenTelemetry).
init_monitoring()

from app.routes import auth, oauth, proxy  # noqa: E402
from app.routes.auth import close_jwks_client  # noqa: E402

logger = logging.getLogger(__name__)

ASGIMessage: TypeAlias = MutableMapping[str, Any]


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    """Application lifespan manager for startup and shutdown."""
    # Verify the admin client can bypass RLS by checking a known table.
    # This catches misconfigured service-role keys early.
    try:
        from app.database import admin, execute_query

        await execute_query(admin.table("routes").select("id").limit(1))
        logger.info("Startup RLS bypass check passed")
    except Exception as exc:
        logger.warning("Startup RLS bypass check failed: %s", exc)

    # Warn if the deployment appears to use multiple workers with in-process
    # caches, which can cause stale configs and inconsistent rate limiting.

    workers = os.getenv("WORKERS", os.getenv("UVICORN_WORKERS", "1"))
    if workers != "1":
        logger.warning(
            "Multiple workers detected (WORKERS=%s). In-memory caches are not "
            "shared across workers. For consistent behavior, deploy with a "
            "single worker or move caches to Redis.",
            workers,
        )

    if not settings.RETRY_ENDPOINT_SECRET.strip():
        logger.warning(
            "RETRY_ENDPOINT_SECRET is empty. The internal retry and cleanup "
            "endpoints will reject all callers."
        )

    yield
    await shutdown_event()


app = FastAPI(
    title="SafeRoute API",
    description=(
        "Secure, Zero-Config Webhook Proxy Shield. "
        "Forward webhooks safely without exposing your destination URLs."
    ),
    version="1.0.0",
    contact={
        "name": "SafeRoute Team",
        "url": "https://saferouteapi.app",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request ID middleware
# ---------------------------------------------------------------------------
class RequestIDMiddleware(BaseHTTPMiddleware):
    """Generate a unique request ID for every request.

    Stores the ID in ``request.state.request_id`` and the logging
    context variable so it propagates into JSON log records.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        request_id_var.set(request_id)

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_var.set("")


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
_ALLOWED_HEADERS_PRODUCTION = [
    "Authorization",
    "Content-Type",
    "X-API-Key",
    "Idempotency-Key",
    "X-Request-ID",
]


def _get_cors_origins() -> list[str]:
    """Build the list of allowed CORS origins from settings."""
    raw = settings.FRONTEND_URL
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=(
        ["*"] if settings.ENVIRONMENT == "development" else _ALLOWED_HEADERS_PRODUCTION
    ),
    max_age=600,
)

# ---------------------------------------------------------------------------
# Trusted host
# ---------------------------------------------------------------------------
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.get_allowed_hosts())


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------
# Interactive API docs (Swagger UI / ReDoc) load assets from a public CDN, so a
# strict ``default-src 'none'`` policy would break them. We apply the strict
# policy everywhere except the documented doc paths, which get a CSP that
# permits the CDN. In production, docs should be disabled or served from a
# locked-down origin.
_DOCS_PATHS = {"/docs", "/docs/", "/openapi.json", "/redoc"}
_FRONTEND_PATHS = {
    "/",
    "/login.html",
    "/dashboard.html",
    "/auth/callback.html",
    "/assets/css/styles.css",
    "/assets/js/main.js",
    "/assets/js/dashboard.js",
    "/docs/api.md",
}
_ALLOWED_PATHS = _DOCS_PATHS | _FRONTEND_PATHS


def _apply_security_headers(response: Response, path: str) -> None:
    """Set standard hardening headers on ``response``.

    Shared by :class:`SecurityHeadersMiddleware` (normal responses) and
    :class:`RequestSizeLimitMiddleware` (413 rejections) so oversized requests
    do not ship without hardening headers.
    """
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # ``X-XSS-Protection`` is omitted on purpose: it is deprecated and can
    # introduce vulnerabilities in legacy browsers; modern browsers ignore
    # it in favour of CSP.
    if path in _ALLOWED_PATHS:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "script-src 'self' 'unsafe-inline' https://unpkg.com "
            "https://cdn.jsdelivr.net https://cdn.tailwindcss.com; "
            "style-src 'self' https://unpkg.com https://cdn.jsdelivr.net "
            "https://fonts.googleapis.com 'unsafe-inline'; "
            "font-src 'self' https://fonts.gstatic.com; "
            "connect-src 'self'"
        )
    else:
        response.headers["Content-Security-Policy"] = "default-src 'none'"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject standard security headers into every response."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        _apply_security_headers(response, request.url.path)
        return response


# ---------------------------------------------------------------------------
# Request size limit
# ---------------------------------------------------------------------------
_DEFAULT_MAX_BODY_BYTES = settings.MAX_REQUEST_BODY_BYTES
_DEFAULT_MAX_BODY_SECONDS = 30


class RequestTooLargeError(Exception):
    """Raised when a streaming request body exceeds the configured limit."""


class RequestTimeoutError(Exception):
    """Raised when a request body takes too long to arrive."""


class RequestSizeLimitMiddleware:
    """Reject requests with bodies larger than the configured limit.

    Checks ``Content-Length`` for fast rejection and wraps the ASGI ``receive``
    callable so oversized chunked bodies are rejected without pre-reading the
    body before route handlers run. Also enforces a time limit to mitigate
    slow-loris attacks.
    """

    def __init__(
        self,
        app: Any,
        max_size: int = _DEFAULT_MAX_BODY_BYTES,
        max_seconds: int = _DEFAULT_MAX_BODY_SECONDS,
    ) -> None:
        """Initialize the middleware.

        Args:
            app: The downstream ASGI app.
            max_size: Maximum allowed request body size in bytes.
            max_seconds: Maximum seconds allowed to receive the full body.
        """
        self.app = app
        self.max_size = max_size
        self.max_seconds = max_seconds

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[ASGIMessage]],
        send: Callable[[ASGIMessage], Awaitable[None]],
    ) -> None:
        """Reject oversized or slow HTTP request bodies."""
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                length = int(content_length)
            except (ValueError, TypeError):
                length = 0
            if length > self.max_size:
                response = JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large"},
                )
                _apply_security_headers(response, scope.get("path", ""))
                await response(scope, receive, send)
                return

        received = 0
        start_time = time.perf_counter()

        async def limited_receive() -> ASGIMessage:
            nonlocal received
            elapsed = time.perf_counter() - start_time
            if elapsed > self.max_seconds:
                raise RequestTimeoutError

            try:
                message = await asyncio.wait_for(
                    receive(), timeout=max(0.001, self.max_seconds - elapsed)
                )
            except asyncio.TimeoutError:
                raise RequestTimeoutError

            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_size:
                    raise RequestTooLargeError
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestTooLargeError:
            response = JSONResponse(
                status_code=413,
                content={"detail": "Request body too large"},
            )
            _apply_security_headers(response, scope.get("path", ""))
            await response(scope, receive, send)
        except RequestTimeoutError:
            response = JSONResponse(
                status_code=408,
                content={"detail": "Request body timeout"},
            )
            _apply_security_headers(response, scope.get("path", ""))
            await response(scope, receive, send)


# Middleware ordering: ``add_middleware`` prepends, so the LAST registered
# middleware runs OUTERMOST. Effective order (outer → inner):
# Size limit → Security headers → Request ID → route handlers.
# All three mutate the same final ``Response`` object, so header injection is
# order-independent in practice. ``SecurityHeadersMiddleware`` owns the security
# header set; ``RequestSizeLimitMiddleware`` delegates to the same helper for
# 413 responses so oversized rejections are hardened consistently.
app.add_middleware(RequestIDMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestSizeLimitMiddleware, max_size=_DEFAULT_MAX_BODY_BYTES)

# Mount routers.
app.include_router(auth.router)
app.include_router(oauth.router)
app.include_router(proxy.router)

logger.info("SafeRoute API initialized (environment=%s)", settings.ENVIRONMENT)


async def shutdown_event() -> None:
    """Close shared resources on application shutdown."""
    from app import database as db_module

    try:
        if db_module.has_http_client() and not db_module.get_http_client().is_closed:
            await asyncio.wait_for(db_module.get_http_client().aclose(), timeout=5.0)
    except asyncio.TimeoutError:
        logger.warning("HTTP client shutdown timed out")
    except Exception:
        logger.warning("HTTP client shutdown failed", exc_info=True)

    try:
        await asyncio.wait_for(close_jwks_client(), timeout=5.0)
    except asyncio.TimeoutError:
        logger.warning("JWKS client shutdown timed out")
    except Exception:
        logger.warning("JWKS client shutdown failed", exc_info=True)


@app.get("/")
async def root() -> JSONResponse:
    """API root with links to documentation and health check."""
    return JSONResponse(
        status_code=200,
        content={
            "service": "SafeRoute API",
            "version": settings.APP_VERSION,
            "status": "running",
            "docs": "/docs",
            "health": "/health",
            "dashboard": "https://darestack.github.io/saferoute-api/",
            "endpoints": {
                "routes": "/v1/routes",
                "proxy": "/v1/r/{slug}",
                "payments": "/v1/payments",
                "webhooks": "/v1/webhooks/paystack",
            },
        },
    )


@app.get("/health")
async def health_check() -> JSONResponse:
    """Check API, database, and cache connectivity.

    Returns:
        dict: Health status with database and cache connectivity checks.
    """
    db_ok = False
    cache_ok = False
    try:
        from app.database import admin, execute_query

        # Read-only connectivity probe — no side effects.
        await execute_query(admin.table("routes").select("id").limit(1))
        db_ok = True
    except Exception as exc:
        logger.error("Health check database probe failed: %s", exc)

    # Cache health check
    try:
        from app.database import cache_get

        # Test L2 cache connectivity with a simple key
        test_key = "__health_check__"
        await cache_get(test_key)
        cache_ok = True
    except Exception as exc:
        logger.error("Health check cache probe failed: %s", exc)

    overall_ok = db_ok and cache_ok
    status_code = 200 if overall_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if overall_ok else "unhealthy",
            "database": "connected" if db_ok else "disconnected",
            "cache": "connected" if cache_ok else "disconnected",
            "service": "SafeRoute API",
        },
    )


# Serve frontend files in development/test environments.
# Mount AFTER all API routes so they take precedence.
if settings.ENVIRONMENT != "production":
    frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
    if os.path.isdir(frontend_path):
        app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
