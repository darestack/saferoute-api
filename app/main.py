"""SafeRoute API entrypoint.

Configures the FastAPI application with security middleware, CORS, and
trusted host restrictions. Mounts the proxy router so the app is runnable
both locally and on Vercel via the Mangum ASGI handler.
"""

import logging
import uuid

from typing import Callable, Awaitable, Any
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.logging_config import configure_logging, request_id_var

# Configure logging before any other imports that use loggers.
configure_logging(environment=settings.ENVIRONMENT)

from app.routes import auth, oauth, proxy  # noqa: E402

logger = logging.getLogger(__name__)

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
        request_id = request.headers.get(
            "X-Request-ID", str(uuid.uuid4())
        )
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
_ALLOWED_HEADERS_PRODUCTION = ["Authorization", "Content-Type", "X-API-Key"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        ["*"]
        if settings.ENVIRONMENT == "development"
        else ["https://saferouteapi.app"]
    ),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=(
        ["*"]
        if settings.ENVIRONMENT == "development"
        else _ALLOWED_HEADERS_PRODUCTION
    ),
    max_age=600,
)

# ---------------------------------------------------------------------------
# Trusted host
# ---------------------------------------------------------------------------
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject standard security headers into every response."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )
        response.headers["Content-Security-Policy"] = "default-src 'none'"
        return response


# ---------------------------------------------------------------------------
# Request size limit
# ---------------------------------------------------------------------------
_DEFAULT_MAX_BODY_BYTES = 1024 * 1024  # 1 MiB


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests with bodies larger than the configured limit.

    Checks both the ``Content-Length`` header (cheap, up-front rejection)
    and the actual body length (to prevent clients that omit or lie about
    the header).
    """

    def __init__(self, app: Any, max_size: int = _DEFAULT_MAX_BODY_BYTES) -> None:
        """Initialize the middleware.

        Args:
            app: The downstream ASGI app.
            max_size: Maximum allowed request body size in bytes.
        """
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Reject oversized requests before they reach route handlers."""
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_size:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large"},
            )

        if request.method in ("POST", "PUT", "PATCH"):
            body = await request.body()
            if len(body) > self.max_size:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large"},
                )

        return await call_next(request)


# Middleware ordering: outermost runs first.
# Request ID → Security headers → Size limit → route handlers.
app.add_middleware(RequestIDMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestSizeLimitMiddleware, max_size=_DEFAULT_MAX_BODY_BYTES)

# Mount routers.
app.include_router(auth.router)
app.include_router(oauth.router)
app.include_router(proxy.router)

logger.info("SafeRoute API initialized (environment=%s)", settings.ENVIRONMENT)


@app.get("/")
async def health_check() -> dict[str, str]:
    """Return a minimal health-check payload.

    Returns:
        dict: Service name and health status.
    """
    return {"Status": "Healthy", "service": "SafeRoute API Engine"}
