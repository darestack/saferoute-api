"""SafeRoute API entrypoint.

Configures the FastAPI application with security middleware, CORS, and
trusted host restrictions. Mounts the proxy router so the app is runnable
both locally and on Vercel via the Mangum ASGI handler.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.routes import auth, oauth, proxy

logger = logging.getLogger(__name__)

app = FastAPI(
    title="SafeRoute API",
    description="Secure, Zero-Config Webhook Proxy Shield",
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
# In development we allow all origins for convenience. In production we
# restrict to the known frontend domain to prevent credential theft.
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
# ``*`` is intentional here because Vercel / CDN edge nodes act as proxies
# and the canonical host is enforced at the edge / DNS level.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject standard security headers into every response."""

    async def dispatch(self, request: Request, call_next):
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

    def __init__(self, app, max_size: int = _DEFAULT_MAX_BODY_BYTES):
        """Initialize the middleware.

        Args:
            app: The downstream ASGI app.
            max_size: Maximum allowed request body size in bytes.
        """
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(self, request: Request, call_next):
        """Reject oversized requests before they reach route handlers.

        Args:
            request: The incoming request.
            call_next: The next middleware / route handler.

        Returns:
            A ``413`` JSON response if the body is too large, otherwise the
            normal response from the downstream handler.
        """
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_size:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large"},
            )

        # Also enforce on the actual body for clients that omit or falsify
        # the Content-Length header.
        if request.method in ("POST", "PUT", "PATCH"):
            body = await request.body()
            if len(body) > self.max_size:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large"},
                )

        return await call_next(request)


# Order matters: security headers should be outermost so they apply even
# to error responses from later middleware.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestSizeLimitMiddleware, max_size=_DEFAULT_MAX_BODY_BYTES)

# Mount the proxy router so ``POST /v1/route/{slug}`` is available.
app.include_router(auth.router)
app.include_router(oauth.router)
app.include_router(proxy.router)


@app.get("/")
async def health_check():
    """Return a minimal health-check payload.

    Returns:
        dict: Service name and health status.
    """
    return {"Status": "Healthy", "service": "SafeRoute API Engine"}
