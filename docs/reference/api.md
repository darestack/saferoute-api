# SafeRoute API Reference

## Base URL

```
https://saferoute-api.vercel.app
```

All endpoints are prefixed with `/v1` unless noted.

## Authentication

Protected routes require a Bearer token from Supabase Auth:

```
Authorization: Bearer <supabase-access-token>
```

Internal endpoints require the shared retry secret:

```
X-Retry-Secret: <RETRY_ENDPOINT_SECRET>
```

## Endpoints

### 1. Proxy Webhook
**POST** `/v1/route/{slug}`

Receives incoming webhooks, validates signatures and rate limits, and forwards the payload to the configured destination URL.

**Form Validation:**
If the route has a `form_schema` configured, the proxy validates required fields, types (string/email/number), and constraints (max_length, min, max) before forwarding. Invalid requests return `400 Bad Request` and are not delivered.

**Spam Shield:**
- **Honeypot**: If `spam_honeypot_field` is set and that field is non-empty, the request is silently dropped with `400`.
- **User-Agent blocking**: If `spam_blocked_ua` contains substrings that match the `User-Agent`, the request is rejected with `403`.
- **Country blocking**: If `spam_allowed_countries` is set, only requests from those countries are allowed (requires IP geolocation).

**Headers:**
- `X-API-Key` (optional): API Key for authentication.
- `X-Hub-Signature-256` (optional): HMAC SHA-256 signature for payload verification.
- `X-Webhook-Signature` (optional): Alternative signature header.
- `Idempotency-Key` (optional): Key to ensure idempotent deliveries.

**Responses:**
- `200 OK`: Returns the status of the forwarding action and the destination's response status code.
- `400 Bad Request`: Invalid payload, invalid destination, form validation failure, or spam detected.
- `401 Unauthorized`: Missing or invalid signatures/API keys.
- `403 Forbidden`: User-Agent or country blocked.
- `429 Too Many Requests`: Client exceeded rate limit.
- `500 Internal Server Error`: Application errors.

### 2. List Routes
**GET** `/v1/routes`

List all routes owned by the authenticated user. Supports pagination.

**Query Parameters:**
- `limit` (optional): Maximum number of routes to return (default: 20, max: 100).
- `offset` (optional): Number of routes to skip (default: 0).

**Responses:**
- `200 OK`: Array of route objects.
- `401 Unauthorized`: Missing or invalid token.

### 3. Create Route
**POST** `/v1/routes`

Create a new proxy route for the authenticated user.

**Request Body:**
```json
{
  "name": "Contact Form",
  "destination_url": "https://hooks.zapier.com/hooks/catch/...",
  "method": "POST",
  "form_schema": {
    "fields": {
      "name": {"type": "string", "required": true, "max_length": 100},
      "email": {"type": "email", "required": true},
      "message": {"type": "string", "required": true, "max_length": 500}
    }
  },
  "spam_honeypot_field": "honeypot",
  "spam_blocked_ua": ["bot", "scraper"],
  "spam_allowed_countries": ["US", "GB", "CA"]
}
```

**Responses:**
- `201 Created`: Route created with `slug` and `api_key`.
- `400 Bad Request`: Invalid destination URL.
- `401 Unauthorized`: Missing or invalid token.

### 4. Get Route
**GET** `/v1/routes/{route_id}`

Retrieve a single route by its internal UUID.

**Responses:**
- `200 OK`: Route object.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route does not exist or belongs to another user.

### 5. Update Route
**PUT** `/v1/routes/{route_id}`

Update an existing route's configuration.

**Responses:**
- `200 OK`: Updated route object.
- `400 Bad Request`: Invalid update data.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route does not exist.

### 6. Delete Route
**DELETE** `/v1/routes/{route_id}`

Delete a route and all associated data.

**Responses:**
- `204 No Content`: Route deleted.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route does not exist.

### 7. Rotate API Key
**POST** `/v1/routes/{route_id}/rotate-key`

Generate a new API key for the route. The new key is returned only once.

**Responses:**
- `200 OK`: Route with new `api_key`.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route does not exist.

### 8. List Webhook Logs
**GET** `/v1/routes/{route_id}/logs`

List webhook delivery logs for a route (newest first, paginated).

**Query Parameters:**
- `limit` (optional): Maximum number of logs to return (default: 20, max: 100).
- `offset` (optional): Number of logs to skip (default: 0).

**Responses:**
- `200 OK`: Array of log objects.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route does not exist.

### 9. Delete Route Logs
**DELETE** `/v1/routes/{route_id}/logs`

Delete all webhook logs for a route. The route itself is preserved.

**Responses:**
- `204 No Content`: Logs deleted.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route does not exist.

### 10. Route Stats
**GET** `/v1/routes/{route_id}/stats`

Get aggregated delivery statistics for a route.

**Responses:**
- `200 OK`: Stats object with delivery metrics.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route does not exist.

### 11. List Failures
**GET** `/v1/routes/{route_id}/failures`

List exhausted webhook delivery failures for a route. Uses cursor-based pagination.

**Query Parameters:**
- `cursor` (optional): Pagination cursor (ISO 8601 timestamp of the last item from the previous page).
- `limit` (optional): Maximum number of failures to return (default: 20).

**Responses:**
- `200 OK`: Paginated list of failure objects with `next_cursor`.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route does not exist.

### 12. Retry Failed Webhook
**POST** `/v1/routes/{route_id}/failures/{log_id}/retry`

Manually retry a failed webhook delivery.

**Responses:**
- `200 OK`: Retry queued confirmation.
- `400 Bad Request`: Only exhausted deliveries can be retried.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route or log not found.

### 13. OAuth Login
**GET** `/auth/oauth/{provider}`

Initiate OAuth flow (Google or GitHub).

**Responses:**
- `200 OK`: OAuth authorization URL.

### 14. OAuth Callback
**GET** `/auth/callback`

Handle OAuth provider callback and exchange code for JWT.

**Responses:**
- `302 Redirect`: Redirect to frontend with JWT token.
- `400 Bad Request`: Invalid OAuth state or code.

### 15. Health Check
**GET** `/health`

Check API, database, and cache connectivity.

**Responses:**
- `200 OK`: Health status with database and cache connectivity.
- `503 Service Unavailable`: Database or cache unreachable.

**Response Body:**
```json
{
  "status": "healthy",
  "database": "connected",
  "cache": "connected",
  "cache_metrics": {
    "user_cache": {"hits": 1234, "misses": 56, "hit_rate": 0.957, "l1_size": 450, "l1_max_size": 1000},
    "route_cache": {"hits": 5678, "misses": 123, "hit_rate": 0.979, "l1_size": 320, "l1_max_size": 500},
    "geolocation_cache": {"hits": 9012, "misses": 234, "hit_rate": 0.974, "l1_size": 2800, "l1_max_size": 4096},
    "api_key_cache": {"hits": 3456, "misses": 78, "hit_rate": 0.978, "l1_size": 380, "l1_max_size": 500}
  },
  "service": "SafeRoute API"
}
```

### 16. Process Retries (Internal)
**POST** `/internal/process-retries`

Cron-triggered endpoint that scans the `webhook_logs` table for failed webhook deliveries and processes them with exponential backoff.

**Headers:**
- `X-Retry-Secret` (required): Shared secret matching `RETRY_ENDPOINT_SECRET`.

**Responses:**
- `200 OK`: Summary of processed retries.
- `401 Unauthorized`: Invalid retry secret.

**Response Body:**
```json
{
  "processed": 5,
  "results": [
    {
      "log_id": 123,
      "retry_count": 1,
      "status_code": 200,
      "outcome": "succeeded"
    }
  ]
}
```

### 17. Cleanup (Internal)
**POST** `/internal/cleanup`

Cron-triggered endpoint that prunes expired idempotency keys, PKCE verifiers, and webhook logs to bounds database size.

**Headers:**
- `X-Retry-Secret` (required): Shared secret matching `RETRY_ENDPOINT_SECRET`.

**Query Parameters:**
- `keep_days` (optional): Number of days of logs to retain (default: 30).

**Responses:**
- `200 OK`: Cleanup statistics.
- `401 Unauthorized`: Invalid retry secret.

**Response Body:**
```json
{
  "webhook_logs_removed": 150,
  "rate_limits_cleaned": true,
  "pkce_verifiers_cleaned": true,
  "idempotency_cache_cleaned": true,
  "keep_days": 30
}
```

### 18. Outbound Health Check (Internal)
**GET** `/internal/health/outbound`

Verifies that the API can successfully make egress requests to the public internet.

**Headers:**
- `X-Retry-Secret` (required): Shared secret matching `RETRY_ENDPOINT_SECRET`.

**Responses:**
- `200 OK`: Connectivity status and egress latency.
- `401 Unauthorized`: Invalid retry secret.

**Response Body:**
```json
{
  "status": "healthy",
  "target": "https://www.google.com/generate_204",
  "status_code": 204,
  "duration_ms": 45
}
```

### 19. Cache Statistics (Internal)
**GET** `/internal/cache/stats`

Return detailed metrics for all distributed caches (L1 in-memory + L2 PostgreSQL).

**Headers:**
- `X-Retry-Secret` (required): Shared secret matching `RETRY_ENDPOINT_SECRET`.

**Responses:**
- `200 OK`: Cache metrics for all cache layers.
- `401 Unauthorized`: Invalid retry secret.
- `500 Internal Server Error`: Failed to retrieve cache stats.

**Response Body:**
```json
{
  "caches": {
    "user_cache": {"hits": 1234, "misses": 56, "hit_rate": 0.957, "l2_hits": 100, "l2_misses": 10, "l1_size": 450, "l1_max_size": 1000},
    "route_cache": {"hits": 5678, "misses": 123, "hit_rate": 0.979, "l2_hits": 200, "l2_misses": 20, "l1_size": 320, "l1_max_size": 500},
    "geolocation_cache": {"hits": 9012, "misses": 234, "hit_rate": 0.974, "l2_hits": 500, "l2_misses": 50, "l1_size": 2800, "l1_max_size": 4096},
    "api_key_cache": {"hits": 3456, "misses": 78, "hit_rate": 0.978, "l2_hits": 150, "l2_misses": 15, "l1_size": 380, "l1_max_size": 500}
  },
  "aggregate": {
    "total_hits": 19380,
    "total_misses": 491,
    "total_l2_hits": 950,
    "total_l2_misses": 95,
    "overall_hit_rate": 0.975,
    "total_l1_size": 3950,
    "total_l1_max_size": 6096,
    "utilization_pct": 64.8
  }
}
```

### 20. Initialize Payment
**POST** `/v1/payments/initialize`

Create a Paystack payment for a credit pack purchase.

**Headers:**
- `Authorization: Bearer <supabase-access-token>` (required)

**Request Body:**
```json
{
  "tier": "starter",
  "email": "user@example.com"
}
```

**Responses:**
- `200 OK`: Paystack checkout URL and transaction reference.
- `401 Unauthorized`: Invalid or missing JWT.
- `500 Internal Server Error`: Payment system not configured or initialization failed.

**Response Body:**
```json
{
  "authorization_url": "https://checkout.paystack.com/...",
  "reference": "sr_user-123_starter",
  "amount": 250000,
  "currency": "NGN"
}
```

### 21. Verify Payment
**GET** `/v1/payments/verify/{reference}`

Verify a Paystack payment and credit the user's account.

**Headers:**
- `Authorization: Bearer <supabase-access-token>` (required)

**Responses:**
- `200 OK`: Payment verification result with credits added.
- `401 Unauthorized`: Invalid or missing JWT.
- `404 Not Found`: Transaction not found.
- `500 Internal Server Error`: Payment verification failed.

**Response Body:**
```json
{
  "status": "success",
  "reference": "sr_user-123_starter",
  "amount": 250000,
  "credits_added": 1000,
  "new_balance": 1100
}
```

### 22. Payment History
**GET** `/v1/payments/history`

List payment transactions for the authenticated user.

**Headers:**
- `Authorization: Bearer <supabase-access-token>` (required)

**Query Parameters:**
- `limit` (optional): Number of results per page (default: 20, max: 100).
- `offset` (optional): Number of results to skip (default: 0).

**Responses:**
- `200 OK`: List of payment transactions.
- `401 Unauthorized`: Invalid or missing JWT.

**Response Body:**
```json
[
  {
    "id": "tx-uuid",
    "reference": "sr_user-123_starter",
    "amount": 250000,
    "currency": "NGN",
    "tier": "starter",
    "credits_to_add": 1000,
    "status": "success",
    "created_at": "2026-07-17T10:00:00Z"
  }
]
```

### 23. Paystack Webhook
**POST** `/v1/webhooks/paystack`

Handle Paystack webhook events. Verifies webhook signature using HMAC-SHA512.

**Headers:**
- `X-Paystack-Signature` (required): HMAC-SHA512 signature of request body.

**Request Body:**
```json
{
  "event": "charge.success",
  "data": {
    "reference": "sr_user-123_starter",
    "status": "success",
    "amount": 250000
  }
}
```

**Responses:**
- `200 OK`: Webhook processed.
- `401 Unauthorized`: Invalid webhook signature.

### 24. Admin Credit Adjustment
**POST** `/v1/admin/credits/adjust`

Manually adjust a user's credit balance. Admin-only endpoint.

**Headers:**
- `X-Admin-Secret` (required): Shared secret matching `ADMIN_SECRET_KEY`.

**Query Parameters:**
- `user_id` (required): User UUID to adjust credits for.
- `amount` (required): Amount to add (positive) or subtract (negative).
- `reason` (optional): Reason for adjustment (default: "Manual adjustment by admin").

**Responses:**
- `200 OK`: Adjustment result with new balance.
- `401 Unauthorized`: Invalid admin secret.

**Response Body:**
```json
{
  "user_id": "user-uuid",
  "amount": 1000,
  "new_balance": 1100,
  "reason": "Manual adjustment by admin"
}
```
