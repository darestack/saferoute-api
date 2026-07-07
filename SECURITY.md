# Security Policy

## Reporting a Vulnerability

If you find a security issue, please open a private security advisory on GitHub or email the maintainers.

Do not open a public issue for security vulnerabilities.

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.x     | Yes (alpha)        |

## Best Practices

- Route-management endpoints verify ownership before exposing route data
- Destination URLs are server-side only — never exposed to the client
- Rate limiting is enforced per-route per-IP
- Outbound destinations are restricted to public HTTPS targets with no-cost application-level SSRF checks
- Webhook payloads and destination responses are stored in delivery logs. Avoid sending sensitive payloads unless your deployment retention, access controls, and privacy policy allow it.
