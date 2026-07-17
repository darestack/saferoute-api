# SafeRoute API Operational Runbook

## Deployment

SafeRoute is a standard ASGI FastAPI application designed to run behind a reverse proxy (e.g., Nginx, Traefik, or a load balancer).

### Environment Variables
- `SUPABASE_URL`: The URL of your Supabase instance.
- `SUPABASE_KEY`: The public anon key.
- `SUPABASE_SERVICE_ROLE_KEY`: The service role key (required).
- `ENCRYPTION_KEY`: Used for webhook secret encryption and JWT signing (must be at least 32 chars in production).
- `API_KEY_SALT`: Salt used for hashing API keys.
- `RETRY_ENDPOINT_SECRET`: A shared secret used by cron jobs to authenticate to the `/internal/` endpoints.
- `TRUSTED_PROXIES`: A comma-separated list of trusted upstream proxies (e.g., `10.0.0.1, 10.0.0.2`). Used to safely extract `X-Forwarded-For`.
- `RETENTION_DAYS`: Webhook log retention period (default `30`).
- `MAX_REQUEST_BODY_BYTES`: Maximum request body size in bytes (default `1048576` / 1 MiB).
- `EMAIL_RETRY_ATTEMPTS`: Maximum email delivery retry attempts (default `3`).
- `EMAIL_RETRY_BACKOFF_BASE`: Base backoff seconds for email retries (default `1.0`).
- `GEOLOCATION_TIMEOUT_SECONDS`: Timeout for IP geolocation lookups (default `2.0`).
- `CIRCUIT_BREAKER_TIMEOUT_SECONDS`: Circuit breaker cooldown before half-open (default `60.0`).
- `OAUTH_CALLBACK_RATE_LIMIT`: Max OAuth callback attempts per IP (default `10`).
- `OAUTH_CALLBACK_RATE_WINDOW_SECONDS`: OAuth rate limit window in seconds (default `60`).

### Running the App
Use Uvicorn to run the app:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## Deployment

See [deployment.md](deployment.md) for complete deployment instructions.

Quick checklist:
1. Apply schema: paste `schema.sql` into Supabase SQL Editor
2. Set environment variables (see `.env.example`)
3. Deploy application code
4. Verify with `curl https://your-api.com/health`
5. Configure cron jobs for `/internal/process-retries` and `/internal/cleanup`

## Maintenance Tasks

### Background Cron Jobs
You MUST configure a scheduler (like cron-job.org, UptimeRobot, or a Kubernetes CronJob) to hit the following endpoints regularly:

1. **Process Retries**: `POST /internal/process-retries` 
   - Frequency: Every minute.
   - Header: `X-Retry-Secret: <your_retry_secret>`

2. **Database Cleanup**: `POST /internal/cleanup`
   - Frequency: Daily.
   - Header: `X-Retry-Secret: <your_retry_secret>`

## Cache Monitoring

### Health Check
The `/health` endpoint now reports cache connectivity and metrics:
```bash
curl https://your-api.com/health
```
Response includes:
```json
{
  "status": "healthy",
  "database": "connected",
  "cache": "connected",
  "cache_metrics": {
    "user_cache": {"hits": 1234, "misses": 56, "hit_rate": 0.957, ...},
    "route_cache": {"hits": 5678, "misses": 123, "hit_rate": 0.979, ...},
    "geolocation_cache": {"hits": 9012, "misses": 234, "hit_rate": 0.974, ...},
    "api_key_cache": {"hits": 3456, "misses": 78, "hit_rate": 0.978, ...}
  },
  "service": "SafeRoute API"
}
```

### Detailed Cache Stats
For per-cache breakdown, use the internal endpoint (requires `RETRY_ENDPOINT_SECRET`):
```bash
curl -H "X-Retry-Secret: $RETRY_ENDPOINT_SECRET" \
  https://your-api.com/internal/cache/stats
```

### Cache Alerts
Set up alerts for:
- **Low hit rate** (< 80%): Indicates cache is too small or TTL too short
- **High L1 utilization** (> 90%): Cache is near capacity, consider increasing `max_size`
- **L2 errors**: Database connectivity issues affecting distributed cache

### Manual Cache Clear
To clear all caches (use during debugging or after configuration changes):
```bash
# No direct endpoint - restart the application workers
# Caches are in-memory and clear on restart
```

## Incident Response

### High Memory Usage or Event Loop Stuttering
- **Symptom**: 502 Bad Gateway or Uvicorn `Worker failed to boot`.
- **Cause**: Extremely high webhook volume filling the `_circuit_breaker_state` or `_route_cache` OrderedDicts.
- **Action**: Increase the `workers` count in Uvicorn, scale horizontally, or lower the `_ROUTE_CACHE_MAX_SIZE` in `app/routes/proxy.py`.

### Cache Not Sharing Across Workers
- **Symptom**: Cache hit rates are low, or data appears inconsistent between workers.
- **Cause**: The `cache_entries` table or RPC functions are missing from the database (migration 013 not applied).
- **Action**: 
  1. Verify migration 013 is applied: check for `cache_entries` table in Supabase SQL Editor
  2. If missing, apply: paste `schema.sql` into Supabase SQL Editor
  3. Restart workers to clear stale in-memory caches
  4. Monitor `/health` endpoint for `"cache": "connected"`

### Rate Limit Evasion
- **Symptom**: A single client bypasses rate limits.
- **Cause**: The `TRUSTED_PROXIES` environment variable is misconfigured or missing the edge proxy IP.
- **Action**: Check your reverse proxy (e.g., Cloudflare, Vercel) and ensure its IPs are correctly listed in `TRUSTED_PROXIES` so `app/utils/security.py` can parse the `X-Forwarded-For` chain correctly from right-to-left.

### Webhook Delivery Failures (Circuit Breaker Open)
- **Symptom**: Webhook logs show `status_code = 503` (Service unavailable (circuit breaker open)).
- **Cause**: A downstream endpoint is timing out or returning 5xx consistently.
- **Action**: Check the downstream health. The circuit breaker will automatically transition to "half-open" every 60 seconds and recover once the downstream starts returning 200s again.
