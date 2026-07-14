# SafeRoute API Reference

## Endpoints

### 1. Proxy Webhook
**POST** `/v1/route/{slug}`

Receives incoming webhooks, validates signatures and rate limits, and forwards the payload to the configured destination URL.

**Headers:**
- `X-API-Key` (optional): API Key for authentication.
- `X-Hub-Signature-256` (optional): HMAC SHA-256 signature for payload verification.
- `X-Webhook-Signature` (optional): Alternative signature header.
- `Idempotency-Key` (optional): Key to ensure idempotent deliveries.

**Responses:**
- `200 OK`: Returns the status of the forwarding action and the destination's response status code.
- `400 Bad Request`: Invalid payload, invalid destination, etc.
- `401 Unauthorized`: Missing or invalid signatures/API keys.
- `429 Too Many Requests`: Client exceeded rate limit.
- `500 Internal Server Error`: Application errors.

### 2. Process Retries (Internal)
**POST** `/internal/process-retries`

Cron-triggered endpoint that scans the `webhook_logs` table for failed webhook deliveries and processes them with exponential backoff.

**Headers:**
- `X-Retry-Secret` (required): Shared secret matching `RETRY_ENDPOINT_SECRET`.

**Responses:**
- `200 OK`: Summary of processed retries.
- `401 Unauthorized`: Invalid retry secret.

### 3. Cleanup (Internal)
**POST** `/internal/cleanup`

Cron-triggered endpoint that prunes expired idempotency keys, PKCE verifiers, and webhook logs to bounds database size.

**Headers:**
- `X-Retry-Secret` (required): Shared secret matching `RETRY_ENDPOINT_SECRET`.

**Responses:**
- `200 OK`: Cleanup statistics.
- `401 Unauthorized`: Invalid retry secret.

### 4. Outbound Health Check (Internal)
**GET** `/internal/health/outbound`

Verifies that the API can successfully make egress requests to the public internet.

**Headers:**
- `X-Retry-Secret` (required): Shared secret matching `RETRY_ENDPOINT_SECRET`.

**Responses:**
- `200 OK`: Connectivity status and egress latency.
- `401 Unauthorized`: Invalid retry secret.
