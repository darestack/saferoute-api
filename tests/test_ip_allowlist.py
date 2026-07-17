"""Tests for IP allowlist utilities."""

from __future__ import annotations
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.utils.ip_allowlist import is_ip_allowed, require_ip_allowlist


class TestIsIpAllowed:
    """Tests for IP allowlist checking."""

    def test_empty_allowlist_allows_all(self):
        assert is_ip_allowed("192.168.1.1", "") is True
        assert is_ip_allowed("192.168.1.1", "   ") is True

    def test_single_ip_allowed(self):
        assert is_ip_allowed("192.168.1.1", "192.168.1.1") is True

    def test_single_ip_denied(self):
        assert is_ip_allowed("192.168.1.2", "192.168.1.1") is False

    def test_multiple_ips(self):
        assert (
            is_ip_allowed("192.168.1.2", "192.168.1.1, 192.168.1.2 ,10.0.0.1") is True
        )
        assert is_ip_allowed("192.168.1.3", "192.168.1.1, 192.168.1.2") is False

    def test_cidr_allowed(self):
        assert is_ip_allowed("192.168.1.100", "192.168.1.0/24") is True

    def test_cidr_denied(self):
        assert is_ip_allowed("192.168.2.100", "192.168.1.0/24") is False

    def test_invalid_cidr_ignored(self):
        assert is_ip_allowed("192.168.1.1", "invalid/cidr") is False

    def test_ipv6_support(self):
        assert is_ip_allowed("::1", "::1") is True
        assert is_ip_allowed("::2", "::1") is False


class TestRequireIpAllowlist:
    """Tests for IP allowlist dependency."""

    @pytest.mark.asyncio
    @patch("app.utils.ip_allowlist.settings")
    async def test_allowed_ip_passes(self, mock_settings):
        mock_settings.ADMIN_ALLOWED_IPS = "192.168.1.1"
        request = MagicMock()
        request.client.host = "192.168.1.1"

        result = await require_ip_allowlist(request)
        assert result is None

    @pytest.mark.asyncio
    @patch("app.utils.ip_allowlist.settings")
    async def test_denied_ip_raises(self, mock_settings):
        mock_settings.ADMIN_ALLOWED_IPS = "192.168.1.1"
        request = MagicMock()
        request.client.host = "192.168.1.2"

        with pytest.raises(HTTPException) as exc_info:
            await require_ip_allowlist(request)
        assert exc_info.value.status_code == 403
