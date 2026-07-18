"""Tests for monitoring module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestInitSentry:
    """Tests for Sentry initialization."""

    def test_skips_when_sentry_not_installed(self):
        """Should not crash when sentry-sdk is not available."""
        with patch("app.monitoring._sentry_available", False):
            from app.monitoring import init_sentry

            init_sentry()  # Should not raise

    def test_skips_when_no_dsn(self):
        """Should not initialize when SENTRY_DSN is not set."""
        mock_settings = MagicMock()
        mock_settings.SENTRY_DSN = ""
        mock_settings.ENVIRONMENT = "test"
        mock_settings.is_production = False
        mock_settings.APP_VERSION = "1.0.0"

        with (
            patch("app.monitoring._sentry_available", True),
            patch("app.monitoring.settings", mock_settings),
            patch("app.monitoring.sentry_sdk") as mock_sdk,
        ):
            from app.monitoring import init_sentry

            init_sentry()
            mock_sdk.init.assert_not_called()

    def test_initializes_with_dsn(self):
        """Should initialize Sentry when DSN is configured."""
        mock_settings = MagicMock()
        mock_settings.SENTRY_DSN = "https://test@sentry.io/123"
        mock_settings.ENVIRONMENT = "production"
        mock_settings.is_production = True
        mock_settings.APP_VERSION = "1.0.0"

        with (
            patch("app.monitoring._sentry_available", True),
            patch("app.monitoring.settings", mock_settings),
            patch("app.monitoring.sentry_sdk") as mock_sdk,
        ):
            from app.monitoring import init_sentry

            init_sentry()
            mock_sdk.init.assert_called_once()

    def test_handles_init_error_gracefully(self):
        """Should not crash if Sentry init raises."""
        mock_settings = MagicMock()
        mock_settings.SENTRY_DSN = "https://test@sentry.io/123"
        mock_settings.ENVIRONMENT = "test"
        mock_settings.is_production = False
        mock_settings.APP_VERSION = "1.0.0"

        with (
            patch("app.monitoring._sentry_available", True),
            patch("app.monitoring.settings", mock_settings),
            patch(
                "app.monitoring.sentry_sdk.init", side_effect=Exception("Init failed")
            ),
        ):
            from app.monitoring import init_sentry

            init_sentry()  # Should not raise


class TestInitOpentelemetry:
    """Tests for OpenTelemetry initialization."""

    def test_skips_when_otel_not_installed(self):
        """Should not crash when opentelemetry packages are not available."""
        with patch("app.monitoring._otel_available", False):
            from app.monitoring import init_opentelemetry

            init_opentelemetry()  # Should not raise

    def test_skips_when_disabled(self):
        """Should not initialize when OTEL_ENABLED is False."""
        mock_settings = MagicMock()
        mock_settings.OTEL_ENABLED = False

        with (
            patch("app.monitoring._otel_available", True),
            patch("app.monitoring.settings", mock_settings),
        ):
            from app.monitoring import init_opentelemetry

            init_opentelemetry()


class TestCaptureExceptionSafe:
    """Tests for safe exception capture."""

    def test_skips_when_sentry_not_available(self):
        """Should not crash when sentry-sdk is not available."""
        with patch("app.monitoring._sentry_available", False):
            from app.monitoring import capture_exception_safe

            capture_exception_safe(Exception("test"))

    def test_captures_exception(self):
        """Should capture exception to Sentry."""
        mock_sentry = MagicMock()
        with (
            patch("app.monitoring._sentry_available", True),
            patch("app.monitoring.sentry_sdk", mock_sentry),
        ):
            from app.monitoring import capture_exception_safe

            exc = Exception("test error")
            capture_exception_safe(exc)
            mock_sentry.capture_exception.assert_called_once_with(exc)

    def test_captures_exception_with_context(self):
        """Should capture exception with context."""
        mock_sentry = MagicMock()
        with (
            patch("app.monitoring._sentry_available", True),
            patch("app.monitoring.sentry_sdk", mock_sentry),
        ):
            from app.monitoring import capture_exception_safe

            exc = Exception("test error")
            capture_exception_safe(exc, {"key": "value"})
            mock_sentry.capture_exception.assert_called_once_with(exc)

    def test_handles_capture_error_gracefully(self):
        """Should not crash if Sentry capture raises."""
        mock_sentry = MagicMock()
        mock_sentry.capture_exception.side_effect = Exception("Capture failed")

        with (
            patch("app.monitoring._sentry_available", True),
            patch("app.monitoring.sentry_sdk", mock_sentry),
        ):
            from app.monitoring import capture_exception_safe

            capture_exception_safe(Exception("test"))  # Should not raise


class TestCaptureMessageSafe:
    """Tests for safe message capture."""

    def test_skips_when_sentry_not_available(self):
        """Should not crash when sentry-sdk is not available."""
        with patch("app.monitoring._sentry_available", False):
            from app.monitoring import capture_message_safe

            capture_message_safe("test message")

    def test_captures_message(self):
        """Should capture message to Sentry."""
        mock_sentry = MagicMock()
        with (
            patch("app.monitoring._sentry_available", True),
            patch("app.monitoring.sentry_sdk", mock_sentry),
        ):
            from app.monitoring import capture_message_safe

            capture_message_safe("test message", "warning")
            mock_sentry.capture_message.assert_called_once_with(
                "test message", level="warning"
            )


class TestSetUserContext:
    """Tests for user context setting."""

    def test_skips_when_sentry_not_available(self):
        """Should not crash when sentry-sdk is not available."""
        with patch("app.monitoring._sentry_available", False):
            from app.monitoring import set_user_context

            set_user_context("user-123")

    def test_sets_user_context(self):
        """Should set user context in Sentry."""
        mock_sentry = MagicMock()
        with (
            patch("app.monitoring._sentry_available", True),
            patch("app.monitoring.sentry_sdk", mock_sentry),
        ):
            from app.monitoring import set_user_context

            set_user_context("user-123", "test@example.com")
            mock_sentry.set_user.assert_called_once_with(
                {
                    "id": "user-123",
                    "email": "test@example.com",
                }
            )

    def test_sets_user_context_without_email(self):
        """Should set user context without email."""
        mock_sentry = MagicMock()
        with (
            patch("app.monitoring._sentry_available", True),
            patch("app.monitoring.sentry_sdk", mock_sentry),
        ):
            from app.monitoring import set_user_context

            set_user_context("user-123")
            mock_sentry.set_user.assert_called_once_with({"id": "user-123"})


class TestAddBreadcrumb:
    """Tests for breadcrumb addition."""

    def test_skips_when_sentry_not_available(self):
        """Should not crash when sentry-sdk is not available."""
        with patch("app.monitoring._sentry_available", False):
            from app.monitoring import add_breadcrumb

            add_breadcrumb("test")

    def test_adds_breadcrumb(self):
        """Should add breadcrumb to Sentry."""
        mock_sentry = MagicMock()
        with (
            patch("app.monitoring._sentry_available", True),
            patch("app.monitoring.sentry_sdk", mock_sentry),
        ):
            from app.monitoring import add_breadcrumb

            add_breadcrumb("test message", "http", "info", {"url": "/test"})
            mock_sentry.add_breadcrumb.assert_called_once_with(
                message="test message",
                category="http",
                level="info",
                data={"url": "/test"},
            )
