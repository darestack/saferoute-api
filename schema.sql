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
    rate_limit integer default 30,
    transform_headers jsonb default '{}'::jsonb,
    transform_body_template text,
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

-- ========================================
-- Rate Limits Table
-- ========================================
create table public.rate_limits (
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
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

create index idx_pkce_verifiers_challenge on public.pkce_verifiers(code_challenge);

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
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
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
-- NOTE: `window_start` is a *stable* bucket boundary (computed inside Postgres
-- via date_bin) rather than a request-relative "now - 60s" value. The previous
-- implementation stored `now - 60s` as the anchor and matched on
-- `window_start >= p_window_start`; because every request passed a drifting
-- cutoff, no stored row ever matched and a brand-new row was inserted on every
-- call, so the counter never accumulated and the limit was never enforced.
-- Keeping `window_start` as a fixed bucket shared by all requests in the same
-- 60s window makes the UPDATE path hit reliably, so counts accumulate and the
-- limit actually triggers. The `unique(route_id, ip_address, window_start)`
-- constraint guarantees at most one row per bucket.
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
    -- Try to increment an existing row for the current 60s bucket.
    update public.rate_limits
    set request_count = request_count + 1
    where route_id = p_route_id
      and ip_address = p_ip
      and window_start = v_bucket
      and request_count < p_max_requests
    returning request_count into new_count;

    if found then
        success := true;
        return next;
        return;
    end if;

    -- A row for this bucket exists but is already at/over the limit.
    perform 1
    from public.rate_limits
    where route_id = p_route_id
      and ip_address = p_ip
      and window_start = v_bucket;

    if found then
        select request_count into new_count
        from public.rate_limits
        where route_id = p_route_id
          and ip_address = p_ip
          and window_start = v_bucket;
        success := false;
        return next;
        return;
    end if;

    -- No row for the current bucket yet: create it. The unique constraint
    -- makes this safe under concurrent inserts (a lost race simply re-reads
    -- the row the winning writer created).
    insert into public.rate_limits (route_id, ip_address, request_count, window_start)
    values (p_route_id, p_ip, 1, v_bucket)
    on conflict (route_id, ip_address, window_start) do nothing;

    select request_count into new_count
    from public.rate_limits
    where route_id = p_route_id
      and ip_address = p_ip
      and window_start = v_bucket;

    success := true;
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
