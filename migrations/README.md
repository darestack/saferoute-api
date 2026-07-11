# Database Migrations

This directory contains versioned SQL migrations for the SafeRoute API schema.

## Convention

- Files are named `NNN_description.sql` where `NNN` is a zero-padded sequence number.
- Each migration is idempotent: it can be applied safely to an already-updated database.
- Migrations are applied in order by the deployment process.

## Current Migrations

- `schema.sql` — initial schema
- `migration_002_enhancements.sql`
- `migration_004_retention.sql`
- `migration_005_rate_limiter_fix.sql`
- `migration_006_webhook_logs_updated_at.sql`
