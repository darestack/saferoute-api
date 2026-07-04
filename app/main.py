"""SafeRoute API entrypoint.

Configures the FastAPI application with security middleware, CORS, and
trusted host restrictions. Mounts the proxy router so the app is runnable
both locally and on Vercel via the Mangum ASGI handler.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.routes import proxy

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.ENVIRONMENT == "development" else ["https://saferouteapi.app"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
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
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


# ---------------------------------------------------------------------------
# Request size limit
# ---------------------------------------------------------------------------
class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests with bodies larger than the configured limit."""

    def __init__(self, app, max_size: int = 1024 * 1024):
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
        if request.headers.get("content-length"):
            if int(request.headers["content-length"]) > self.max_size:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large"},
                )
        return await call_next(request)


# Order matters: security headers should be outermost so they apply even
# to error responses from later middleware.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestSizeLimitMiddleware, max_size=1024 * 1024)

# Mount the proxy router so ``POST /v1/route/{slug}`` is available.
app.include_router(proxy.router)


@app.get("/")
async def health_check():
    """Return a minimal health-check payload.

    Returns:
        dict: Service name and health status.
    """
    return {"Status": "Healthy", "service": "SafeRoute API Engine"}
