"""Additional tests for PKCE store/retrieve functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.utils.pkce import store_pkce_verifier, retrieve_and_delete_pkce_verifier


class TestStorePkceVerifier:
    """Tests for store_pkce_verifier function."""

    @pytest.mark.asyncio
    async def test_stores_verifier_successfully(self):
        """Should store PKCE verifier in database."""
        mock_admin = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [{"id": 1}]
        mock_admin.table.return_value.insert.return_value.execute.return_value = (
            mock_result
        )

        with patch("app.database.execute_query", return_value=mock_result):
            await store_pkce_verifier(mock_admin, "challenge", "verifier")
            # No exception means success

    @pytest.mark.asyncio
    async def test_raises_on_storage_failure(self):
        """Should raise exception when storage fails."""
        mock_admin = MagicMock()

        with patch("app.database.execute_query", side_effect=Exception("DB error")):
            with pytest.raises(Exception, match="DB error"):
                await store_pkce_verifier(mock_admin, "challenge", "verifier")


class TestRetrieveAndDeletePkceVerifier:
    """Tests for retrieve_and_delete_pkce_verifier function."""

    @pytest.mark.asyncio
    async def test_retrieves_verifier_successfully(self):
        """Should retrieve and delete PKCE verifier."""
        mock_admin = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [{"code_verifier": "test-verifier"}]
        mock_admin.rpc.return_value.execute.return_value = mock_result

        with patch("app.database.execute_query", return_value=mock_result):
            verifier = await retrieve_and_delete_pkce_verifier(mock_admin, "challenge")
            assert verifier == "test-verifier"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        """Should return None when verifier is not found."""
        mock_admin = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []
        mock_admin.rpc.return_value.execute.return_value = mock_result

        with patch("app.database.execute_query", return_value=mock_result):
            verifier = await retrieve_and_delete_pkce_verifier(mock_admin, "challenge")
            assert verifier is None

    @pytest.mark.asyncio
    async def test_returns_none_on_rpc_failure(self):
        """Should return None when RPC call fails."""
        mock_admin = MagicMock()

        with patch("app.database.execute_query", side_effect=Exception("RPC error")):
            verifier = await retrieve_and_delete_pkce_verifier(mock_admin, "challenge")
            assert verifier is None
