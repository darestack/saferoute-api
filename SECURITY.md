# Security Policy

## Reporting a Vulnerability

If you find a security issue, please email **security@naisutech.com** or open a private security advisory on GitHub.

Do not open a public issue for security vulnerabilities.

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.x     | Yes (alpha)        |

## Best Practices

- All routes verify route ownership via Supabase RLS before proxying
- Destination URLs are server-side only — never exposed to the client
- Rate limiting is enforced per-route per-IP
- Webhook payloads are not logged by default in production
