-- ========================================
-- Distributed Cache Table (L2 - PostgreSQL)
-- ========================================
-- Shared cache accessible to all workers/processes via PostgreSQL.
-- Used as L2 fallback when L1 in-memory cache misses or evicts.

create table public.cache_entries (
    key text primary key,
    value jsonb not null,
    expires_at timestamp with time zone not null,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

create index idx_cache_entries_expires_at on public.cache_entries(expires_at);

-- Service role full access only (no user-level access needed for cache)
alter table public.cache_entries enable row level security;

create policy "Service role full access cache_entries"
    on public.cache_entries for all
    to service_role
    using (true);

-- ========================================
-- Cache RPC Functions
-- ========================================

-- Get a cached value by key. Returns NULL if not found or expired.
create or replace function public.cache_get(p_key text)
returns jsonb as $$
begin
    return (
        select value
        from public.cache_entries
        where key = p_key
          and expires_at > timezone('utc'::text, now())
        limit 1
    );
end;
$$ language plpgsql stable;

-- Set a cached value with TTL in seconds.
-- Uses ON CONFLICT (upsert) for atomic updates.
create or replace function public.cache_set(
    p_key text,
    p_value jsonb,
    p_ttl_seconds integer default 300
)
returns void as $$
begin
    insert into public.cache_entries (key, value, expires_at)
    values (
        p_key,
        p_value,
        timezone('utc'::text, now()) + (p_ttl_seconds || ' seconds')::interval
    )
    on conflict (key) do update
    set value = excluded.value,
        expires_at = excluded.expires_at;
end;
$$ language plpgsql;

-- Delete a cached value by key.
create or replace function public.cache_delete(p_key text)
returns void as $$
begin
    delete from public.cache_entries where key = p_key;
end;
$$ language plpgsql;

-- Clean up expired cache entries. Returns the number of rows removed.
create or replace function public.cache_cleanup()
returns integer as $$
declare
    v_removed integer;
begin
    with removed as (
        delete from public.cache_entries
        where expires_at <= timezone('utc'::text, now())
        returning 1
    )
    select count(*) into v_removed from removed;

    return v_removed;
end;
$$ language plpgsql;
