"""Email notification utilities for SafeRoute API.

Uses Resend for transactional email delivery. Supports notifications for:
- New form submissions
- Failed deliveries
- Daily digests
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from resend import Resend

from app.config import settings

logger = logging.getLogger(__name__)

_resend_client = None


def _get_resend_client() -> Optional[Resend]:
    global _resend_client
    if _resend_client is None:
        if not settings.RESEND_API_KEY:
            return None
        _resend_client = Resend(api_key=settings.RESEND_API_KEY)
    return _resend_client


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
    rows = "".join(
        f"<tr><td><strong>{key}</strong></td><td>{value}</td></tr>"
        for key, value in payload.items()
    )

    html = f"""
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
        "html": html,
    }
    if reply_to:
        email["reply_to"] = reply_to

    return email


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
    if not settings.RESEND_API_KEY:
        return False

    try:
        client = _get_resend_client()
        if client is None:
            return False
        email = _render_submission_email(to, subject, payload, route_name, reply_to)
        result = client.emails.send(email)
        logger.info(
            "Submission email sent",
            extra={"to": to, "subject": subject, "id": result.get("id")},
        )
        return True
    except Exception:
        logger.exception("Failed to send submission email to %s", to)
        return False
