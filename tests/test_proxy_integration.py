"""Integration tests for the proxy webhook endpoint."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.proxy import verify_webhook_signature


client = TestClient(app)


class TestProxyWebhook:
    def test_missing_route_returns_404(self):
        with patch("app.routes.proxy.admin") as mock_admin:
            mock_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
            response = client.post("/v1/route/does-not-exist", json={"hello": "world"})
            assert response.status_code == 404

    def test_signature_verification_rejects_invalid_sig(self):
        body = b'{"hello": "world"}'
        assert verify_webhook_signature(body, "sha256=invalid") is False

    def test_signature_verification_accepts_valid_sig(self):
        from app.config import settings

        body = b'{"hello": "world"}'
        expected = "sha256=" + __import__(
            "hashlib"
        ).sha256(
            (settings.WEBHOOK_SECRET + body.decode("utf-8", errors="replace")).encode("utf-8")
        ).hexdigest()
        assert verify_webhook_signature(body, expected) is True
