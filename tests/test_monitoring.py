"""Tests for monitoring and observability utilities."""

from __future__ import annotations
from unittest.mock import patch


from app.monitoring import (
    add_breadcrumb,
    capture_exception_safe,
    init_sentry,
    set_user_context,
)


class TestSentryInit:
    """Tests for Sentry initialization."""

    @patch("app.monitoring.sentry_sdk")
    @patch("app.monitoring.settings")
    def test_init_sentry_with_dsn(self, mock_settings, mock_sentry):
        mock_settings.SENTRY_DSN = "https://test@sentry.io/123"
        mock_settings.ENVIRONMENT = "production"
        mock_settings.is_production = True
        mock_settings.APP_VERSION = "0.7.0"

        init_sentry()

        mock_sentry.init.assert_called_once()
        call_kwargs = mock_sentry.init.call_args[1]
        assert call_kwargs["dsn"] == "https://test@sentry.io/123"
        assert call_kwargs["environment"] == "production"
        assert call_kwargs["release"] == "0.7.0"

    @patch("app.monitoring.sentry_sdk")
    @patch("app.monitoring.settings")
    def test_init_sentry_without_dsn(self, mock_settings, mock_sentry):
        mock_settings.SENTRY_DSN = ""

        init_sentry()

        mock_sentry.init.assert_not_called()


class TestBreadcrumbs:
    """Tests for breadcrumb functions."""

    @patch("app.monitoring.sentry_sdk")
    def test_add_breadcrumb(self, mock_sentry):
        add_breadcrumb("test message", category="test", level="info")

        mock_sentry.add_breadcrumb.assert_called_once()
        call_kwargs = mock_sentry.add_breadcrumb.call_args[1]
        assert call_kwargs["message"] == "test message"
        assert call_kwargs["category"] == "test"
        assert call_kwargs["level"] == "info"


class TestCaptureException:
    """Tests for exception capturing."""

    @patch("app.monitoring.sentry_sdk")
    def test_capture_exception_safe(self, mock_sentry):
        exc = ValueError("test error")
        capture_exception_safe(exc)

        mock_sentry.capture_exception.assert_called_once_with(exc)

    @patch("app.monitoring.sentry_sdk")
    def test_capture_exception_with_context(self, mock_sentry):
        exc = ValueError("test error")
        capture_exception_safe(exc, context={"user_id": "123"})

        assert mock_sentry.capture_exception.called or mock_sentry.push_scope.called


class TestSetUserContext:
    """Tests for user context."""

    @patch("app.monitoring.sentry_sdk")
    def test_set_user_context(self, mock_sentry):
        set_user_context("user-123", email="test@example.com")

        mock_sentry.set_user.assert_called_once_with({
            "id": "user-123",
            "email": "test@example.com",
        })

    @patch("app.monitoring.sentry_sdk")
    def test_set_user_context_no_email(self, mock_sentry):
        set_user_context("user-123")

        mock_sentry.set_user.assert_called_once_with({"id": "user-123"})
