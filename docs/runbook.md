# SafeRoute API Operational Runbook

## Overview

SafeRoute API is a FastAPI-based form backend for static sites. It handles form validation, spam filtering, email notifications, and webhook delivery. This runbook covers deployment, maintenance, and incident response.

## Architecture

```
Client -> FastAPI (Vercel/Lambda) -> Supabase (DB + Auth)
                                  -> Resend (Email)
                                  -> Paystack (Payments)
                                  -> Downstream webhooks
```

## Environment Variables

### Required
- `SUPABASE_URL`: The URL of your Supabase instance.
- `SUPABASE_KEY`: The public anon key.
- `SUPABASE_SERVICE_ROLE_KEY`: The service role key (required for server-side operations).
- `ENCRYPTION_KEY`: Used for webhook secret encryption and JWT signing (must be at least 32 chars in production).
- `API_KEY_SALT`: Salt used for hashing API keys.
- `RETRY_ENDPOINT_SECRET`: A shared secret used by cron jobs to authenticate to the `/internal/` endpoints.

### Optional
- `TRUSTED_PROXIES`: A comma-separated list of trusted upstream proxies (e.g., `10.0.0.1, 10.0.0.2`). Used to safely extract `X-Forwarded-For`.
- `RETENTION_DAYS`: Webhook log retention period (default `30`).
- `MAX_REQUEST_BODY_BYTES`: Maximum request body size in bytes (default `1048576` / 1 MiB).
- `EMAIL_RETRY_ATTEMPTS`: Maximum email delivery retry attempts (default `3`).
- `EMAIL_RETRY_BACKOFF_BASE`: Base backoff seconds for email retries (default `1.0`).
- `GEOLOCATION_TIMEOUT_SECONDS`: Timeout for IP geolocation lookups (default `2.0`).
- `CIRCUIT_BREAKER_TIMEOUT_SECONDS`: Circuit breaker cooldown before half-open (default `60.0`).
- `OAUTH_CALLBACK_RATE_LIMIT`: Max OAuth callback attempts per IP (default `10`).
- `OAUTH_CALLBACK_RATE_WINDOW_SECONDS`: OAuth rate limit window in seconds (default `60`).
- `RESEND_API_KEY`: Resend API key for email notifications.
- `PAYSTACK_SECRET_KEY`: Paystack secret key for payment processing.
- `PAYSTACK_BASE_URL`: Paystack API base URL (default `https://api.paystack.co`).
- `PAYSTACK_WEBHOOK_URL`: Public URL where Paystack sends webhook events.
- `FRONTEND_URL`: Frontend URL for payment callbacks (default `http://localhost:8000`).
- `SENTRY_DSN`: Sentry DSN for error tracking (optional).
- `OTEL_ENABLED`: Enable OpenTelemetry tracing (default `false`).
- `APP_VERSION`: Application version for Sentry release tracking.
- `ADMIN_SECRET_KEY`: Shared secret for admin endpoints.
- `ADMIN_ALLOWED_IPS`: Comma-separated IP allowlist for admin endpoints.
- `DISPOSABLE_EMAIL_LIST_URL`: URL to disposable email domain list (defaults to embedded fallback if empty).

## Deployment

### Vercel (Recommended)
SafeRoute is optimized for Vercel deployment using the included `api/index.py` adapter.

1. Connect your GitHub repository to Vercel
2. Set all environment variables in Vercel dashboard
3. Deploy the `main` branch
4. Apply `schema.sql` to your Supabase project

### Docker
```bash
docker build -t saferoute-api .
docker run -p 8000:8000 --env-file .env saferoute-api
```

### Manual (Uvicorn)
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## Database Setup

1. Open Supabase SQL Editor
2. Paste contents of `schema.sql`
3. Execute to create tables, indexes, and RLS policies
4. Verify with: `SELECT tablename FROM pg_tables WHERE schemaname = 'public';`

## Health Checks

### Basic Health
```bash
curl https://your-api.com/health
```
Expected response:
```json
{
  "status": "healthy",
  "database": "connected",
  "cache": "connected",
  "service": "SafeRoute API"
}
```

> **Note:** The `/health` endpoint checks database and cache connectivity only. Detailed cache metrics (hit/miss rates, L1/L2 breakdown) are available at `/internal/cache/stats`.

### Detailed Health with Cache Metrics
```bash
curl -H "X-Retry-Secret: $RETRY_ENDPOINT_SECRET" \
  https://your-api.com/internal/cache/stats
```
The `/health` endpoint checks database **and** distributed-cache (L2
Postgres) connectivity. If either is down it returns `503` so an orchestrator
can pull the instance out of rotation. Cache *metrics* (hit/miss rates) are
exposed separately on the internal endpoint below.

### Cache Stats (Internal)
```bash
curl -H "X-Retry-Secret: $RETRY_ENDPOINT_SECRET" \
  https://your-api.com/internal/cache/stats
```

## Background Jobs

### Cron Jobs
You MUST configure a scheduler to hit the following endpoints:

1. **Process Retries**: `POST /internal/process-retries`
   - Frequency: Every minute
   - Header: `X-Retry-Secret: <your_retry_secret>`
   - Processes failed webhook deliveries from the retry queue

2. **Database Cleanup**: `POST /internal/cleanup`
   - Frequency: Daily (recommended: 02:00 UTC)
   - Header: `X-Retry-Secret: <your_retry_secret>`
   - Purges expired webhook logs, idempotency keys, and PKCE verifiers

### Vercel Cron
If deploying on Vercel, add to `vercel.json`:
```json
{
  "crons": [
    { "path": "/internal/process-retries", "schedule": "* * * * *" },
    { "path": "/internal/cleanup", "schedule": "0 2 * * *" }
  ]
}
```

## Monitoring

### Free Tier Options
- **Sentry**: Error tracking with 5,000 events/month free tier
- **UptimeRobot**: Uptime monitoring with 5-minute intervals
- **Vercel Analytics**: Built-in for Vercel deployments

See [Zero-Dollar Constraint & Tradeoffs](reference/zero-dollar-constraint.md)
for the explicit list of every paid/optional integration, what happens
when it is unconfigured, and the security/scale tradeoffs accepted
to keep the project at $0.

### Key Metrics to Monitor
- `/health` endpoint availability
- Webhook delivery success rate (check `/v1/routes/{route_id}/logs`)
- Circuit breaker state (open = downstream issues)
- Cache hit rates (should be > 80%)
- Payment success rate

## Incident Response

### High Memory Usage or Event Loop Stuttering
- **Symptom**: 502 Bad Gateway or Uvicorn `Worker failed to boot`
- **Cause**: High webhook volume filling circuit breaker or route caches
- **Action**: Increase worker count, scale horizontally, or reduce `_ROUTE_CACHE_MAX_SIZE`

### Cache Not Sharing Across Workers
- **Symptom**: Low cache hit rates, inconsistent data between workers
- **Cause**: Missing `cache_entries` table or RPC functions
- **Action**: 
  1. Verify migration 013 is applied
  2. If missing, apply `schema.sql`
  3. Restart workers to clear in-memory caches

### Rate Limit Evasion
- **Symptom**: Single client bypasses rate limits
- **Cause**: `TRUSTED_PROXIES` not configured or missing edge proxy IP
- **Action**: Configure `TRUSTED_PROXIES` with your CDN/proxy IPs

### Webhook Delivery Failures (Circuit Breaker Open)
- **Symptom**: Webhook logs show `status_code = 503`
- **Cause**: Downstream endpoint timing out or returning 5xx
- **Action**: Check downstream health. Circuit breaker auto-recovers every 60s.

### Payment Failures
- **Symptom**: Users report payment initialization failures
- **Cause**: Paystack API key misconfigured or service down
- **Action**: 
  1. Verify `PAYSTACK_SECRET_KEY` is set
  2. Check Paystack status page
  3. Review payment_transactions table for error details

### Email Delivery Failures
- **Symptom**: Form submission emails not received
- **Cause**: Resend API key misconfigured or rate limited
- **Action**:
  1. Verify `RESEND_API_KEY` is set
  2. Check Resend dashboard for delivery status
  3. Review application logs for `ResendError` messages

## Key Rotation

All long-lived secrets are environment variables. Rotate them by
writing new values and restarting (the app reads settings at import time).
Prefer a rolling restart so in-flight webhook deliveries are not dropped.

### Encryption Key (`ENCRYPTION_KEY`)
1. Generate a new 32+ char secret.
2. Set it as `ENCRYPTION_KEY` in the environment.
3. Restart the application (the Fernet instance is cached per process).
4. Re-encrypt existing webhook secrets: for every route with a
   `webhook_secret`/`webhook_secrets` value, read it, decrypt with the
   old key, and re-write via the update endpoint so it is stored under
   the new key. The `v1:` version prefix lets old+new coexist during the
   cutover window.

### API Key (`api_key_hash` per route)

Use `POST /v1/routes/{route_id}/rotate-key`. The new key is
returned **once** and cannot be retrieved again — store it immediately.
The previous key is invalidated atomically and the route's cached proxy
row is evicted so the new key takes effect on the next request.

### Internal Secrets (`RETRY_ENDPOINT_SECRET`, `ADMIN_SECRET_KEY`)
1. Generate new high-entropy values.
2. Set them in the environment alongside the public URLs used by the
   scheduled jobs (`cleanup.yml`) and any admin tooling.
3. Restart. Old values stop authenticating immediately because the
   endpoints compare against the live `settings` value.

### Provider Secrets (Paystack, Resend, Turnstile)
Rotate in the provider console, then update the corresponding env var
(`PAYSTACK_SECRET_KEY`, `RESEND_API_KEY`, `TURNSTILE_SECRET_KEY`)
and restart. Missing values degrade gracefully (see
[docs/reference/zero-dollar-constraint.md](../reference/zero-dollar-constraint.md).

## Scaling & Horizontal Deployment

SafeRoute is stateless apart from in-memory caches. Horizontal scale
by running multiple instances behind a load balancer; all durable state
lives in Supabase.

### Multi-worker / multi-instance caveats (zero-dollar)
- **In-memory caches are per process.** Route, user, and api-key caches
  use a PostgreSQL L2 tier, so they converge after TTL. The
  **circuit breaker is in-memory only** and is NOT shared — with
  `WORKERS > 1` (or multiple instances) each worker maintains its
  own breaker and per-IP rate-limit counters. This weakens (but does
  not break) global rate limiting and circuit breaking. The app logs a
  startup warning when `WORKERS != 1`.
- **Mitigation without paid infra:** keep `WORKERS=1` per instance and
  scale by adding instances; rely on the L2 cache for convergence;
  tune `CIRCUIT_BREAKER_TIMEOUT_SECONDS` and rate-limit windows
  for acceptable per-worker divergence.

### When budget allows
Move the L1/L2 backing store and the circuit breaker into Redis so
state is shared across workers and instances. The cache and breaker are
isolated behind `DistributedCache` / `circuit_breaker` modules, so the
swap is localized.

## Backup and Recovery

### Database
- Supabase handles automated backups (check your plan)
- Export critical tables regularly: `payment_transactions`, `routes`, `user_profiles`
- Schema is in `schema.sql` for disaster recovery

### Application State
- All state is in Supabase; application is stateless
- Caches are in-memory and rebuild on restart
- No additional backup needed beyond database

## Support

For issues and questions:
- GitHub Issues: https://github.com/darestack/saferoute-api/issues
- Email: deeprince2020@gmail.com
