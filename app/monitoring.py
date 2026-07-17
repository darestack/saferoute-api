"""Monitoring and observability for SafeRoute API.

Integrates Sentry for error tracking and OpenTelemetry for distributed tracing.
"""

from __future__ import annotations
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_sentry_available = False
try:
    import sentry_sdk

    _sentry_available = True
except ImportError:
    logger.warning("sentry-sdk not installed; Sentry monitoring disabled")

_otel_available = False
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    _otel_available = True
except ImportError:
    logger.warning("opentelemetry packages not installed; tracing disabled")


def init_sentry() -> None:
    """Initialize Sentry SDK if DSN is configured."""
    if not _sentry_available:
        return

    sentry_dsn = getattr(settings, "SENTRY_DSN", "")
    if not sentry_dsn:
        logger.info("SENTRY_DSN not set; Sentry monitoring disabled")
        return

    try:
        sentry_sdk.init(
            dsn=sentry_dsn,
            environment=settings.ENVIRONMENT,
            traces_sample_rate=0.1 if settings.is_production else 1.0,
            profiles_sample_rate=0.1 if settings.is_production else 1.0,
            release=getattr(settings, "APP_VERSION", "unknown"),
            send_default_pii=False,
        )
        logger.info("Sentry initialized (environment=%s)", settings.ENVIRONMENT)
    except Exception as exc:
        logger.warning("Failed to initialize Sentry: %s", exc)


def init_opentelemetry() -> None:
    """Initialize OpenTelemetry tracing if enabled."""
    if not _otel_available:
        return

    if not getattr(settings, "OTEL_ENABLED", False):
        logger.info("OpenTelemetry disabled; set OTEL_ENABLED=true to enable")
        return

    try:
        provider = TracerProvider()
        processor = BatchSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        logger.info("OpenTelemetry tracing initialized")
    except Exception as exc:
        logger.warning("Failed to initialize OpenTelemetry: %s", exc)


def init_monitoring() -> None:
    """Initialize all monitoring backends."""
    init_sentry()
    init_opentelemetry()


def capture_exception_safe(
    exc: Exception, context: dict[str, Any] | None = None
) -> None:
    """Capture an exception to Sentry with optional context."""
    if not _sentry_available:
        return

    try:
        if context:
            with sentry_sdk.push_scope() as scope:
                for key, value in context.items():
                    scope.set_context(key, value)
                sentry_sdk.capture_exception(exc)
        else:
            sentry_sdk.capture_exception(exc)
    except Exception:
        pass


def capture_message_safe(message: str, level: str = "info") -> None:
    """Capture a message to Sentry."""
    if not _sentry_available:
        return

    try:
        sentry_sdk.capture_message(message, level=level)  # type: ignore[arg-type]
    except Exception:
        pass


def set_user_context(user_id: str, email: str | None = None) -> None:
    """Set user context for Sentry events."""
    if not _sentry_available:
        return

    try:
        user_data: dict[str, str] = {"id": user_id}
        if email:
            user_data["email"] = email
        sentry_sdk.set_user(user_data)
    except Exception:
        pass


def add_breadcrumb(
    message: str,
    category: str = "custom",
    level: str = "info",
    data: dict[str, Any] | None = None,
) -> None:
    """Add a breadcrumb to Sentry for debugging."""
    if not _sentry_available:
        return

    try:
        sentry_sdk.add_breadcrumb(
            message=message,
            category=category,
            level=level,
            data=data or {},
        )
    except Exception:
        pass
