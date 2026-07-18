# Security Policy

## Reporting a Vulnerability

If you find a security issue, please open a private security advisory on GitHub or email the maintainers at deeprince2020@gmail.com.

Do not open a public issue for security vulnerabilities.

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.x     | Yes (alpha)        |

## Security Controls

- Route-management endpoints verify ownership before exposing route data
- Destination URLs are server-side only — never exposed to the client
- Rate limiting is enforced per-route per-IP
- Outbound destinations are restricted to public HTTPS targets with application-level SSRF checks
- Webhook payloads and destination responses are stored in delivery logs. Avoid sending sensitive payloads unless your deployment retention, access controls, and privacy policy allow it
- All internal endpoints (`/internal/process-retries`, `/internal/cleanup`) require a shared secret via constant-time header comparison
- JWT tokens are validated against Supabase JWKS with audience and issuer checks
- Webhook secrets are encrypted with Fernet before storage; plaintext fallback is only permitted outside production

## Known Limitations and Tradeoffs

### DNS Rebinding

Route creation performs DNS resolution to validate the destination hostname resolves to a public IP. At request time, the proxy skips DNS re-resolution for latency reasons. This means a malicious DNS provider could return a public IP at creation time and a private IP at request time.

**Tradeoff:** Per-request DNS resolution adds latency on the hot path and reintroduces a TOCTOU window. Full egress-firewall controls are out of scope for the $0 cost target. The write-time DNS check is the primary defense.

### In-Memory Caches

Route, user, and API key caches are stored in-process. In multi-worker deployments, each worker maintains its own cache. Cache invalidation takes up to the TTL (30s for routes, 300s for users/API keys) to propagate across workers.

**Tradeoff:** A multi-process cache requires Redis or Memcached, which adds operational complexity. Supabase free tier does not include Redis. The current implementation is acceptable for single-worker Vercel deployments.

### IP Spoofing via X-Forwarded-For

`X-Forwarded-For` is only trusted when the direct TCP peer IP is explicitly listed in `TRUSTED_PROXIES`. If `TRUSTED_PROXIES` is empty, the direct peer IP is used instead of trusting `X-Forwarded-For`.

**Tradeoff:** This prevents IP spoofing but requires operators to configure `TRUSTED_PROXIES` when behind a CDN. Without this setting, all clients behind the CDN will appear to come from the CDN's IP address.

## Key Rotation

### Encryption Key Rotation

To rotate the `ENCRYPTION_KEY`:

1. Set the new key in your environment
2. Restart the application
3. Re-encrypt existing `safe_plain:` and `v1:` webhook secrets by reading and updating each route

**Note:** The application caches the Fernet instance in memory. After rotation, call `clear_fernet_cache()` or restart the process to use the new key.

### API Key Rotation

Use `POST /auth/routes/{route_id}/rotate-key` to rotate a route's API key. The new key is returned once and cannot be retrieved again. The old key is invalidated immediately.
