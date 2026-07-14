# Database Migrations

SafeRoute API uses versioned SQL migrations to evolve the Supabase/PostgreSQL schema.

## Migration files

Place migration scripts in the `migrations/` directory. The runner supports both
numbered and timestamped filenames:

```
migrations/
  001_create_routes_table.sql
  20240101_120000_add_api_key_hash.sql
```

Files are applied in lexicographic order.

## Running migrations

### Option A: Supabase CLI (recommended)

SafeRoute requires Supabase-specific extensions (`auth` schema, RLS roles).
For local development, use the Supabase CLI:

```bash
supabase init
supabase migration new <description>
supabase migration up
```

### Option B: Custom runner (CI/CD)

```bash
python migrate.py
```

Requires `DATABASE_URL` in the environment. The target database must have the
base schema already applied.

## Base schema

The canonical schema lives in `schema.sql`. Run it once when setting up a new
Supabase project. Do not run it against a plain PostgreSQL instance unless you
also create the required Supabase extensions and roles.

## Local Postgres (optional)

A plain Postgres container is available for testing without Supabase auth:

```bash
docker compose up -d postgres
```

This does **not** apply the base schema automatically; use the Supabase CLI
for a complete local stack.
