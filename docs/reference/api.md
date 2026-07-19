# SafeRoute API Reference

## Base URL

```
https://saferoute-api.vercel.app
```

All endpoints are prefixed with `/v1` unless noted.

All endpoints are prefixed with `/v1` unless noted.

## Authentication

### User-Endpoints (Bearer Token)

Protected routes require a Supabase Auth JWT:

```
Authorization: Bearer <supabase-access-token>
```

### Internal Endpoints (Shared Secret)

Internal/cron endpoints require the retry secret:

```
X-Retry-Secret: <RETRY_ENDPOINT_SECRET>
```

### Admin Endpoints (Admin Secret)

Admin-only endpoints require the admin secret:

```
X-Admin-Secret: <ADMIN_SECRET_KEY>
```

---

## Public Proxy Endpoints

These endpoints are called by external services or browser forms. No authentication required.

### 1. Proxy Webhook — Primary Path
**POST** `/v1/route/{slug}`

Receives incoming webhooks, validates signatures and rate limits, and forwards the payload to the configured destination URL.

### 2. Proxy Webhook — Short Alias
**POST** `/v1/r/{slug}`

Equivalent to `/v1/route/{slug}`. Use this shorter path for form actions.

**Form Validation:**
If the route has a `form_schema` configured, the proxy validates required fields, types (`string`/`email`/`number`), and constraints (`max_length`, `min`, `max`) before forwarding. Invalid requests return `400 Bad Request` and are not delivered.

**Spam Shield:**
- **Honeypot**: If `spam_honeypot_field` is set and that field is non-empty, the request is silently dropped with `400`.
- **User-Agent blocking**: If `spam_blocked_ua` contains substrings matching the `User-Agent`, the request is rejected with `403`.
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

---

## Authenticated User Endpoints

These endpoints require a Supabase Auth Bearer token.

### 3. List Routes
**GET** `/v1/routes`

List all routes owned by the authenticated user. Supports pagination.

**Query Parameters:**
- `limit` (optional): Maximum number of routes to return (default: `20`, max: `100`).
- `offset` (optional): Number of routes to skip (default: `0`).

**Responses:**
- `200 OK`: Array of route objects.
- `401 Unauthorized`: Missing or invalid token.

### 4. Create Route
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

### 5. Get Route
**GET** `/v1/routes/{route_id}`

Retrieve a single route by its internal UUID.

**Responses:**
- `200 OK`: Route object.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route does not exist or belongs to another user.

### 6. Update Route
**PUT** `/v1/routes/{route_id}`

Update an existing route's configuration.

**Responses:**
- `200 OK`: Updated route object.
- `400 Bad Request`: Invalid update data.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route does not exist.

### 7. Delete Route
**DELETE** `/v1/routes/{route_id}`

Delete a route and all associated data.

**Responses:**
- `204 No Content`: Route deleted.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route does not exist.

### 8. Rotate API Key
**POST** `/v1/routes/{route_id}/rotate-key`

Generate a new API key for the route. The new key is returned only once.

**Responses:**
- `200 OK`: Route with new `api_key`.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route does not exist.

### 9. List Webhook Logs
**GET** `/v1/routes/{route_id}/logs`

List webhook delivery logs for a route (newest first, paginated).

**Query Parameters:**
- `limit` (optional): Maximum number of logs to return (default: `20`, max: `100`).
- `offset` (optional): Number of logs to skip (default: `0`).

**Responses:**
- `200 OK`: Array of log objects.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route does not exist.

### 10. Delete Route Logs
**DELETE** `/v1/routes/{route_id}/logs`

Delete all webhook logs for a route. The route itself is preserved.

**Responses:**
- `204 No Content`: Logs deleted.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route does not exist.

### 11. Replay Webhook Log
**POST** `/v1/routes/{route_id}/logs/{log_id}/replay`

Manually replay a single webhook delivery log.

**Responses:**
- `200 OK`: Replay queued confirmation.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route or log not found.

### 12. Route Stats
**GET** `/v1/routes/{route_id}/stats`

Get aggregated delivery statistics for a route.

**Responses:**
- `200 OK`: Stats object with delivery metrics.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route does not exist.

### 13. List Failures
**GET** `/v1/routes/{route_id}/failures`

List exhausted webhook delivery failures for a route. Uses cursor-based pagination.

**Query Parameters:**
- `cursor` (optional): Pagination cursor returned by a previous request. Format is `created_at|id` (composite key to ensure stable ordering when multiple failures share the same timestamp).
- `limit` (optional): Maximum number of failures to return (default: `20`).

**Responses:**
- `200 OK`: Paginated list of failure objects with `next_cursor`.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route does not exist.

### 14. Retry Failed Webhook
**POST** `/v1/routes/{route_id}/failures/{log_id}/retry`

Manually retry a failed webhook delivery.

**Responses:**
- `200 OK`: Retry queued confirmation.
- `400 Bad Request`: Only exhausted deliveries can be retried.
- `401 Unauthorized`: Missing or invalid token.
- `404 Not Found`: Route or log not found.

### 15. Get Current User Profile
**GET** `/v1/me`

Return the currently authenticated user's profile, including credit balance and tier.

**Responses:**
- `200 OK`: User profile object.
- `401 Unauthorized`: Missing or invalid token.

### 16. Initialize Payment
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

### 17. Verify Payment
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

### 18. Payment History
**GET** `/v1/payments/history`

List payment transactions for the authenticated user.

**Headers:**
- `Authorization: Bearer <supabase-access-token>` (required)

**Query Parameters:**
- `limit` (optional): Number of results per page (default: `20`, max: `100`).
- `offset` (optional): Number of results to skip (default: `0`).

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

---

## OAuth Endpoints

### 19. OAuth Login
**GET** `/auth/oauth/{provider}`

Initiate OAuth flow (`google` or `github`).

**Responses:**
- `200 OK`: OAuth authorization URL.

**Response Body:**
```json
{
  "auth_url": "https://accounts.google.com/...",
  "provider": "google"
}
```

### 20. OAuth Callback
**POST** `/auth/callback`

Handle OAuth provider callback and exchange code for JWT.

**Responses:**
- `302 Redirect`: Redirect to frontend with JWT token.
- `400 Bad Request`: Invalid OAuth state or code.

---

## Public Utility Endpoints

### 21. Health Check
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
  "service": "SafeRoute API"
}
```

> **Note:** Detailed cache metrics (hit/miss rates, L1/L2 breakdown) are available on the internal endpoint `/internal/cache/stats`.

### 22. Exchange Rates
**GET** `/rates`

Get exchange rates from base currency to target currencies.

**Query Parameters:**
- `base` (optional): Base currency code (default: `USD`).
- `symbols` (optional): Comma-separated target currency codes (default: `NGN`).

**Responses:**
- `200 OK`: Exchange rate data.

**Response Body:**
```json
{
  "base": "USD",
  "rates": {
    "NGN": 1500.0
  },
  "errors": []
}
```

> **Note:** Per-symbol lookup failures are reported as `null` with the failing symbol recorded in `errors`. A `null` rate means "unavailable" — do not substitute a default.

---

## Internal Endpoints

These endpoints require `X-Retry-Secret: <RETRY_ENDPOINT_SECRET>`.

### 23. Process Retries
**POST** `/internal/process-retries`

Cron-triggered endpoint that scans `webhook_logs` for failed deliveries and retries them with exponential backoff.

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

### 24. Cleanup
**POST** `/internal/cleanup`

Cron-triggered endpoint that prunes expired idempotency keys, PKCE verifiers, and webhook logs to bound database size.

**Headers:**
- `X-Retry-Secret` (required): Shared secret matching `RETRY_ENDPOINT_SECRET`.

**Query Parameters:**
- `keep_days` (optional): Number of days of logs to retain (default: `30`).

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

### 25. Outbound Health Check
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

### 26. Cache Statistics
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

---

## Webhook Endpoints

### 27. Paystack Webhook
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

### 28. Retry Failed Payment Webhooks
**POST** `/v1/webhooks/paystack/retry`

Admin-only endpoint to retry failed payment webhooks.

**Headers:**
- `X-Admin-Secret` (required): Shared secret matching `ADMIN_SECRET_KEY`.

**Responses:**
- `200 OK`: Retry processed.
- `401 Unauthorized`: Invalid admin secret.

---

## Admin Endpoints

### 29. Admin Credit Adjustment
**POST** `/v1/admin/credits/adjust`

Manually adjust a user's credit balance. Admin-only endpoint.

**Headers:**
- `X-Admin-Secret` (required): Shared secret matching `ADMIN_SECRET_KEY`.

**Query Parameters:**
- `user_id` (required): User UUID to adjust credits for.
- `amount` (required): Amount to add (positive) or subtract (negative).
- `reason` (optional): Reason for adjustment (default: `"Manual adjustment by admin"`).

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

---

## Deprecated Endpoints

These endpoints return `410 Gone` and are no longer supported.

### Deprecated: Register
**POST** `/v1/register`

Returns `410 Gone`. Use OAuth (`/auth/oauth/google` or `/auth/oauth/github`) instead.

### Deprecated: Login
**POST** `/v1/login`

Returns `410 Gone`. Use OAuth (`/auth/oauth/google` or `/auth/oauth/github`) instead.
