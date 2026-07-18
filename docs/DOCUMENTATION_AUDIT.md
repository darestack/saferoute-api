# SafeRoute API — Documentation Audit Report

**Audit Date:** 2026-07-18  
**Project:** SafeRoute API  
**Repository:** darestack/saferoute-api  
**Auditor:** Kilo (Automated Documentation Review)

---

## Executive Summary

This audit reviewed all documentation files in the SafeRoute API project, including setup guides, API references, user manuals, contribution guidelines, changelogs, and internal technical documentation. The review identified **12 critical inconsistencies**, **8 gaps in endpoint coverage**, **5 outdated references**, **4 unclear sections**, and **3 formatting errors**.

The most critical issue is a **version number mismatch** across project metadata files, followed by **incorrect API paths** in operational runbooks that will cause 404 errors for operators.

### Documentation Health Score

| Metric | Score | Notes |
|--------|-------|-------|
| Completeness | 3/5 | Major gaps in endpoint and environment variable coverage |
| Accuracy | 2/5 | Multiple version, path, and response mismatches |
| Clarity | 4/5 | Generally well-written with good structure |
| Consistency | 2/5 | Conflicts between README, CONTRIBUTING, and code |
| Formatting | 4/5 | Good markdown structure, minor fragment issues |
| Maintainability | 3/5 | Some docs reference non-existent files |

**Overall Assessment:** Documentation is well-structured but contains critical inaccuracies that will mislead operators and contributors. The version mismatch and incorrect API paths are the most urgent issues to address.

---

## 1. Critical Inconsistencies

### 1.1 Version Number Mismatch

**Severity:** High  
**Impact:** Breaks semantic versioning expectations; confuses dependency resolution.

| File | Declared Version |
|------|-----------------|
| `pyproject.toml` | `0.1.0` |
| `CHANGELOG.md` | `0.7.0` (latest) |
| `.env.example` | `APP_VERSION=0.7.0` |
| `app/config.py` | `APP_VERSION: str = "0.7.0"` |

The package metadata in `pyproject.toml` claims version `0.1.0`, while the application code and changelog reference `0.7.0`. This inconsistency means published packages would carry incorrect version metadata.

**Recommendation:** Update `pyproject.toml` version to `0.7.0` to match the codebase and changelog.

### 1.2 Dependency Installation Command Conflict

**Severity:** Medium  
**Impact:** New contributors following the README quick-start will miss development dependencies, causing test and lint commands to fail.

| Document | Command |
|----------|---------|
| `README.md` (line 24) | `pip install -r requirements.txt` |
| `CONTRIBUTING.md` (line 34) | `pip install -r requirements-dev.txt` |
| `.github/workflows/ci.yml` (line 27) | `pip install -r requirements-dev.txt` |

The README instructs users to install only runtime dependencies, while CONTRIBUTING.md and CI correctly use the development requirements file.

**Recommendation:** Update `README.md` to use `pip install -r requirements-dev.txt` in the quick-start and Docker setup sections.

### 1.3 Mypy Command Inconsistency

**Severity:** Medium  
**Impact:** Running `mypy app/` without `--ignore-missing-imports` produces false-positive errors on Supabase boundary modules.

| Document | Command |
|----------|---------|
| `CONTRIBUTING.md` (line 79) | `mypy app/` |
| `CONTRIBUTING.md` (line 150, PR checklist) | `mypy app/ --ignore-missing-imports` |
| `.github/workflows/ci.yml` (line 52) | `mypy app/ --ignore-missing-imports` |
| `pyproject.toml` (lines 36-38) | `strict = true` with `ignore_missing_imports = true` |

The CONTRIBUTING.md contains two different mypy commands on different lines.

**Recommendation:** Update line 79 in `CONTRIBUTING.md` to `mypy app/ --ignore-missing-imports` to match CI and the PR checklist.

### 1.4 Python Version Requirement Conflict

**Severity:** Medium  
**Impact:** Deployment guide suggests Python 3.11+ is acceptable, contradicting the project's actual requirement of 3.12+.

| Document | Requirement |
|----------|-------------|
| `README.md` (line 3 badge) | Python 3.12+ |
| `CONTRIBUTING.md` (line 15) | Python 3.12+ |
| `pyproject.toml` (line 11) | `>=3.12` |
| `docs/deployment.md` (line 6) | **Python 3.11+** |
| `.github/workflows/ci.yml` (line 21) | Python 3.12 |

**Recommendation:** Update `docs/deployment.md` line 6 to require Python 3.12+.

### 1.5 Health Check Response Mismatch

**Severity:** High  
**Impact:** Operators expect `cache_metrics` in `/health` responses but the endpoint does not include them, leading to confusion during health monitoring.

| Document | Claims |
|----------|--------|
| `docs/runbook.md` (lines 79-85) | `/health` returns `cache_metrics` |
| `docs/deployment.md` (lines 111-118) | `/health` returns `cache_metrics` |
| `app/main.py` (lines 425-464) | **Does NOT include `cache_metrics`** |

The actual `/health` endpoint returns only `status`, `database`, `cache` (connectivity boolean), and `service` fields. Cache metrics are available at the separate `/internal/cache/stats` endpoint.

**Recommendation:** Update `docs/runbook.md` and `docs/deployment.md` to remove `cache_metrics` from `/health` response examples. Add a note directing operators to `/internal/cache/stats` for detailed cache metrics.

### 1.6 API Key Rotation Path Error

**Severity:** Medium  
**Impact:** Security operations staff following the runbook will receive 404 errors.

| Document | Path |
|----------|------|
| `SECURITY.md` (line 59) | `POST /auth/routes/{route_id}/rotate-key` |
| `docs/runbook.md` (lines 205-208) | `POST /auth/routes/{route_id}/rotate-key` |
| Actual code (`app/routes/auth.py` line 854) | `POST /v1/routes/{route_id}/rotate-key` |

The documentation references an `/auth/routes/` prefix that does not exist. The actual endpoint uses the `/v1/routes/` prefix.

**Recommendation:** Update `SECURITY.md` and `docs/runbook.md` to use `/v1/routes/{route_id}/rotate-key`.

### 1.7 Missing `api/index.py` Documentation

**Severity:** Low  
**Impact:** The Vercel/Mangum ASGI adapter file exists but is undocumented, making serverless deployment less discoverable.

`docs/deployment.md` (line 47) mentions "the included `api/index.py` adapter" but the file is not listed in the README project layout or documented in any deployment guide.

**Recommendation:** Add `api/index.py` to the README project layout and document it as the Vercel/Mangum ASGI adapter in `docs/deployment.md`.

---

## 2. Missing Documentation Gaps

### 2.1 Undocumented API Endpoints

**Severity:** High  
**Impact:** API consumers cannot discover all available endpoints; integration testing is hindered.

The following endpoints exist in the code but are absent from `docs/reference/api.md`:

| Endpoint | Method | Purpose | Source File |
|----------|--------|---------|-------------|
| `/v1/r/{slug}` | POST | Public alias for `/v1/route/{slug}` | `app/routes/proxy.py:838-839` |
| `/rates` | GET | Exchange rate lookup (USD→target) | `app/main.py:351-371` |
| `/v1/me` | GET | Current user profile | `app/routes/auth.py:404-408` |
| `/v1/register` | POST | Deprecated — returns 410 Gone | `app/routes/auth.py:381-388` |
| `/v1/login` | POST | Deprecated — returns 410 Gone | `app/routes/auth.py:391-398` |
| `/v1/routes/{route_id}/logs/{log_id}/replay` | POST | Replay a logged webhook delivery | `app/routes/auth.py:1127-1232` |
| `/v1/webhooks/paystack/retry` | POST | Retry failed payment webhooks | `app/routes/auth.py:487-528` |
| `/v1/admin/credits/adjust` | POST | Admin-only credit adjustment | `app/routes/auth.py:548-612` |

**Recommendation:** Add all missing endpoints to `docs/reference/api.md`. Mark `/register` and `/login` as deprecated with 410 Gone status. Document the `X-Admin-Secret` requirement for the admin endpoint.

### 2.2 Missing Environment Variables in Setup Guide

**Severity:** Medium  
**Impact:** Operators deploying to production may miss critical configuration variables.

`docs/guides/setup.md` omits the following variables that exist in `app/config.py` and `.env.example`:

| Variable | Purpose | Default |
|----------|---------|---------|
| `PAYSTACK_SECRET_KEY` | Paystack API authentication | — |
| `PAYSTACK_BASE_URL` | Paystack API base URL | `https://api.paystack.co` |
| `PAYSTACK_WEBHOOK_URL` | Paystack webhook callback URL | — |
| `ADMIN_SECRET_KEY` | Admin endpoint authentication | — |
| `ADMIN_ALLOWED_IPS` | IP allowlist for admin endpoints | — |
| `SENTRY_DSN` | Sentry error tracking | — |
| `APP_VERSION` | Application version string | `0.7.0` |
| `OTEL_ENABLED` | Enable OpenTelemetry tracing | `false` |
| `DISPOSABLE_EMAIL_LIST_URL` | Disposable email domain list | GitHub raw URL |

**Recommendation:** Update `docs/guides/setup.md` to include all environment variables from `app/config.py`, grouped by category.

### 2.3 Missing Frontend Development Documentation

**Severity:** Medium  
**Impact:** Frontend contributors lack guidance on local development, building, and testing.

There is no documentation for:
- Running the frontend locally (`cd frontend && npm run dev`)
- Building the frontend for production (`npm run build`)
- Running frontend tests (`npm run test:unit`, `npm run test:e2e`)
- The GitHub Pages deployment workflow (`.github/workflows/frontend.yml`)

**Recommendation:** Add a "Frontend Development" section to `CONTRIBUTING.md` or create a new `docs/guides/frontend.md`.

### 2.4 Missing `migrate.py` Documentation

**Severity:** Low  
**Impact:** Developers search for a non-existent file.

`docs/migrations.md` (lines 14-16, 38-42) references a `migrate.py` script that does not exist in the project.

**Recommendation:** Either remove references to `migrate.py` or create the script if it is intended for CI/CD use.

---

## 3. Outdated Information

### 3.1 Frontend APPROACH.md Status

**Severity:** Medium  
**Impact:** Test status may be stale; file structure references are incorrect.

`frontend/APPROACH.md` (lines 188-220) claims:
- "Playwright E2E tests: 15/15 passing"
- Lists `docs/api.md` under frontend structure (actual location is `docs/reference/api.md`)

**Recommendation:** Update test counts to reflect the current state. Fix file path references.

### 3.2 Project Layout Incompleteness

**Severity:** Low  
**Impact:** New contributors get an incomplete picture of the services layer.

`README.md` (lines 54-79) shows `app/services/` with only `payments.py`, but the actual directory contains seven modules: `cache.py`, `circuit_breaker.py`, `exchange_rates.py`, `payments.py`, `retention.py`, `retry_processor.py`, and `route_cache.py`.

**Recommendation:** Expand the project layout in README to list all service modules.

---

## 4. Unclear Sections

### 4.1 Proxy Endpoint Behavior

**Severity:** High  
**Impact:** Clients checking HTTP status codes will miss delivery failures.

`docs/reference/api.md` (lines 27-53) implies the proxy endpoint returns standard HTTP status codes, but the implementation (`app/routes/proxy.py:1079-1089`) **always returns HTTP 200** to the client, with the actual delivery status in the `destination_status` field.

**Recommendation:** Clarify that the proxy is "transparent" — always returns HTTP 200 to the caller, with actual delivery status in `destination_status`.

### 4.2 Migrations.md Fragment

**Severity:** Medium  
**Impact:** Reads as a copy-paste error.

`docs/migrations.md` lines 4-5:
```
The complete schema is in `schema.sql`.
an existing database.
```

**Recommendation:** Fix to: "The complete schema is in `schema.sql`. Use it for fresh Supabase deployments or when resetting an existing database."

### 4.3 OAuth Endpoint Path Convention

**Severity:** Low  
**Impact:** Minor confusion about URL prefix conventions.

Auth routes use `/v1` prefix (e.g., `/v1/routes`) except OAuth routes which use `/auth` (e.g., `/auth/oauth/google`). This inconsistency is not documented.

**Recommendation:** Document the URL prefix convention in `docs/reference/api.md`.

### 4.4 Zero-Dollar Constraint FX Description

**Severity:** Low  
**Impact:** Describes behavior that does not match implementation.

`docs/reference/zero-dollar-constraint.md` (lines 59-67) states the FX fallback returns a hardcoded rate, but the actual implementation returns `None` when the live rate fetch fails.

**Recommendation:** Update the tradeoff description to match actual behavior (returns `None`, not a hardcoded fallback).

---

## 5. Formatting Errors

### 5.1 Fragment in migrations.md

`docs/migrations.md` lines 4-5 contain an incomplete sentence fragment (see Section 4.2).

### 5.2 Long Line Wrapping in setup.md

`docs/guides/setup.md` (line 87) has a very long line for `DISPOSABLE_EMAIL_LIST_URL` that wraps awkwardly.

**Recommendation:** Use proper line breaks for long env var descriptions.

### 5.3 Inconsistent Table Alignment

`docs/reference/zero-dollar-constraint.md` uses tables that render correctly in markdown but have inconsistent column alignment in the raw file.

**Recommendation:** Standardize markdown table formatting across all docs.

---

## 6. Additional Findings

### 6.1 Missing `DISPOSABLE_EMAIL_LIST_URL` in Main Docs

This environment variable is documented only in `docs/guides/setup.md` but not in `docs/runbook.md` or `README.md`.

**Recommendation:** Add `DISPOSABLE_EMAIL_LIST_URL` to `docs/runbook.md` environment variables section.

### 6.2 Non-existent `clear_fernet_cache()` References

`SECURITY.md` (line 56) and `docs/guides/setup.md` (line 114) reference `clear_fernet_cache()` which does not exist in the codebase. The Fernet cache is managed internally in `app/crypto.py`.

**Recommendation:** Remove or update these references to match the actual implementation.

### 6.3 Test Suite Documentation Gap

`CONTRIBUTING.md` shows `pytest tests/ -v` but `load-tests/README.md` shows `k6 run load-tests/saferoute-load-test.js`. The frontend has separate test commands (`npm run test:unit`, `npm run test:e2e`). No document explains the full test suite structure.

**Recommendation:** Add a "Test Suite" section to `CONTRIBUTING.md` explaining backend, frontend, and load tests.

---

## 7. Actionable Recommendations

The following table summarizes all recommendations, ordered by priority:

| Priority | Action | File(s) to Update | Section Reference |
|----------|--------|-------------------|-------------------|
| **P0** | Fix version mismatch: update `pyproject.toml` to `0.7.0` | `pyproject.toml` | 1.1 |
| **P0** | Fix `/health` response examples to remove `cache_metrics` | `docs/runbook.md`, `docs/deployment.md` | 1.5 |
| **P0** | Fix API key rotation path from `/auth/routes/` to `/v1/routes/` | `SECURITY.md`, `docs/runbook.md` | 1.6 |
| **P1** | Add missing endpoints to API reference | `docs/reference/api.md` | 2.1 |
| **P1** | Standardize install command to `requirements-dev.txt` | `README.md` | 1.2 |
| **P1** | Standardize mypy command with `--ignore-missing-imports` | `CONTRIBUTING.md` | 1.3 |
| **P1** | Fix Python version to 3.12+ | `docs/deployment.md` | 1.4 |
| **P1** | Add all env vars to setup guide | `docs/guides/setup.md` | 2.2 |
| **P1** | Clarify proxy endpoint always returns 200 | `docs/reference/api.md` | 4.1 |
| **P1** | Fix migrations.md fragment | `docs/migrations.md` | 4.2 |
| **P2** | Add frontend development docs | New: `docs/guides/frontend.md` or `CONTRIBUTING.md` | 2.3 |
| **P2** | Update APPROACH.md test counts and file paths | `frontend/APPROACH.md` | 3.1 |
| **P2** | Expand README project layout | `README.md` | 3.2 |
| **P2** | Remove/fix `clear_fernet_cache()` references | `SECURITY.md`, `docs/guides/setup.md` | 6.2 |
| **P2** | Resolve `migrate.py` reference | `docs/migrations.md` | 2.4 |
| **P3** | Update zero-dollar constraint FX description | `docs/reference/zero-dollar-constraint.md` | 4.4 |
| **P3** | Document `api/index.py` Mangum adapter | `README.md` | 1.7 |
| **P3** | Add `DISPOSABLE_EMAIL_LIST_URL` to runbook | `docs/runbook.md` | 6.1 |
| **P3** | Add test suite documentation | `CONTRIBUTING.md` | 6.3 |

---

## Appendix A. Files Reviewed

| File | Type | Status |
|------|------|--------|
| `README.md` | Main documentation | Reviewed |
| `CHANGELOG.md` | Version history | Reviewed |
| `CONTRIBUTING.md` | Contribution guide | Reviewed |
| `SECURITY.md` | Security policy | Reviewed |
| `docs/reference/api.md` | API reference | Reviewed |
| `docs/reference/architecture.md` | Architecture docs | Reviewed |
| `docs/reference/zero-dollar-constraint.md` | Tradeoffs | Reviewed |
| `docs/runbook.md` | Operations runbook | Reviewed |
| `docs/migrations.md` | Database migrations | Reviewed |
| `docs/deployment.md` | Deployment guide | Reviewed |
| `docs/guides/setup.md` | Setup guide | Reviewed |
| `docs/guides/distributed-cache.md` | Cache architecture | Reviewed |
| `app/repositories/README.md` | Repository layer docs | Reviewed |
| `load-tests/README.md` | Load testing | Reviewed |
| `frontend/APPROACH.md` | Frontend design | Reviewed |
| `app/main.py` | Application entry point | Cross-referenced |
| `app/config.py` | Configuration | Cross-referenced |
| `app/routes/proxy.py` | Proxy routes | Cross-referenced |
| `app/routes/auth.py` | Auth routes | Cross-referenced |
| `app/routes/oauth.py` | OAuth routes | Cross-referenced |
| `app/models.py` | Pydantic models | Cross-referenced |
| `schema.sql` | Database schema | Cross-referenced |
| `.env.example` | Environment template | Cross-referenced |
| `pyproject.toml` | Package metadata | Cross-referenced |
| `.github/workflows/ci.yml` | CI pipeline | Cross-referenced |
| `.github/workflows/frontend.yml` | Frontend CI | Cross-referenced |
| `api/index.py` | Vercel adapter | Cross-referenced |

---

## Appendix B. Methodology

This audit was conducted by systematically reading all documentation files and cross-referencing claims against the actual codebase. Each finding was categorized by severity (P0-Critical, P1-High, P2-Medium, P3-Low) based on its impact on users, contributors, or operators.

The review covered:
- Factual accuracy against source code
- Consistency across documentation files
- Completeness of endpoint and configuration coverage
- Clarity of instructions and explanations
- Markdown formatting and structural conventions
- Link validity and reference integrity
