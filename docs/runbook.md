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

### Running the App
Use Uvicorn to run the app:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## Maintenance Tasks

### Background Cron Jobs
You MUST configure a scheduler (like cron-job.org, UptimeRobot, or a Kubernetes CronJob) to hit the following endpoints regularly:

1. **Process Retries**: `POST /internal/process-retries` 
   - Frequency: Every minute.
   - Header: `X-Retry-Secret: <your_retry_secret>`

2. **Database Cleanup**: `POST /internal/cleanup`
   - Frequency: Daily.
   - Header: `X-Retry-Secret: <your_retry_secret>`

## Incident Response

### High Memory Usage or Event Loop Stuttering
- **Symptom**: 502 Bad Gateway or Uvicorn `Worker failed to boot`.
- **Cause**: Extremely high webhook volume filling the `_circuit_breaker_state` or `_route_cache` OrderedDicts.
- **Action**: Increase the `workers` count in Uvicorn, scale horizontally, or lower the `_ROUTE_CACHE_MAX_SIZE` in `app/routes/proxy.py`.

### Rate Limit Evasion
- **Symptom**: A single client bypasses rate limits.
- **Cause**: The `TRUSTED_PROXIES` environment variable is misconfigured or missing the edge proxy IP.
- **Action**: Check your reverse proxy (e.g., Cloudflare, Vercel) and ensure its IPs are correctly listed in `TRUSTED_PROXIES` so `app/utils/security.py` can parse the `X-Forwarded-For` chain correctly from right-to-left.

### Webhook Delivery Failures (Circuit Breaker Open)
- **Symptom**: Webhook logs show `status_code = 503` (Service unavailable (circuit breaker open)).
- **Cause**: A downstream endpoint is timing out or returning 5xx consistently.
- **Action**: Check the downstream health. The circuit breaker will automatically transition to "half-open" every 60 seconds and recover once the downstream starts returning 200s again.
