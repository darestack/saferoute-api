# Distributed Cache Architecture

## Overview

SafeRoute API uses a two-tier cache architecture to balance performance and consistency across multiple worker processes. The cache layer is built on PostgreSQL (via Supabase) with zero external dependencies.

## Architecture

```
┌─────────────┐     ┌─────────────┐
│   Worker 1  │     │   Worker 2  │
│  ┌───────┐  │     │  ┌───────┐  │
│  │  L1   │  │     │  │  L1   │  │
│  │(Order)│  │     │  │(Order)│  │
│  └───┬───┘  │     │  └───┬───┘  │
│      │      │     │      │      │
│      ▼      │     │      ▼      │
│  ┌───────┐  │     │  ┌───────┐  │
│  │  L2   │◄─┼─────┼──►│  L2   │  │
│  │(PG RPC)│  │     │  │(PG RPC)│  │
│  └───────┘  │     │  └───────┘  │
└─────────────┘     └─────────────┘
         │                   │
         └─────────┬─────────┘
                   ▼
           ┌─────────────┐
           │  PostgreSQL │
           │ cache_entries│
           └─────────────┘
```

### L1: In-Memory Cache

- **Technology**: Python `OrderedDict` with TTL and FIFO eviction
- **Scope**: Per-worker process
- **Latency**: ~0.01ms (O(1) dict lookup)
- **Capacity**: Configurable per cache (default 500-4096 entries)

**Eviction Policy**: FIFO (first-in, first-out). When the cache reaches `max_size`, the oldest entry is evicted to make room for new entries.

**TTL**: Each entry has a time-to-live. Expired entries are lazily removed on access.

### L2: PostgreSQL Cache

- **Technology**: PostgreSQL table with JSONB values and TTL
- **Scope**: Shared across all workers
- **Latency**: ~1-5ms (network round-trip)
- **Capacity**: Effectively unlimited (bounded by TTL cleanup)

**Schema**:
```sql
CREATE TABLE public.cache_entries (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT timezone('utc', now()) NOT NULL
);
```

**RPC Functions**:
- `cache_get(p_key)` → JSONB | NULL
- `cache_set(p_key, p_value, p_ttl_seconds)` → void
- `cache_delete(p_key)` → void
- `cache_cleanup()` → integer (rows removed)

## Cache Layers

### User Cache
- **Purpose**: Cache authenticated user profiles from Supabase Auth
- **L1 Size**: 1000 entries
- **TTL**: 300 seconds (5 minutes)
- **Key**: User ID
- **Value**: User model dict

### Route Cache
- **Purpose**: Cache active route configurations for webhook proxy
- **L1 Size**: 500 entries
- **TTL**: 30 seconds
- **Key**: Route slug
- **Value**: Route dict

### API Key Cache
- **Purpose**: Cache API key hash → route_id mappings
- **L1 Size**: 500 entries
- **TTL**: 300 seconds (5 minutes)
- **Key**: HMAC-SHA256 hash of API key
- **Value**: Route ID
- **Special**: Maintains reverse index for per-route invalidation

### Geolocation Cache
- **Purpose**: Cache IP → country code lookups
- **L1 Size**: 4096 entries
- **TTL**: 3600 seconds (1 hour)
- **Key**: Client IP address
- **Value**: 2-letter ISO country code or NULL

## Performance Characteristics

| Metric | L1 Hit | L2 Hit | L1 Miss |
|--------|--------|--------|---------|
| Latency | ~0.01ms | ~1-5ms | ~0.01ms + DB query |
| Capacity | 500-4096 | Unlimited | N/A |
| Consistency | Per-worker | Global | N/A |

**Hot Path**: L1 handles the majority of cache hits. L2 is only accessed on L1 miss.

**Cold Start**: On worker restart, L1 is empty. First requests will hit L2 until L1 warms up.

## Monitoring

### Health Check
```bash
GET /health
```
Returns cache connectivity status and metrics for all cache layers.

### Cache Stats
```bash
GET /internal/cache/stats
X-Retry-Secret: <your_retry_secret>
```
Returns detailed metrics per cache:
- `hits` / `misses` / `hit_rate`
- `l2_hits` / `l2_misses`
- `l1_size` / `l1_max_size`

### Key Metrics to Watch

| Metric | Healthy Range | Action if Outside Range |
|--------|---------------|------------------------|
| Overall hit rate | > 90% | Increase L1 size or TTL |
| L1 utilization | < 80% | Decrease size to save memory |
| L2 errors | 0 | Check database connectivity |
| L2 latency | < 10ms | Check PostgreSQL performance |

## Deployment

### Applying the Migration

The distributed cache requires migration 013:

```bash
# Option 1: Using the migration runner
.venv/bin/python migrate.py

# Option 2: Apply via Supabase SQL Editor
# Copy contents of schema.sql
```

### Environment Variables

No new environment variables are required. The cache uses the existing `SUPABASE_SERVICE_ROLE_KEY` for L2 access.

### Zero-Downtime Deployment

1. Apply migration 013 to database
2. Deploy new code
3. Workers will automatically use L1 + L2
4. No cache warmup required (L2 serves as fallback)

## Troubleshooting

### Cache Not Sharing Across Workers

**Symptom**: Cache hit rates are low, or data appears inconsistent between workers.

**Cause**: Migration 013 not applied, or `SUPABASE_SERVICE_ROLE_KEY` missing.

**Action**:
1. Verify migration 013 is applied: check for `cache_entries` table
2. Verify `SUPABASE_SERVICE_ROLE_KEY` is set
3. Restart workers to clear stale in-memory caches

### High L2 Latency

**Symptom**: Requests are slower than expected.

**Cause**: PostgreSQL is overloaded, or network latency is high.

**Action**:
1. Check PostgreSQL CPU and connection count
2. Consider increasing L1 size to reduce L2 traffic
3. Check network latency between app and database

### Cache Growing Unbounded

**Symptom**: `cache_entries` table is growing indefinitely.

**Cause**: TTL is too long, or `cache_cleanup()` is not being called.

**Action**:
1. Reduce TTL values in settings
2. Call `cache_cleanup()` manually or via cron
3. Check for long-running transactions preventing cleanup

## Tradeoffs

| Decision | Tradeoff |
|----------|----------|
| L1 per-worker | Faster access, but inconsistent across workers |
| L2 PostgreSQL | Consistent, but adds ~1-5ms latency |
| JSONB values | Flexible schema, but larger storage |
| No cache invalidation pub/sub | Simpler architecture, but explicit deletes required |
| OAuth rate-limit in-memory | Faster, but per-worker only |
