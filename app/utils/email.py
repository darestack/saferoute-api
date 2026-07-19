"""Email notification utilities for SafeRoute API.

Uses Resend for transactional email delivery. Supports notifications for:
- New form submissions
- Failed deliveries
- Daily digests
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
from typing import Any

import resend
from resend.exceptions import ResendError

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Resend email client (v2.x API)
# ---------------------------------------------------------------------------
if settings.RESEND_API_KEY:
    resend.api_key = settings.RESEND_API_KEY

# ---------------------------------------------------------------------------
# Disposable email detection
# ---------------------------------------------------------------------------
_DISPOSABLE_EMAIL_DOMAINS: set[str] = set()
"""Runtime-loaded set of disposable email domains.

Loaded from ``DISPOSABLE_EMAIL_LIST_URL`` if set, otherwise falls back to
an embedded minimal list. The cache is refreshed on every ``settings``
reload (typically only on startup).
"""

_DISPOSABLE_EMAIL_LIST_URL = os.environ.get(
    "DISPOSABLE_EMAIL_LIST_URL",
    "https://raw.githubusercontent.com/ivolo/disposable-email-domains/master/index.json",
)
"""Source for disposable email domains. Set to empty string to disable."""


def _load_disposable_domains_sync() -> None:
    """Synchronously load disposable email domains from the embedded JSON file.

    This is the primary loading path; it requires no network I/O and works
    in any context (sync, async, tests, startup). Idempotent: safe to call
    multiple times; subsequent calls are no-ops once the set is populated.
    """
    global _DISPOSABLE_EMAIL_DOMAINS
    if _DISPOSABLE_EMAIL_DOMAINS:
        return
    try:
        from pathlib import Path

        json_path = Path(__file__).with_name("disposable_domains.json")
        if json_path.exists():
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                _DISPOSABLE_EMAIL_DOMAINS = {
                    domain.strip().lower()
                    for domain in data
                    if isinstance(domain, str) and domain.strip()
                }
                logger.info(
                    "Loaded %d disposable email domains from embedded file",
                    len(_DISPOSABLE_EMAIL_DOMAINS),
                )
                return
    except Exception:
        logger.exception("Failed to load embedded disposable email domains")
    _DISPOSABLE_EMAIL_DOMAINS = set()


def _ensure_disposable_domains_loaded() -> None:
    """Load disposable email domains if not already loaded.

    Uses synchronous file I/O so it works in both sync and async contexts
    without requiring an event loop.
    """
    _load_disposable_domains_sync()


def is_disposable_email(email: str) -> bool:
    """Check if an email address uses a disposable domain.

    Args:
        email: The email address to check.

    Returns:
        ``True`` if the domain is in the disposable list, ``False`` otherwise.
    """
    _ensure_disposable_domains_loaded()
    if not email or "@" not in email:
        return False
    domain = email.split("@")[-1].strip().lower()
    return domain in _DISPOSABLE_EMAIL_DOMAINS


# ---------------------------------------------------------------------------
# Resend email client
# ---------------------------------------------------------------------------
def _is_resend_configured() -> bool:
    """Return True if Resend API key is configured."""
    return bool(settings.RESEND_API_KEY)


# ---------------------------------------------------------------------------
# Email rendering
# ---------------------------------------------------------------------------
def _render_submission_email(
    to: str,
    subject: str,
    payload: dict[str, Any],
    route_name: str,
    reply_to: str = "",
) -> dict[str, Any]:
    """Render a simple HTML email for a new form submission.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        payload: Parsed form payload.
        route_name: Human-readable route name.
        reply_to: Optional reply-to address.

    Returns:
        Resend email payload dict.
    """
    _html_escape = html.escape
    rows = "".join(
        f"<tr><td><strong>{_html_escape(str(key))}</strong></td>"
        f"<td>{_html_escape(str(value))}</td></tr>"
        for key, value in payload.items()
    )

    email_html = f"""
    <html>
      <body>
        <h2>New submission: {route_name}</h2>
        <table border="1" cellpadding="6" cellspacing="0">
          {rows}
        </table>
      </body>
    </html>
    """

    email: dict[str, Any] = {
        "from": settings.EMAIL_FROM,
        "to": to,
        "subject": subject,
        "html": email_html,
    }
    if reply_to:
        email["reply_to"] = reply_to

    return email


# ---------------------------------------------------------------------------
# Email delivery with retry
# ---------------------------------------------------------------------------
_EMAIL_RETRY_ATTEMPTS = settings.EMAIL_RETRY_ATTEMPTS
"""Maximum attempts for email delivery."""

_EMAIL_RETRY_BACKOFF_BASE = settings.EMAIL_RETRY_BACKOFF_BASE
"""Base backoff in seconds between email retries."""


async def _send_with_retry(email: dict[str, Any]) -> bool:
    """Send an email with exponential backoff retry.

    Args:
        email: Resend email payload dict.

    Returns:
        ``True`` if the email was accepted by Resend, ``False`` otherwise.
    """
    if not _is_resend_configured():
        return False

    for attempt in range(1, _EMAIL_RETRY_ATTEMPTS + 1):
        try:
            # Resend 2.x SDK uses module-level functions; run in thread pool
            # to avoid blocking the event loop.
            result = await asyncio.to_thread(resend.Emails.send, email)
            logger.info(
                "Submission email sent",
                extra={
                    "to": email.get("to"),
                    "subject": email.get("subject"),
                    "id": result.get("id"),
                    "attempt": attempt,
                },
            )
            return True
        except ResendError as exc:
            # Permanent API errors (auth, validation, etc.) should not be retried.
            code = getattr(exc, "code", None)
            if isinstance(code, str) and code.isdigit() and 400 <= int(code) < 500:
                logger.error(
                    "Permanent Resend error (status=%s) sending to %s: %s",
                    code,
                    email.get("to"),
                    exc,
                )
                return False
            if isinstance(code, int) and 400 <= code < 500:
                logger.error(
                    "Permanent Resend error (status=%s) sending to %s: %s",
                    code,
                    email.get("to"),
                    exc,
                )
                return False
            if attempt < _EMAIL_RETRY_ATTEMPTS:
                backoff = _EMAIL_RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "Email send attempt %d failed, retrying in %.1fs: %s",
                    attempt,
                    backoff,
                    exc,
                )
                await asyncio.sleep(backoff)
            else:
                logger.exception(
                    "Email send failed after %d attempts to %s",
                    _EMAIL_RETRY_ATTEMPTS,
                    email.get("to"),
                )
        except Exception as exc:
            if attempt < _EMAIL_RETRY_ATTEMPTS:
                backoff = _EMAIL_RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "Email send attempt %d failed, retrying in %.1fs: %s",
                    attempt,
                    backoff,
                    exc,
                )
                await asyncio.sleep(backoff)
            else:
                logger.exception(
                    "Email send failed after %d attempts to %s",
                    _EMAIL_RETRY_ATTEMPTS,
                    email.get("to"),
                )

    return False


async def send_submission_email(
    to: str,
    subject: str,
    payload: dict[str, Any],
    route_name: str,
    reply_to: str = "",
) -> bool:
    """Send a form-submission notification email via Resend.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        payload: Parsed form payload.
        route_name: Human-readable route name.
        reply_to: Optional reply-to address.

    Returns:
        ``True`` if the email was accepted by Resend, ``False`` otherwise.
    """
    if not _is_resend_configured():
        return False

    # Basic email format validation to avoid wasting Resend API calls.
    email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    if not to or not email_re.match(to):
        logger.warning("Invalid recipient email address, skipping send: %s", to)
        return False

    try:
        email = _render_submission_email(to, subject, payload, route_name, reply_to)
        return await _send_with_retry(email)
    except Exception:
        logger.exception("Failed to queue submission email to %s", to)
        return False
