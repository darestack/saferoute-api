# SafeRoute API Reference

## Base URL

```
https://saferoute-api.vercel.app
```

## Authentication

All authenticated API requests require a Supabase JWT access token in the Authorization header:

```
Authorization: Bearer <supabase-access-token>
```

Route-level authentication uses API keys for webhook proxy requests.

## Endpoints

### Create Route

Create a new form route.

```http
POST /v1/routes
```

**Request Body:**
```json
{
  "name": "Contact Form",
  "destination_url": "https://example.com/webhook"
}
```

**Response:**
```json
{
  "id": 123,
  "name": "Contact Form",
  "slug": "contact",
  "destination_url": "https://example.com/webhook",
  "is_active": true,
  "created_at": "2026-01-01T00:00:00Z"
}
```

### List Routes

Get all routes for the authenticated user.

```http
GET /v1/routes
```

**Response:**
```json
[
  {
    "id": 123,
    "name": "Contact Form",
    "slug": "contact",
    "destination_url": "https://example.com/webhook",
    "is_active": true,
    "requests_count": 42,
    "created_at": "2026-01-01T00:00:00Z"
  }
]
```

### Get Route

Get a specific route by ID.

```http
GET /v1/routes/{route_id}
```

### Update Route

Update an existing route.

```http
PATCH /v1/routes/{route_id}
```

**Request Body:**
```json
{
  "name": "Updated Name",
  "destination_url": "https://example.com/new-webhook"
}
```

### Delete Route

Delete a route.

```http
DELETE /v1/routes/{route_id}
```

### Submit Form

Submit a form to a route. This is the public endpoint.

```http
POST /v1/routes/{slug}
```

**Request Body:**
```json
{
  "name": "John Doe",
  "email": "john@example.com",
  "message": "Hello!"
}
```

**Query Parameters:**
- `turnstile_token` (optional): Turnstile verification token

**Response (Success):**
```json
{
  "success": true,
  "message": "Form submitted successfully"
}
```

**Response (Spam Blocked):**
```json
{
  "success": false,
  "error": "Spam detected"
}
```

### List Logs

Get webhook delivery logs for a route.

```http
GET /v1/routes/{route_id}/logs
```

**Query Parameters:**
- `limit` (optional): Number of logs to return (default: 50, max: 100)

**Response:**
```json
[
  {
    "id": 123,
    "route_id": "uuid",
    "status_code": 200,
    "duration_ms": 45,
    "created_at": "2026-01-01T00:00:00Z"
  }
]
```

### Delete Logs

Delete all logs for a route.

```http
DELETE /v1/routes/{route_id}/logs
```

### Replay Log

Manually replay a failed webhook delivery.

```http
POST /v1/routes/{route_id}/logs/{log_id}/replay
```

## Spam Shield

SafeRoute includes built-in spam protection:

### Honeypot

Add a hidden field to your form. Bots that fill all fields will be blocked.

```html
<input type="text" name="_honeypot" style="display: none;">
```

### Turnstile

Enable Cloudflare Turnstile for invisible bot verification.

```json
{
  "turnstile_enabled": true,
  "turnstile_site_key": "your-site-key"
}
```

Include the token in form submission:
```html
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
<div class="cf-turnstile" data-sitekey="your-site-key"></div>
```

## Error Codes

| Status | Code | Description |
|--------|------|-------------|
| 400 | `invalid_request` | Missing required fields |
| 401 | `unauthorized` | Invalid or missing API key |
| 403 | `forbidden` | Route not found or inactive |
| 404 | `not_found` | Resource not found |
| 429 | `rate_limited` | Too many requests |
| 500 | `server_error` | Internal server error |

## Rate Limiting

SafeRoute uses credit-based access. Each successfully processed request consumes 1 credit. Spam blocked by SafeRoute does not consume credits.

| Tier | Credits | Price |
|------|---------|-------|
| Free | 100 credits/month | $0 |
| Starter Pack | 1,000 credits | $5 one-time |
| Builder Pack | 10,000 credits | $25 one-time |
| Agency Pack | 50,000 credits | $75 one-time |

Rate limit headers are included in all responses:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 99
X-RateLimit-Reset: 1704067200
```

## Payments

### Initialize Payment

Initialize a Paystack payment for a credit pack purchase.

```http
POST /v1/payments/initialize
Authorization: Bearer <supabase-access-token>
```

**Request Body:**
```json
{
  "tier": "starter",
  "email": "user@example.com"
}
```

**Response:**
```json
{
  "authorization_url": "https://checkout.paystack.com/...",
  "reference": "sr_user123_starter",
  "amount": 250000,
  "currency": "NGN"
}
```

### Verify Payment

Verify a payment after the user returns from Paystack checkout.

```http
GET /v1/payments/verify/{reference}
Authorization: Bearer <supabase-access-token>
```

**Response:**
```json
{
  "status": "success",
  "reference": "sr_user123_starter",
  "amount": 250000,
  "credits_added": 1000,
  "new_balance": 1100
}
```

### Paystack Webhook

Paystack webhook endpoint for asynchronous payment notifications.

```http
POST /v1/webhooks/paystack
X-Paystack-Signature: <signature>
```

The webhook verifies the signature and processes `charge.success` and `charge.failed` events.
