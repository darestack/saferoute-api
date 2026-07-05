"""Centralized logging configuration for SafeRoute API.

Provides two profiles:

* **development** — human-readable, colored output to stderr.
* **production** — JSON-lines format suitable for log aggregation services.

Usage::

    from app.logging_config import configure_logging
    configure_logging(environment="production")
"""

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

# Context variable for request-scoped correlation ID.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)


class RequestIdFilter(logging.Filter):
    """Inject the current request ID into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects for production use."""

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as a JSON string.

        Args:
            record: The log record to format.

        Returns:
            A single-line JSON string.
        """
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = getattr(record, "request_id", "")
        if request_id:
            log_entry["request_id"] = request_id

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


class ReadableFormatter(logging.Formatter):
    """Human-readable log format for development."""

    FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s"

    def __init__(self) -> None:
        super().__init__(fmt=self.FORMAT, datefmt="%H:%M:%S")


def configure_logging(environment: str = "development") -> None:
    """Configure the root logger based on the deployment environment.

    Args:
        environment: ``"development"`` for readable output, anything else
            (typically ``"production"``) for JSON-lines output.
    """
    root_logger = logging.getLogger()

    # Clear existing handlers to avoid duplicates on re-import.
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)

    if environment == "development":
        handler.setFormatter(ReadableFormatter())
        root_logger.setLevel(logging.DEBUG)
    else:
        handler.setFormatter(JSONFormatter())
        root_logger.setLevel(logging.INFO)

    # Attach request ID filter so every record carries the correlation ID.
    root_logger.addFilter(RequestIdFilter())
    root_logger.addHandler(handler)

    # Suppress noisy third-party loggers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("supabase").setLevel(logging.WARNING)
    logging.getLogger("hpack").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
