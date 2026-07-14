# SafeRoute API Architecture

## Overview
SafeRoute API is a high-performance, asynchronous webhook forwarding engine built on FastAPI and Supabase. It provides a secure ingress layer for external webhooks, enforcing rate limits, verifying HMAC signatures, applying payload transformations, and ensuring idempotent delivery to downstream services.

## Architecture Patterns
- **Edge Proxy Model**: Acts as a reverse proxy for incoming webhooks.
- **Asynchronous I/O**: Built entirely on `asyncio` and `httpx` to handle high concurrency without blocking.
- **Stateless Application Layer**: Web workers (Uvicorn/FastAPI) are fully stateless. All durable state, including rate limits, idempotency caches, and retry queues, is offloaded to PostgreSQL (Supabase).
- **Circuit Breaker**: Prevents cascading failures by halting outbound requests to dead downstream services.

## Data Flow (Webhook Delivery)
1. **Ingress**: An external provider (e.g., Stripe, GitHub) POSTs a webhook to `/v1/route/{slug}`.
2. **Security Checks**: 
   - Extract real client IP from `X-Forwarded-For`.
   - Validate payload signature (`X-Hub-Signature-256`) against the route's decrypted secret.
3. **Idempotency**: Check the `idempotency_cache` table via the `Idempotency-Key` header. Return cached response if a duplicate is found.
4. **Rate Limiting**: Atomically increment the IP's request count using the `increment_rate_limit` RPC.
5. **Transformation**: Resolve dot-notation placeholders in the route's `transform_body_template` to reshape the JSON payload.
6. **Egress**: Forward the payload using the shared `httpx.AsyncClient`.
7. **Logging & Retry**: Persist the delivery result to the `webhook_logs` table. If the downstream returns a 5xx, set `retry_status` to `pending`.
8. **Metrics**: Increment the route's delivery counters atomically.

## Security Boundaries
- **SSRF Prevention**: `validate_destination_url_async` ensures destinations are valid HTTP/HTTPS URLs and do not point to internal IP ranges. DNS rebinding is prevented by forcing request-time DNS resolution (`resolve_dns=True`).
- **Database Access**: The application uses the Supabase service-role key for internal queries, bypassing Row-Level Security (RLS) to act as a privileged daemon.
- **Secrets Management**: Webhook secrets are stored symmetrically encrypted in the database.

## Background Jobs
- **/internal/process-retries**: A secured cron endpoint that polls `webhook_logs` for failed deliveries and re-attempts them up to 3 times with exponential backoff.
- **/internal/cleanup**: A secured cron endpoint that prunes expired idempotency keys, old webhook logs, and rate limit buckets to bound database growth.
