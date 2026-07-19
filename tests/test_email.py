"""Tests for email utilities (disposable detection, rendering, send guard)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import app.utils.email as email_module
from app.utils.email import (
    is_disposable_email,
    send_submission_email,
    _render_submission_email,
)


@pytest.fixture(autouse=True)
def _reset_disposable_cache():
    """Ensure a deterministic disposable-domain set per test."""
    original = email_module._DISPOSABLE_EMAIL_DOMAINS
    email_module._DISPOSABLE_EMAIL_DOMAINS = {"mailinator.com", "tempmail.com"}
    yield
    email_module._DISPOSABLE_EMAIL_DOMAINS = original


class TestDisposableEmail:
    def test_detects_disposable(self):
        assert is_disposable_email("bob@mailinator.com") is True

    def test_allows_normal_domain(self):
        assert is_disposable_email("bob@example.com") is False

    def test_rejects_malformed(self):
        assert is_disposable_email("not-an-email") is False
        assert is_disposable_email("") is False

    def test_case_insensitive(self):
        assert is_disposable_email("Bob@TempMail.com") is True


class TestRenderSubmissionEmail:
    def test_html_escapes_values(self):
        email = _render_submission_email(
            to="a@b.com",
            subject="New submission",
            payload={"name": "<script>alert(1)</script>", "email": "x@y.com"},
            route_name="Contact",
        )
        html_body = email["html"]
        assert "<script>alert(1)</script>" not in html_body
        assert "&lt;script&gt;" in html_body
        assert "Contact" in html_body

    def test_includes_reply_to_when_set(self):
        html_body = _render_submission_email(
            to="a@b.com",
            subject="s",
            payload={"k": "v"},
            route_name="r",
            reply_to="reply@b.com",
        )
        assert html_body["reply_to"] == "reply@b.com"


class TestSendSubmissionEmail:
    @pytest.mark.asyncio
    async def test_skips_when_resend_unconfigured(self):
        with patch.object(email_module.settings, "RESEND_API_KEY", ""):
            ok = await send_submission_email(
                to="a@b.com", subject="s", payload={"k": "v"}, route_name="r"
            )
        assert ok is False

    @pytest.mark.asyncio
    async def test_skips_invalid_recipient(self):
        with patch.object(email_module.settings, "RESEND_API_KEY", "rek"):
            ok = await send_submission_email(
                to="not-an-email", subject="s", payload={"k": "v"}, route_name="r"
            )
        assert ok is False

    @pytest.mark.asyncio
    async def test_sends_on_success(self):
        with (
            patch.object(email_module.settings, "RESEND_API_KEY", "rek"),
            patch("app.utils.email.resend") as mock_resend,
        ):
            mock_resend.Emails.send.return_value = {"id": "email-1"}
            ok = await send_submission_email(
                to="a@b.com", subject="s", payload={"k": "v"}, route_name="r"
            )
        assert ok is True
        mock_resend.Emails.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_permanent_error_not_retried(self):
        from resend.exceptions import ResendError

        with (
            patch.object(email_module.settings, "RESEND_API_KEY", "rek"),
            patch("app.utils.email.resend") as mock_resend,
            patch("app.utils.email.asyncio.sleep", new=AsyncMock()),
        ):
            err = ResendError(
                "422", "invalid_request_error", "bad request", "fix the request"
            )
            err.code = "422"
            mock_resend.Emails.send.side_effect = err
            ok = await send_submission_email(
                to="a@b.com", subject="s", payload={"k": "v"}, route_name="r"
            )
        assert ok is False
        # Permanent (4xx) error -> no retry.
        assert mock_resend.Emails.send.call_count == 1
