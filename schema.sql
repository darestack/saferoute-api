-- SafeRoute API Database Schema
-- Run this in your Supabase SQL Editor

-- Enable extensions
create extension if not exists "uuid-ossp";
create extension if not exists "pgcrypto";

-- ========================================
-- Routes Table
-- ========================================
create table public.routes (
    id uuid default uuid_generate_v4() primary key,
    user_id uuid not null references auth.users(id) on delete cascade,
    name text not null,
    slug text not null unique,
    destination_url text not null,
    method text not null default 'POST',
    headers jsonb default '{}'::jsonb,
    is_active boolean default true,
    requests_count integer default 0,
    last_used_at timestamp with time zone,
    api_key_prefix text,
    api_key_hash text,
    webhook_secret text,
    webhook_secrets jsonb default '[]'::jsonb,
    rate_limit integer default 30,
    max_payload_bytes integer default 1048576,
    max_concurrent_deliveries integer default 10,
    content_scan_rules jsonb default '[]'::jsonb,
    signing_secret text,
    transform_headers jsonb default '{}'::jsonb,
    transform_body_template text,
    form_schema jsonb default '{}'::jsonb,
    spam_honeypot_field text,
    spam_blocked_ua text[] default '{}',
    spam_allowed_countries text[] default '{}',
    spam_blocked_ips text[] default '{}',
    turnstile_enabled boolean default false,
    turnstile_site_key text,
    turnstile_secret_key text,
    email_notifications jsonb default '{}'::jsonb,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    updated_at timestamp with time zone default timezone('utc'::text, now()) not null
);

-- Index for fast lookups by slug (used in proxy path)
create index idx_routes_slug on public.routes(slug);

-- Partial index for the active-route proxy lookup (slug + is_active), the
-- hottest read path. Restricting to active rows keeps the index small.
create index idx_routes_slug_active on public.routes(slug) where is_active;

-- Index for user's routes
create index idx_routes_user_id on public.routes(user_id);

-- Index for API key lookups
create index idx_routes_api_key_hash on public.routes(api_key_hash);

-- ========================================
-- Webhook Logs Table
-- ========================================
create table public.webhook_logs (
    id bigint generated always as identity primary key,
    route_id uuid not null references public.routes(id) on delete cascade,
    status_code integer,
    request_body jsonb,
    response_body text,
    response_headers jsonb,
    error_message text,
    ip_address inet,
    user_agent text,
    duration_ms integer,
    content_type text,
    retry_count integer default 0,
    max_retries integer default 3,
    next_retry_at timestamp with time zone,
    retry_status text default 'none' check (retry_status in ('none', 'pending', 'retrying', 'exhausted', 'succeeded')),
    idempotency_key text,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    updated_at timestamp with time zone default timezone('utc'::text, now()) not null
);

-- Index for route logs lookup
create index idx_webhook_logs_route_id on public.webhook_logs(route_id);

-- Index for time-based queries
create index idx_webhook_logs_created_at on public.webhook_logs(created_at desc);

-- Index for retry processing
create index idx_webhook_logs_retry on public.webhook_logs(retry_status, next_retry_at)
    where retry_status = 'pending';

-- ========================================
-- Idempotency Cache Table
-- ========================================
create table public.idempotency_cache (
    id uuid default uuid_generate_v4() primary key,
    route_id uuid not null references public.routes(id) on delete cascade,
    idempotency_key text not null,
    response_status integer not null,
    response_body text,
    response_headers jsonb,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    unique(route_id, idempotency_key)
);

create index idx_idempotency_cache_lookup
    on public.idempotency_cache(route_id, idempotency_key);

-- Atomically claim an idempotency key to prevent duplicate processing.
-- Returns true if the claim succeeded (caller is the leader), false if
-- another request already claimed this key.
create or replace function public.claim_idempotency_key(
    p_route_id uuid,
    p_idempotency_key text
)
returns boolean as $$
begin
    insert into public.idempotency_cache (route_id, idempotency_key, response_status)
    values (p_route_id, p_idempotency_key, 0)
    on conflict (route_id, idempotency_key) do nothing;

    return found;
end;
$$ language plpgsql;

-- ========================================
-- Rate Limits Table
-- ========================================
-- UNLOGGED table for high-throughput rate-limit writes. Unlogged tables skip
-- WAL, making inserts/updates roughly 2-5x faster at the cost of not being
-- crash-recoverable. Rate limit buckets are ephemeral by design (they expire
-- after 60s and are cleaned up hourly), so data loss on crash is acceptable.
create unlogged table public.rate_limits (
    id uuid default uuid_generate_v4() primary key,
    route_id uuid not null references public.routes(id) on delete cascade,
    ip_address inet not null,
    request_count integer default 1,
    window_start timestamp with time zone default timezone('utc'::text, now()) not null,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    unique(route_id, ip_address, window_start)
);

create index idx_rate_limits_route_ip on public.rate_limits(route_id, ip_address);

-- ========================================
-- PKCE Verifiers Table (for OAuth flows)
-- ========================================
create table public.pkce_verifiers (
    id uuid default uuid_generate_v4() primary key,
    code_challenge text not null unique,
    code_verifier text not null,
    state text not null unique,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

create index idx_pkce_verifiers_challenge on public.pkce_verifiers(code_challenge);
create index idx_pkce_verifiers_state on public.pkce_verifiers(state);

-- ========================================
-- Row Level Security (RLS)
-- ========================================
alter table public.routes enable row level security;
alter table public.webhook_logs enable row level security;
alter table public.rate_limits enable row level security;
alter table public.pkce_verifiers enable row level security;
alter table public.idempotency_cache enable row level security;

-- Routes: Users can only access their own routes
create policy "Users can view own routes"
    on public.routes for select
    to authenticated
    using (auth.uid() = user_id);

create policy "Users can create own routes"
    on public.routes for insert
    to authenticated
    with check (auth.uid() = user_id);

create policy "Users can update own routes"
    on public.routes for update
    to authenticated
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

create policy "Users can delete own routes"
    on public.routes for delete
    to authenticated
    using (auth.uid() = user_id);

-- Service role can do anything (for proxy backend)
create policy "Service role full access routes"
    on public.routes for all
    to service_role
    using (true);

-- Webhook logs: Users can view logs for their own routes
create policy "Users can view own route logs"
    on public.webhook_logs for select
    to authenticated
    using (
        exists (
            select 1 from public.routes
            where routes.id = webhook_logs.route_id
            and routes.user_id = auth.uid()
        )
    );

-- Service role full access to webhook_logs
create policy "Service role full access webhook_logs"
    on public.webhook_logs for all
    to service_role
    using (true);

-- Rate limits: Service role full access
create policy "Service role full access rate_limits"
    on public.rate_limits for all
    to service_role
    using (true);

-- PKCE verifiers: Service role full access only
create policy "Service role full access pkce_verifiers"
    on public.pkce_verifiers for all
    to service_role
    using (true);

-- Idempotency cache: Service role full access only
create policy "Service role full access idempotency_cache"
    on public.idempotency_cache for all
    to service_role
    using (true);

-- ========================================
-- Webhook failures (dead-letter queue)
-- ========================================
create table public.webhook_failures (
    id uuid default uuid_generate_v4() primary key,
    route_id uuid not null references public.routes(id) on delete cascade,
    webhook_log_id bigint,
    status_code integer,
    error_message text,
    request_body jsonb,
    response_body text,
    ip_address inet,
    user_agent text,
    retry_count integer default 0,
    max_retries integer default 3,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    updated_at timestamp with time zone default timezone('utc'::text, now()) not null
);

create index idx_webhook_failures_route_id on public.webhook_failures(route_id);
create index idx_webhook_failures_created_at on public.webhook_failures(created_at);

alter table public.webhook_failures enable row level security;

create policy "Service role full access webhook_failures"
    on public.webhook_failures for all
    to service_role
    using (true);

-- ========================================
-- Triggers
-- ========================================
create or replace function public.update_updated_at()
returns trigger as $$
begin
    new.updated_at = timezone('utc'::text, now());
    return new;
end;
$$ language plpgsql;

create trigger update_webhook_failures_updated_at
    before update on public.webhook_failures
    for each row
    execute function public.update_updated_at();

create trigger update_routes_updated_at
    before update on public.routes
    for each row
    execute function public.update_updated_at();

create trigger update_webhook_logs_updated_at
    before update on public.webhook_logs
    for each row
    execute function public.update_updated_at();

-- ========================================
-- Helper Functions
-- ========================================
-- Increment route request count atomically
create or replace function public.increment_route_count(p_route_id uuid)
returns void as $$
begin
    update public.routes
    set
        requests_count = requests_count + 1,
        last_used_at = timezone('utc'::text, now())
    where id = p_route_id;
end;
$$ language plpgsql;

-- Atomically increment the rate-limit counter for a (route, ip) pair using a
-- fixed 60-second bucket keyed on `window_start`.
--
-- Uses a single INSERT ... ON CONFLICT DO UPDATE to minimize lock contention
-- under concurrent bursts. The UNLOGGED table further improves write throughput
-- by skipping WAL.
create or replace function public.increment_rate_limit(
    p_route_id uuid,
    p_ip inet,
    p_max_requests integer
)
returns table (
    success boolean,
    new_count integer
) as $$
declare
    v_bucket timestamptz := date_bin(
        interval '60 seconds',
        timezone('utc', now()),
        '1970-01-01 00:00:00+00'::timestamptz
    );
begin
    insert into public.rate_limits (route_id, ip_address, request_count, window_start)
    values (p_route_id, p_ip, 1, v_bucket)
    on conflict (route_id, ip_address, window_start) do update
    set request_count = rate_limits.request_count + 1
    where rate_limits.request_count < p_max_requests
    returning request_count into new_count;

    if found then
        success := true;
        return next;
        return;
    end if;

    -- Row exists but is already at/over the limit. Return the current count
    -- so the caller can report how many requests remain.
    select request_count into new_count
    from public.rate_limits
    where route_id = p_route_id
      and ip_address = p_ip
      and window_start = v_bucket;

    success := false;
    return next;
    return;
end;
$$ language plpgsql;

-- Clean up old rate limit entries
create or replace function public.cleanup_rate_limits()
returns void as $$
begin
    delete from public.rate_limits
    where window_start < timezone('utc'::text, now()) - interval '1 hour';
end;
$$ language plpgsql;

-- Clean up expired PKCE verifiers (older than 10 minutes)
create or replace function public.cleanup_pkce_verifiers()
returns void as $$
begin
    delete from public.pkce_verifiers
    where created_at < timezone('utc'::text, now()) - interval '10 minutes';
end;
$$ language plpgsql;

-- Atomically retrieve and delete a PKCE verifier (prevents reuse race)
create or replace function public.consume_pkce_verifier(p_code_challenge text)
returns table (code_verifier text) as $$
begin
    delete from public.pkce_verifiers
    where code_challenge = p_code_challenge
    returning code_verifier into code_verifier;
end;
$$ language plpgsql;

-- Atomically retrieve and delete a PKCE verifier by state (prevents reuse race)
create or replace function public.consume_pkce_verifier_by_state(p_state text)
returns table (code_verifier text) as $$
begin
    delete from public.pkce_verifiers
    where state = p_state
    returning code_verifier into code_verifier;
end;
$$ language plpgsql;

-- Clean up old idempotency cache entries (older than 24 hours)
create or replace function public.cleanup_idempotency_cache()
returns void as $$
begin
    delete from public.idempotency_cache
    where created_at < timezone('utc'::text, now()) - interval '24 hours';
end;
$$ language plpgsql;

-- Clean up old webhook delivery logs and their dead-letter rows.
-- Keeps the most recent `p_keep_days` of delivery history to bound storage
-- growth. Safe to run on a schedule (see the /internal/cleanup endpoint or
-- pg_cron). Returns the number of webhook_logs rows removed.
create or replace function public.cleanup_webhook_logs(p_keep_days integer default 30)
returns integer as $$
declare
    v_cutoff timestamp with time zone := timezone('utc'::text, now()) - (p_keep_days || ' days')::interval;
    v_removed integer;
begin
    -- Dead-letter failures reference the original log; prune them first.
    delete from public.webhook_failures
    where created_at < v_cutoff;

    with removed as (
        delete from public.webhook_logs
        where created_at < v_cutoff
        returning 1
    )
    select count(*) into v_removed from removed;

    return v_removed;
end;
$$ language plpgsql;

-- ========================================
-- Route stats aggregation function
-- ========================================
create or replace function public.get_route_stats(p_route_id uuid)
returns table (
    total_deliveries bigint,
    successful_deliveries bigint,
    failed_deliveries bigint,
    timeout_count bigint,
    avg_latency_ms double precision,
    deliveries_24h bigint,
    deliveries_7d bigint,
    deliveries_30d bigint
) as $$
begin
    return query
    select
        count(*)::bigint,
        count(*) filter (where status_code between 200 and 299)::bigint,
        count(*) filter (where status_code is not null and status_code not between 200 and 299)::bigint,
        count(*) filter (where status_code = 504)::bigint,
        avg(duration_ms),
        count(*) filter (where created_at >= timezone('utc'::text, now()) - interval '24 hours')::bigint,
        count(*) filter (where created_at >= timezone('utc'::text, now()) - interval '7 days')::bigint,
        count(*) filter (where created_at >= timezone('utc'::text, now()) - interval '30 days')::bigint
    from public.webhook_logs
    where route_id = p_route_id;
end;
$$ language plpgsql stable;

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

-- ========================================
-- User Profiles Table
-- ========================================
create table public.user_profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    credits integer not null default 100,
    tier text not null default 'free',
    max_concurrent_requests integer default 50,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    updated_at timestamp with time zone default timezone('utc'::text, now()) not null
);

create index idx_user_profiles_id on public.user_profiles(id);

alter table public.user_profiles enable row level security;

create policy "Users can view own profile"
    on public.user_profiles for select
    to authenticated
    using (auth.uid() = id);

create policy "Users can update own profile"
    on public.user_profiles for update
    to authenticated
    using (auth.uid() = id)
    with check (auth.uid() = id);

create policy "Service role full access user_profiles"
    on public.user_profiles for all
    to service_role
    using (true);

create trigger update_user_profiles_updated_at
    before update on public.user_profiles
    for each row
    execute function public.update_updated_at();

-- ========================================
-- Credit Helper Functions
-- ========================================
-- Atomically deduct credits from a user's profile.
create or replace function public.deduct_user_credits(
    p_user_id uuid,
    p_amount integer default 1
)
returns boolean as $$
declare
    v_current_credits integer;
begin
    select credits into v_current_credits
    from public.user_profiles
    where id = p_user_id
    for update;

    if v_current_credits is null then
        insert into public.user_profiles (id, credits, tier)
        values (p_user_id, 100, 'free')
        on conflict (id) do nothing;
        v_current_credits := 100;
    end if;

    if v_current_credits >= p_amount then
        update public.user_profiles
        set credits = credits - p_amount
        where id = p_user_id;
        return true;
    else
        return false;
    end if;
end;
$$ language plpgsql;

-- Atomically add credits to a user's profile.
create or replace function public.add_user_credits(
    p_user_id uuid,
    p_amount integer
)
returns void as $$
begin
    insert into public.user_profiles (id, credits, tier)
    values (p_user_id, p_amount, 'free')
    on conflict (id) do update
    set credits = public.user_profiles.credits + p_amount;
end;
$$ language plpgsql;

-- Atomically grant credits for a payment exactly once.
--
-- Both the Paystack webhook path and the return-URL verify path may attempt to
-- credit the same transaction. This function flips ``credits_granted`` from
-- false -> true in a single UPDATE and only adds credits when that flip
-- succeeds, so concurrent or duplicate calls cannot double-credit the user.
-- Returns the number of credit-granting rows affected (0 or 1).
create or replace function public.grant_credits_once(
    p_reference text,
    p_user_id uuid,
    p_amount integer
)
returns integer as $$
declare
    v_affected integer := 0;
begin
    update public.payment_transactions
    set credits_granted = true
    where reference = p_reference
      and credits_granted = false;

    get diagnostics v_affected = row_count;

    if v_affected > 0 then
        perform public.add_user_credits(p_user_id, p_amount);
    end if;

    return v_affected;
end;
$$ language plpgsql;

-- ========================================
-- Payment Transactions Table
-- ========================================
create table public.payment_transactions (
    id uuid default uuid_generate_v4() primary key,
    user_id uuid not null references auth.users(id) on delete cascade,
    reference text not null unique,
    amount integer not null,
    currency text not null default 'NGN',
    tier text not null,
    credits_to_add integer not null,
    -- Guard against double credit grants. Set to true exactly once when
    -- credits are actually added to the user's balance, regardless of whether
    -- the grant came from the webhook path or the return-URL verify path.
    credits_granted boolean not null default false,
    status text not null default 'pending' check (status in ('pending', 'success', 'failed')),
    paystack_response jsonb default '{}'::jsonb,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    updated_at timestamp with time zone default timezone('utc'::text, now()) not null
);

create index idx_payment_transactions_user_id on public.payment_transactions(user_id);
create index idx_payment_transactions_reference on public.payment_transactions(reference);
create index idx_payment_transactions_status on public.payment_transactions(status);

alter table public.payment_transactions enable row level security;

create policy "Users can view own payment transactions"
    on public.payment_transactions for select
    to authenticated
    using (auth.uid() = user_id);

create policy "Service role full access payment_transactions"
    on public.payment_transactions for all
    to service_role
    using (true);

create trigger update_payment_transactions_updated_at
    before update on public.payment_transactions
    for each row
    execute function public.update_updated_at();

-- ========================================
-- Cleanup jobs (optional, run via pg_cron)
-- ========================================
-- select cron.schedule('cleanup-old-logs', '0 0 * * *', $$
--     delete from public.webhook_logs
--     where created_at < timezone('utc'::text, now()) - interval '30 days';
-- $$);

-- select cron.schedule('cleanup-rate-limits', '*/15 * * * *', $$
--     select public.cleanup_rate_limits();
-- $$);

-- select cron.schedule('cleanup-pkce-verifiers', '*/5 * * * *', $$
--     select public.cleanup_pkce_verifiers();
-- $$);

-- select cron.schedule('cleanup-idempotency-cache', '0 * * * *', $$
--     select public.cleanup_idempotency_cache();
-- $$);

-- ========================================
-- Audit Logs Table
-- ========================================
create table public.audit_logs (
    id bigint generated always as identity primary key,
    user_id uuid references auth.users(id) on delete set null,
    action text not null,
    resource_type text not null,
    resource_id text,
    ip_address inet,
    user_agent text,
    metadata jsonb default '{}'::jsonb,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

create index idx_audit_logs_user_id on public.audit_logs(user_id);
create index idx_audit_logs_action on public.audit_logs(action);
create index idx_audit_logs_created_at on public.audit_logs(created_at);

alter table public.audit_logs enable row level security;

create policy "Service role full access audit_logs"
    on public.audit_logs for all
    to service_role
    using (true);

create policy "Users can view own audit logs"
    on public.audit_logs for select
    to authenticated
    using (auth.uid() = user_id);

-- ========================================
-- Secret Rotation Checks Table
-- ========================================
create table public.secret_rotation_checks (
    id bigint generated always as identity primary key,
    secret_name text not null unique,
    last_rotated_at timestamp with time zone default timezone('utc'::text, now()) not null,
    owner text,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

create index idx_secret_rotation_checks_name on public.secret_rotation_checks(secret_name);

alter table public.secret_rotation_checks enable row level security;

create policy "Service role full access secret_rotation_checks"
    on public.secret_rotation_checks for all
    to service_role
    using (true);

-- ========================================
-- Circuit Breaker State Table
-- ========================================
create table public.circuit_breaker_state (
    destination_url text primary key,
    state text not null default 'closed',
    opened_at timestamp with time zone,
    failure_count integer not null default 0,
    updated_at timestamp with time zone default timezone('utc'::text, now()) not null
);

create index idx_circuit_breaker_state_updated_at on public.circuit_breaker_state(updated_at);

alter table public.circuit_breaker_state enable row level security;

create policy "Service role full access circuit_breaker_state"
    on public.circuit_breaker_state for all
    to service_role
    using (true);

-- ========================================
-- App Settings Table
-- ========================================
create table public.app_settings (
    key text primary key,
    value jsonb not null default '{}'::jsonb,
    updated_at timestamp with time zone default timezone('utc'::text, now()) not null
);

alter table public.app_settings enable row level security;

create policy "Service role full access app_settings"
    on public.app_settings for all
    to service_role
    using (true);
