# Database Migrations

SafeRoute API uses `schema.sql` as the canonical source of truth for the full
database schema. The complete schema is in `schema.sql`.

For existing databases, apply incremental migrations in lexicographic order.

## Source of truth

`schema.sql` contains the complete schema: tables, indexes, RLS policies,
triggers, and helper functions. Use it for fresh Supabase deployments.

## Incremental migrations

For schema changes, edit `schema.sql` directly. Files are
applied in lexicographic order by `migrate.py`.

```
schema.sql
  008_add_webhook_secrets.sql
  legacy_002_enhancements.sql
  legacy_004_retention.sql
  ...
```

Files prefixed with `legacy_` are historical migrations that predate the
consolidated `schema.sql`. They are retained for reference but are not needed
for new deployments.

## Running migrations

### Supabase CLI (recommended)

```bash
supabase migration new <description>
supabase migration up
```

### Supabase SQL Editor

For fresh deployments or quick schema updates, paste the contents of `schema.sql` into the Supabase SQL Editor and run it.

### Custom runner (CI/CD)

If you have a custom migration runner in your CI/CD pipeline, apply migrations using `DATABASE_URL` in the environment. The target database must have the base schema from `schema.sql` already applied.

## Local Postgres (optional)

```bash
docker compose up -d postgres
```

This starts a plain Postgres 16 container. It does not apply the Supabase schema automatically; use the Supabase CLI for a complete local stack.
