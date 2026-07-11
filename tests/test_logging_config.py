"""Tests for logging configuration."""

import json
import logging

from app.logging_config import configure_logging, JSONFormatter


class TestJSONFormatter:
    """Tests for the production JSON log formatter."""
    def test_formats_as_json(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=None,
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "Test message"
        assert "timestamp" in parsed

    def test_includes_request_id(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=None,
            exc_info=None,
        )
        record.request_id = "req-123"
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["request_id"] == "req-123"


class TestJSONFormatterTimestamp:
    """The emitted timestamp must reflect the event time, not emit time."""

    def test_timestamp_uses_record_created(self):
        from datetime import datetime, timezone

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=None,
            exc_info=None,
        )
        expected = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        output = JSONFormatter().format(record)
        assert json.loads(output)["timestamp"] == expected


class TestConfigureLogging:
    """Tests for logging configuration setup."""

    def test_development_sets_debug(self):
        configure_logging(environment="development")
        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_production_sets_info(self):
        configure_logging(environment="production")
        root = logging.getLogger()
        assert root.level == logging.INFO

    def test_suppresses_httpx(self):
        configure_logging(environment="production")
        httpx_logger = logging.getLogger("httpx")
        assert httpx_logger.level == logging.WARNING


class TestRequestIdFilter:
    """Tests for request ID propagation into log records."""

    def test_filter_adds_request_id(self):
        from app.logging_config import RequestIdFilter, request_id_var

        configure_logging(environment="production")
        request_id_var.set("req-abc-123")
        filter_ = RequestIdFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello",
            args=None,
            exc_info=None,
        )
        assert filter_.filter(record) is True
        assert getattr(record, "request_id", None) == "req-abc-123"
        request_id_var.set("")
