# SafeRoute API — Two-Phase Code Review & Remediation Report

> Scope decision (confirmed with owner): **Backend first, then frontend/CI/docs**.
> Runtime context: **Active project — refactor freely**.
> Services: **Replace paid with free** where refactoring; keep working free-tier integrations.
> Standards: **Modernize tooling** (adopt `uv`, tighten `mypy` overrides, keep ruff/black).
> Tests: **Add unit + mocked integration + E2E (no live DB required)**.
> Process: **Feature branch + PR per batch**; commit sequentially.
> Zero-dollar constraint: **No paid tools/services/deps.** Tradeoffs documented inline.

---

## Phase 1 — Line-by-line correctness, edge cases, dead code, tech debt

### B1. `app/config.py`
- **Bug / inconsistency**: `APP_VERSION` defaults to `"0.7.0"` but `main.py` sets FastAPI `version="1.0.0"` and root endpoint returns `settings.APP_VERSION`. Three conflicting version sources.
- **Tech debt**: `extra="ignore"` silently swallows typos in env var names (e.g. `ALLOWED_HOSTS` vs `ALLOWED_HOST`). Fail-closed is desirable for secrets but silent ignores reduce operability. Keep but document.
- **Edge case**: `get_allowed_hosts()` raises in production if `ALLOWED_HOSTS` empty, but `validate_production_settings` already raises earlier — redundant duplicate check (dead-ish branch). Harmless but duplicated logic.
- **Bug**: `is_production` uses `== "production"`. `ENVIRONMENT` default is `"production"`, so a missing env var silently enables the strictest mode (good fail-closed), but the warning path for missing `ENCRYPTION_KEY` only triggers when explicitly non-production. Fine, but `validate_production_settings` references `self.WEBHOOK_SECRET` etc. with truthiness checks that skip length validation when the secret is empty — intentional, documented.

### B2. `app/crypto.py`
- **Correctness**: `decrypt_webhook_secret` returns the raw ciphertext unchanged when no `ENCRYPTION_KEY` and no version prefix. If a value was stored with `safe_plain:` prefix it is unprefixed and returned. OK.
- **Bug risk**: `encrypt_webhook_secret` raises `RuntimeError` in production if key missing, but callers in `auth.py` (create/update route) do not distinguish `RuntimeError` from generic `Exception` — they wrap in 500 with `safe_error_detail`. Acceptable, but the plaintext fallback path means a non-prod route created without encryption keeps `safe_plain:` values that later become un-decryptable after prod key rotation. Documented as migration window.
- **Dead code**: `_VERSION_PREFIX`/`_FALLBACK_PREFIX` versioning is partial — no rotation logic that reads versions differ; single version only. Not dead but underused. Acceptable.

### B3. `app/database.py`
- **Bug**: `get_http_client` reuses a closed client via `is_closed` check — OK. But `execute_query` wraps blocking `.execute()` in `asyncio.to_thread`; Supabase client is not concurrency-safe across threads by default. Acceptable for current usage.
- **Tech debt / dead code**: `supabase_client = get_supabase_client(use_service_role=False)` is created at import time and uses the **anon key** for the module-level alias. `oauth.py` imports `supabase_client` for code exchange. Fine, but the module-level instantiation means a missing `SUPABASE_KEY` crashes import even for code paths that only need admin. Fail-fast is intended.
- **Redundant**: `cache_get` in `main.py` health check calls `cache_get("__health_check__")` on every `/health`. Fine.
- **Bug**: `verify_api_key` caches misses? No — only caches hits. Correct (avoids cache poisoning of negative results). Good.

### B4. `app/routes/auth.py`
- **CRITICAL bug**: `retry_failed_webhooks` (line 485) selects `webhook_failures` with `route_id == None`. Payment webhook failures are inserted by `retry_processor.update_retry_outcome` with `route_id` set to `log_entry["route_id"]` — NOT null. So payment failures always have a route_id and this query returns **nothing**. The admin retry endpoint for payment webhooks is effectively dead. Misaligned with schema.
- **Bug**: `_fetch_and_cache_user` (line 264) re-fetches cache inside the fill, but if another coroutine cached a *partial/different* user it returns that. Minor.
- **Bug**: `admin_adjust_credits` reads `result.data[0]["credits"]` without checking `result.data` length → `IndexError` → 500 if user profile row missing. Should guard.
- **Dead code**: `_user_to_dict` drops `credits`/`tier` (not serialized) yet `_fetch_and_cache_user` re-fetches profile separately. The cache stores only id/email/full_name — so `/v1/me` after credit change relies on `_user_cache.delete`. OK but the `credits`/`tier` are fetched from DB directly, never cached. Acceptable.
- **Tech debt**: duplicate slug-exists check logic between update and repository.

### B5. `app/routes/proxy.py`
- **CRITICAL correctness**: `proxy_webhook` is registered at `@router.post("/v1/route/{slug}")` but `main.py` mounts routers and the README/examples use `/v1/r/{slug}`. The public slug path is `/v1/route/{slug}` — inconsistent with documented `/v1/r/contact-form`. Verify against frontend + docs. (Likely a real bug: documented endpoint does not exist.)
- **Bug**: `_authenticate_route` only enforces API key if `x_api_key` is provided, and only enforces signature if `webhook_secrets` exist. A route **with** a webhook secret but **without** `X-API-Key` will still pass auth if the signature header is present. But a route with `webhook_secrets` set and NO signature header → 401. However a route with NEITHER api_key configured nor webhook_secret → `_authenticate_route` returns `None` early (no `x_api_key`) and skips signature → **anyone can POST to any active public slug** with no auth. This is the core security model: the **slug is the secret**. Acceptable by design but worth documenting; rate-limit is the only abuse control.
- **Bug**: idempotency claim + wait: if `claim_idempotency` returns True but the downstream `forward` fails before `store_idempotency`, the key remains claimed with no cached result → subsequent requests wait 30s then return 504. Edge case, acceptable.
- **Performance**: `parse_payload` is called before route lookup — so even invalid/oversized bodies for unknown slugs get parsed. Minor.
- **Tech debt**: `validate_destination_url_async(destination, resolve_dns=False)` at request time is DNS-free; full check at write time. Good design, documented.
- **Bug**: `proxy_webhook` always returns 200 with `destination_status` even on 5xx from destination → clients can't use HTTP status. Documented as intentional transparent proxy. OK.
- **Dead code**: `process_retries`/`cleanup`/`outbound_health_check`/`cache_stats` all behind `RETRY_ENDPOINT_SECRET`; fine.

### B6. `app/services/cache.py` & `route_cache.py`
- **Concurrency bug**: `DistributedCache.get` L1 check/evict happens under lock, but the L2 `cache_get` is called **outside** the lock and may run concurrently with `set` repopulating L1 — fine. However the metrics (`_hits`, `_misses`) are mutated outside the lock in the L2 path (line 79–84 set `_l2_hits` then later `_misses` at 90 outside lock) → lost updates under concurrency. Minor (counters).
- **Bug**: `_evict` uses FIFO but cache is `OrderedDict` used as LRU (`move_to_end` on get). Mixed eviction semantics — comment says FIFO but move_to_end makes it LRU. Dead/misleading comment.
- **Dead code**: `clear_route_cache`/`clear_api_key_cache` exist; `clear_route_cache` used. OK.

### B7. `app/utils/security.py`
- **Bug**: `validate_destination_url` — when hostname is a literal IP and `resolve_dns=True`, it returns after `_is_public_ip` check (good). When hostname is a literal IP and `resolve_dns=False`, the `except ValueError` (not an IP) is not hit, so it falls through to `if not resolve_dns: return` — OK.
- **Security gap**: SSRF guard checks scheme/port via `parsed.port or 443` for DNS resolution but does NOT re-validate after DNS (TOCTOU) — documented as accepted tradeoff under zero-dollar constraint.
- **Bug**: `safe_error_detail` redaction regex for internal IPs uses `(?<![\d.])` lookbehind but `127.0.0.1` matches; fine.
- **Tech debt**: `get_client_ip` trusts right-most XFF only when peer in `TRUSTED_PROXIES`. Good. But default empty `TRUSTED_PROXIES` on Vercel means direct peer is Vercel's proxy IP, not client → rate limiting/geo keyed on wrong IP. Operational debt; documented.

### B8. `app/utils/routes.py`
- **Dead code**: `assert_owned_route_exists` is defined but appears unused (grep). Candidate for removal or kept for API symmetry.

### B9. `app/routes/oauth.py`
- **Bug/duplication**: `state` JWT signed with `settings.ENCRYPTION_KEY or _get_jwt_signing_key()`. In production `ENCRYPTION_KEY` present → fine. Callback decodes with same. But the `code_challenge` is only in the state JWT and PKCE verifier stored by challenge — if state JWT forgery is possible (weak/empty key in non-prod) it's contained to non-prod.
- **Bug**: `_check_oauth_rate_limit` uses a module-global `OrderedDict` without clearing on process restart — bounded, fine.
- **Tech debt**: `redirect_uri` built as `FRONTEND_URL + "/auth/callback"` via `urljoin` — if `FRONTEND_URL` ends with `/`, `urljoin` drops `auth/callback`. Actually `urljoin("https://x/","auth/callback")` → `https://x/auth/callback`; but `urljoin("https://x/dashboard.html","auth/callback")` would break. `FRONTEND_URL.rstrip("/") + "/"` is forced, so OK.

### B10. `app/services/payments.py`
- **CRITICAL business bug**: `verify_payment` returns `new_balance: 0` always, and credits are added via `add_user_credits`. But `process_webhook` (webhook path) also credits on `charge.success` — and `verify_payment` (return-url path) ALSO credits. If both webhook and return-verify fire, **double credit**. No idempotency on credit grant keyed by reference. Real double-spend risk.
- **Bug**: reference format `sr_{user_id[:8]}_{tier}` is not unique across re-purchases; relies on secondary random suffix only when collision detected. Race window exists.
- **Tech debt**: `initialize_payment` builds a fresh `httpx.AsyncClient` per call instead of using shared `get_http_client()`. Connection churn under load.
- **Bug**: `verify_webhook_signature` uses `hmac.compare_digest` on hex digest vs raw header — Paystack sends hex SHA512; correct. But missing `X-Paystack-Signature` → `signature=""` → compare_digest(expect, "") → False → 401. OK.

### B11. `app/services/retry_processor.py`
- **Bug**: `process_pending_retries` joins `routes!inner(...)` — if route deleted, log never retried and stays `pending` forever (no reaper for missing-route). Minor.
- **Correctness**: `reap_stale_retries` resets `retrying`→`pending` by `updated_at < cutoff`. Good.

### B12. Tests / CI
- **CI bug**: `ci.yml` "Security Scan" greps staged files for `password|secret|key|token` and **fails** if found — this will block every PR that contains the word "key" (e.g. `API_KEY_SALT`, `ENCRYPTION_KEY`). It also only checks `--cached` (staged) which on `pull_request` events is empty → grep over nothing → exits 0 (false sense of security). Broken control.
- **CI bug**: `pip-audit --fix --ignore-vuln GHSA-xxx` is a placeholder; `--fix` may alter `requirements.txt` unexpectedly; `|| true` + `continue-on-error` makes it toothless.
- **CI gap**: no coverage threshold gate (requested: add).
- **Test gap**: no E2E test exercising the proxy happy path with mocked Supabase.

---

## Phase 2 — Holistic / architectural review

### A1. Endpoint path inconsistency (B5 + docs + frontend)
`/v1/route/{slug}` (code) vs `/v1/r/{slug}` (README/frontend). Must reconcile; this is a shipping-blocking bug.

### A2. Payment double-credit (B10)
Two independent credit paths (webhook + return-verify) without idempotent guard → financial integrity risk. Fix: grant credits exactly once per `reference` using a DB constraint / `ON CONFLICT`.

### A3. Dead admin retry endpoint (B4)
`/v1/webhooks/paystack/retry` queries `route_id == None` but payment failures always carry a route_id → endpoint does nothing. Either fix the query or remove. Under "remove dead code" guidance → fix to be functional or delete.

### A4. Concurrency counters in `DistributedCache` (B6)
Hit/miss metrics mutated outside lock → inaccurate. Low impact (observability only) but should be lock-correct or use atomic counters.

### A5. SSRF TOCTOU (B7)
Accepted zero-dollar tradeoff; document explicitly in runbook. Recommend periodic re-validation + egress allowlist if budget allows (future).

### A6. Missing `TRUSTED_PROXIES` on serverless
On Vercel the peer IP is the CDN; without `TRUSTED_PROXIES` set, per-IP rate limiting and geo are ineffective. Operational debt — document in runbook + config validation.

### A7. Epistemic debt — version drift
`APP_VERSION 0.7.0` vs FastAPI `1.0.0` vs README badges. Single source of truth needed.

### A8. Tooling modernization
- Migrate `requirements*.txt` + manual venv to `uv` + `pyproject.toml` optional deps.
- `mypy` overrides silence 9 codes across 8 modules — gradually narrow; start with `database.py` typed wrapper.
- Add `ruff` per-file ignores already present; consolidate.

### A9. Systemic — caching coherence
L1 in-process caches are not shared across Vercel serverless instances (each cold start = empty). The "distributed" L2 is Postgres, but every read does an L1 miss → L2 hit → DB round trip, partly defeating the cache. Document and consider a real shared cache (Redis) if budget — out of zero-dollar scope; keep Postgres L2.

### A10. Test coverage & E2E
No live-or-mocked E2E. Add mocked integration tests for proxy + payments using `respx`/`pytest-httpx` (free) and `unittest.mock` for Supabase.

---

## Prioritized remediation plan (highest → lowest impact)

1. **Endpoint path reconciliation** (`/v1/route` vs `/v1/r`) — shipping blocker.
2. **Payment double-credit idempotency** — financial integrity.
3. **Dead admin retry endpoint** (`route_id == None`) — correctness.
4. **`admin_adjust_credits` IndexError guard** — crash bug.
5. **Version source-of-truth** (`APP_VERSION` unification).
6. **CI security-scan fixes** (broken grep + placeholder pip-audit) + **coverage gate**.
7. **`DistributedCache` metric lock correctness** + eviction comment fix.
8. **Dead code removal** (`assert_owned_route_exists` if unused, duplicate allowed-hosts check).
9. **Tooling modernization** (uv, mypy narrowing).
10. **Docs** (architecture/api/runbook) capturing SSRF/TRUSTED_PROXIES/zero-dollar tradeoffs + E2E tests.

Each batch below implements items, adds tests, and opens a PR.

---

## Zero-dollar constraint tradeoffs (explicit)

- **No Redis**: cross-instance shared cache unavailable → Postgres L2 used; accepted latency.
- **No managed egress firewall**: SSRF mitigated via DNS-resolution + scheme/credential checks at write time; TOCTOU residual risk documented.
- **No paid CI scanners**: rely on `ruff`, `mypy`, `pip-audit` (free, OSS), `pytest` coverage. `pip-audit` kept but made non-blocking-with-report rather than `--fix`.
- **Free geolocation (ip-api.com over HTTP)**: privacy tradeoff documented; country-blocking is best-effort.
- **All deps remain OSS/pip-installable**: no SaaS required for the review itself.
