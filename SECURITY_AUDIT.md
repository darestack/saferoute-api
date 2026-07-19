# SafeRoute API — Security Audit Report

Date: 2026-07-18
Auditor: Automated baseline audit

## Summary

| Severity | Count | Status |
|----------|-------|--------|
| Critical | 0 | None found |
| High | 1 | Remediated |
| Medium | 2 | Documented / Mitigated |
| Low | 1 | Documented |

## Findings

### HIGH-001: security.txt not served by application
- **File**: `security.txt`
- **Issue**: The repository contained a `security.txt` file at the project root per RFC 9116, but the FastAPI application did not serve it at `/.well-known/security.txt` or `/security.txt`, making it inaccessible to automated security tools and bug bounty researchers.
- **Remediation**: Added `GET /.well-known/security.txt` and `GET /security.txt` endpoints in `app/main.py`. Added both paths to the CSP `_ALLOWED_PATHS` set so the file is reachable and permitted by content-security-policy.

### MEDIUM-001: Weak default secrets in .env.example
- **File**: `.env.example`
- **Issue**: Example environment variables contain weak placeholder values (`API_KEY_SALT=dev-salt-change-in-production`, `WEBHOOK_SECRET=dev-secret-change-in-production`). An operator who copies `.env.example` to `.env` without changing these values would run the application with trivially guessable secrets.
- **Mitigation**: The application fails closed in production (`config.py:115-159`) and validates that `API_KEY_SALT`, `ENCRYPTION_KEY`, and `WEBHOOK_SECRET` are at least 16–32 characters. This prevents accidental startup with weak values, but the `.env.example` file itself should be updated to use stronger placeholders in a follow-up change.
- **Recommendation**: Update `.env.example` placeholders to 32+ character strings that resemble real secrets.

### MEDIUM-002: pyproject.toml version drift
- **File**: `pyproject.toml`
- **Issue**: `pyproject.toml` pins `version = "0.1.0"` while the root `package.json` and `app/config.py` both use `0.7.0`. This can confuse dependency managers and release tooling.
- **Mitigation**: The `standard-version` configuration now bumps `pyproject.toml` via the `.versionrc.json` updater, so the version will stay in sync during releases.
- **Recommendation**: Manually align `pyproject.toml` to `0.7.0` immediately to prevent confusion during the current release cycle.

### LOW-001: In-memory caches not shared across workers
- **File**: `app/main.py`, `app/routes/auth.py`, `app/services/route_cache.py`
- **Issue**: The L1 in-memory caches (`_user_cache`, route cache, rate-limit cache) are process-local. If the deployment scales beyond a single Uvicorn worker, caches become inconsistent, which can cause stale configs and rate-limit drift.
- **Mitigation**: The application logs a warning at startup when `WORKERS != 1` (`main.py:58-64`). The current deployment target (Vercel) uses a single worker by default, so this is low risk in production.
- **Recommendation**: When scaling horizontally, migrate caches to Redis or use the existing L2 PostgreSQL cache table as the single source of truth.

## Recommendations

1. Update `.env.example` placeholders to stronger values (MEDIUM-001).
2. Align `pyproject.toml` version to `0.7.0` (MEDIUM-002).
3. Consider adding rate-limit response headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`) for client visibility.
4. Add `Referrer-Policy: strict-origin-when-cross-origin` (already present) and ensure no internal paths leak in `detail` messages (already protected by `safe_error_detail`).

## Compliance Notes

- The application enforces HTTPS via `Strict-Transport-Security` in production.
- Secrets are never logged; `safe_error_detail` redacts database URLs, IPs, and file paths in production responses.
- All internal endpoints (`/internal/...`) are gated by `compare_digest` of shared secrets.
- Admin endpoints are additionally IP-allowlisted (`utils/ip_allowlist.py`).
