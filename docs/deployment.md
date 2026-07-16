# SafeRoute API Deployment Guide

## Prerequisites

- Supabase project with database access
- Python 3.11+ and pip
- Environment variables configured (see `.env.example`)

## Step 1: Apply Database Migrations

The distributed cache requires migration 013. Apply it to your Supabase database:

### Option A: Using Supabase CLI (Recommended)

```bash
# Install Supabase CLI if not already installed
npm install -g supabase

# Link to your project
supabase link --project-id <your-project-id>

# Apply migrations
supabase migration up
```

### Option B: Using Supabase SQL Editor

1. Open your Supabase project dashboard
2. Go to **SQL Editor**
3. Copy the contents of `migrations/013_add_distributed_cache.sql`
4. Paste into the SQL Editor
5. Click **Run**

### Option C: Using the Custom Migration Runner

```bash
# Set DATABASE_URL in your environment
export DATABASE_URL="postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres"

# Run migrations
.venv/bin/python migrate.py
```

## Step 2: Configure Environment Variables

Ensure these environment variables are set in your deployment environment:

```env
# Required
SUPABASE_URL=https://[PROJECT-REF].supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres

# Security (must be set in production)
ENCRYPTION_KEY=<32+ character random string>
API_KEY_SALT=<16+ character random string>
ALLOWED_HOSTS=<your-domain.com>

# Optional (have defaults)
WEBHOOK_SECRET=<32+ character shared secret for webhook HMAC>
RETRY_ENDPOINT_SECRET=<32+ character secret for internal endpoints>
TRUSTED_PROXIES=<comma-separated proxy IPs>
MAX_REQUEST_BODY_BYTES=1048576
EMAIL_RETRY_ATTEMPTS=3
CIRCUIT_BREAKER_TIMEOUT_SECONDS=60
```

## Step 3: Deploy Application

### Vercel

```bash
# Install Vercel CLI
npm install -g vercel

# Deploy
vercel --prod
```

### Docker

```bash
# Build image
docker build -t saferoute-api .

# Run container
docker run -p 8000:8000 \
  -e SUPABASE_URL=$SUPABASE_URL \
  -e SUPABASE_SERVICE_ROLE_KEY=$SUPABASE_SERVICE_ROLE_KEY \
  -e DATABASE_URL=$DATABASE_URL \
  -e ENCRYPTION_KEY=$ENCRYPTION_KEY \
  saferoute-api
```

### Uvicorn (Direct)

```bash
# Install dependencies
pip install -r requirements.txt

# Run with multiple workers
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## Step 4: Verify Deployment

```bash
# Check health endpoint
curl https://your-api.com/health

# Expected response:
# {
#   "status": "healthy",
#   "database": "connected",
#   "cache": "connected",
#   "cache_metrics": { ... },
#   "service": "SafeRoute API"
# }

# Check cache stats (requires retry secret)
curl -H "X-Retry-Secret: $RETRY_ENDPOINT_SECRET" \
  https://your-api.com/internal/cache/stats
```

## Step 5: Configure Cron Jobs

Set up scheduled tasks for background processing:

### Process Retries (Every Minute)

```bash
curl -X POST https://your-api.com/internal/process-retries \
  -H "X-Retry-Secret: $RETRY_ENDPOINT_SECRET"
```

### Database Cleanup (Daily)

```bash
curl -X POST https://your-api.com/internal/cleanup \
  -H "X-Retry-Secret: $RETRY_ENDPOINT_SECRET"
```

## Monitoring

### Health Checks

- **Public**: `GET /health` — database + cache connectivity
- **Internal**: `GET /internal/cache/stats` — detailed cache metrics

### Key Metrics to Watch

| Metric | Target | Action if Outside Range |
|--------|--------|------------------------|
| Cache hit rate | > 90% | Increase L1 size or TTL |
| L1 utilization | < 80% | Decrease size to save memory |
| L2 errors | 0 | Check database connectivity |
| Response time p95 | < 500ms | Check downstream latency |

### Alerts to Configure

1. **Health check failure** — `/health` returns 503
2. **Low cache hit rate** — Overall hit rate < 80%
3. **High error rate** — 5xx responses > 1%
4. **Rate limit hits** — 429 responses increasing

## Troubleshooting

### Cache Not Sharing Across Workers

**Symptom**: Cache hit rates are low, or data appears inconsistent between workers.

**Cause**: Migration 013 not applied, or `SUPABASE_SERVICE_ROLE_KEY` missing.

**Action**:
1. Verify migration 013 is applied: check for `cache_entries` table in Supabase SQL Editor
2. Verify `SUPABASE_SERVICE_ROLE_KEY` is set
3. Restart workers to clear stale in-memory caches

### Database Connection Issues

**Symptom**: Health check shows `"database": "disconnected"`.

**Action**:
1. Verify `DATABASE_URL` is correct
2. Check Supabase project status
3. Verify network connectivity (firewall, VPC peering)

### High Memory Usage

**Symptom**: Workers using excessive memory.

**Action**:
1. Check cache metrics: `/internal/cache/stats`
2. Reduce `_USER_CACHE_MAX_SIZE` or `_ROUTE_CACHE_MAX_SIZE`
3. Increase worker count and reduce per-worker cache size
