-- Add circuit_breaker_state table for shared circuit breaker across workers
-- Applied to existing databases after schema.sql is deployed

create table if not exists public.circuit_breaker_state (
    destination_url text primary key,
    state text not null default 'closed',
    opened_at timestamp with time zone,
    failure_count integer not null default 0,
    updated_at timestamp with time zone default timezone('utc'::text, now()) not null
);

create index if not exists idx_circuit_breaker_state_updated_at on public.circuit_breaker_state(updated_at);

alter table public.circuit_breaker_state enable row level security;

drop policy if exists "Service role full access circuit_breaker_state" on public.circuit_breaker_state;
create policy "Service role full access circuit_breaker_state"
    on public.circuit_breaker_state for all
    to service_role
    using (true);
