# Zero-Dollar Constraint & Tradeoffs

SafeRoute is designed to run entirely on free/OSS components. This document
records the explicit tradeoffs accepted because the project forbids paid
tools, services, dependencies, or external resources. Every paid integration
below is **optional**: the code path degrades gracefully (no-op) when the
relevant key is absent, so the system runs at $0 with only Supabase (which has
a free tier) required.

## Required vs optional dependencies

| Component | Type | Cost | What happens when unconfigured |
|-----------|------|------|--------------------------------|
| Supabase (Postgres + Auth + RLS) | Freemium SaaS | Free tier | **Required.** App refuses to start without it. |
| `cryptography`, `httpx`, `fastapi`, etc. | OSS | $0 | Always used. |
| Resend (email) | Freemium SaaS | Free tier | Submission emails are skipped (`_is_resend_configured()` guard). |
| Paystack (payments) | Paid SaaS | Per-transaction | Endpoints return 500 "Payment system not configured". |
| Cloudflare Turnstile (CAPTCHA) | Freemium SaaS | Free tier | Spam shield step is skipped per route. |
| Sentry (errors) | Freemium SaaS | Free tier | `init_sentry()` no-ops; logging still goes to stderr. |
| OpenTelemetry (tracing) | OSS SDK | $0 SDK, $ for collector | SDK initializes but exports nowhere in prod unless a collector is wired. |
| ip-api.com (geolocation) | Freemium SaaS | Free tier (HTTP only) | Lookups return `None`; country-block spam rule is bypassed. |
| open.er-api.com (FX rates) | Free API | $0 | Falls back to hardcoded rate (see tradeoff below). |
| Google `generate_204` (outbound health) | Free endpoint | $0 | Outbound healthcheck cannot run. |

## Specific tradeoffs

### 1. No managed network egress firewall (SSRF)
**Decision:** Outbound webhook destinations are validated at write time with
DNS resolution (`validate_destination_url(resolve_dns=True)`) and re-checked at
request time for scheme/credential/literal-IP invariants
(`validate_destination_url_async(resolve_dns=False)`). There is **no** paid
egress firewall (e.g. VPC egress control, ProxyCrew, AWS Network Firewall).
**Risk:** DNS-rebinding TOCTOU between validation and connection. Mitigated by
re-checking the parsed URL at request time, but a hostile network could still
resolve a validated hostname to an internal IP between checks.
**If budget allows:** deploy behind a VPC with a restrictive egress policy and
resolve+pin destination IPs.

### 2. No Redis / shared in-memory state
**Decision:** Caches use an in-memory L1 + PostgreSQL L2 (`DistributedCache`).
The circuit breaker is **in-memory only** (per worker).
**Risk:** With `WORKERS > 1`, per-IP rate-limit counts, route/user/api-key L1
caches, and circuit-breaker state are not shared across workers. Rate limiting
and circuit breaking become per-worker (weaker) rather than global.
**Mitigation:** L2 Postgres backs route/user/api-key caches so they converge
after TTL. The app logs a startup warning when `WORKERS != 1`.
**If budget allows:** add Redis as the L1/L2 backing store and move the
circuit breaker into Redis.

### 3. Geolocation over plaintext HTTP
**Decision:** ip-api.com free tier only supports HTTP, so client IPs are sent
unencrypted for country-block spam rules.
**Risk:** IP metadata exposure on the wire; dependency on a third party.
**Mitigation:** Results (and failures) are cached for 1h; private/non-global
IPs never leave the process. Disable by leaving `spam_allowed_countries` empty.
**If budget allows:** switch to an HTTPS geolocation provider or a local
GeoIP database (MaxMind GeoLite2, free with signup).

### 4. Hardcoded FX fallback rate
**Decision:** `_convert_usd_to_ngn_kobo` falls back to `1500.0 NGN/USD` when the
live rate fetch fails.
**Risk:** Stale rate misprices Paystack charges if the API is down for a long
period.
**Mitigation:** Live rate is preferred; failures are logged. Treat a `None`
rate from `/rates` as unavailable (the endpoint no longer returns `1.0`).
**If budget allows:** use a paid FX API with an SLA, or pin a periodically
refreshed rate in the database.

### 5. No paid load-testing service
**Decision:** `load-tests/` use `k6` (OSS, locally run) — not a paid platform.
**Risk:** No hosted distributed load testing.
**Mitigation:** Run `k6` from a CI runner or local machine as needed.

### 6. Observability without a paid collector
**Decision:** Sentry/OTel are wired but optional. In production OTel exports
nowhere unless a real exporter is configured.
**Risk:** Traces are not aggregated; errors only surface via logs/Sentry free
tier.
**Mitigation:** Structured JSON logs (`logging_config`) are the primary
signal; `X-Request-ID` correlation is added to every request.

## Upgrade path (when budget is available)
All integrations are isolated behind single functions/classes
(`app.utils.email`, `app.services.payments`, `app.monitoring`,
`app.utils.captcha`, `app.services.exchange_rates`). Swapping a free
dependency for a paid/self-hosted one is a localized change with no ripple
into route handlers.
