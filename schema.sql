-- SafeRoute API Database Schema
-- Run this in your Supabase SQL Editor

-- Enable UUID generation
create extension if not exists "uuid-ossp";

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
    rate_limit_per_minute integer default 30,
    transform_rules jsonb default '{}'::jsonb,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    updated_at timestamp with time zone default timezone('utc'::text, now()) not null
);

-- Index for fast lookups by slug (used in proxy path)
create index idx_routes_slug on public.routes(slug);

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
    retry_count integer default 0,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

-- Index for route logs lookup
create index idx_webhook_logs_route_id on public.webhook_logs(route_id);

-- Index for time-based queries
create index idx_webhook_logs_created_at on public.webhook_logs(created_at desc);

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
-- Stores PKCE code_verifier values keyed by code_challenge so that the
-- OAuth callback (which may hit a different serverless worker) can
-- retrieve the verifier. Entries should be short-lived (< 10 minutes).
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

-- Service role can insert logs (for proxy backend)
create policy "Service role insert logs"
    on public.webhook_logs for insert
    to service_role
    with check (true);

-- Service role full access to webhook_logs (for reading in API)
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

-- ========================================
-- Triggers
-- ========================================
-- Update updated_at timestamp
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

-- ========================================
-- Cleanup job (optional, run via cron)
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

-- ========================================
-- Idempotency Keys Table
-- ========================================
create table public.idempotency_keys (
    id uuid default uuid_generate_v4() primary key,
    route_id uuid not null references public.routes(id) on delete cascade,
    idempotency_key text not null,
    response_status integer not null,
    response_body text,
    response_headers jsonb,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    expires_at timestamp with time zone default timezone('utc'::text, now()) + interval '24 hours' not null,
    unique(route_id, idempotency_key)
);

create index idx_idempotency_keys_route_key on public.idempotency_keys(route_id, idempotency_key);
create index idx_idempotency_keys_expires_at on public.idempotency_keys(expires_at);

alter table public.idempotency_keys enable row level security;

create policy "Service role full access idempotency_keys"
    on public.idempotency_keys for all
    to service_role
    using (true);

-- ========================================
-- Cleanup job for expired idempotency keys
-- ========================================
create or replace function public.cleanup_idempotency_keys()
returns void as $$
begin
    delete from public.idempotency_keys
    where expires_at < timezone('utc'::text, now());
end;
$$ language plpgsql;

-- select cron.schedule('cleanup-idempotency-keys', '*/10 * * * *', $$
--     select public.cleanup_idempotency_keys();
-- $$);
