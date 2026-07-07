"""Regression checks for deployment SQL files."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_migration_002_avoids_invalid_constraint_syntax() -> None:
    sql = (ROOT / "migration_002_enhancements.sql").read_text()
    assert "ADD CONSTRAINT IF NOT EXISTS" not in sql


def test_pkce_consume_function_returns_deleted_verifier() -> None:
    schema = (ROOT / "schema.sql").read_text().lower()
    migration = (ROOT / "migration_002_enhancements.sql").read_text().lower()

    assert "return query" in schema
    assert "returning verifier.code_verifier" in schema
    assert "return query" in migration
    assert "returning verifier.code_verifier" in migration


def test_rate_limit_function_uses_atomic_upsert() -> None:
    schema = (ROOT / "schema.sql").read_text().lower()
    assert "on conflict (route_id, ip_address, window_start)" in schema
    assert "public.rate_limits.request_count < p_max_requests" in schema
