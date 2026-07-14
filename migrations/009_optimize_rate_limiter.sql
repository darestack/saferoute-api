-- Optimize rate limiter for burst traffic at $0 cost.
--
-- 1. Convert rate_limits to UNLOGGED for faster writes (no WAL).
--    Rate limit buckets are ephemeral (60s windows, cleaned hourly), so
--    crash recovery is acceptable.
--
-- 2. Replace increment_rate_limit with a single INSERT ... ON CONFLICT
--    DO UPDATE to reduce lock contention under concurrent bursts.

BEGIN;

-- Convert to UNLOGGED (requires rewriting the table).
alter table public.rate_limits set unlogged;

-- Replace the rate-limit function with the single-statement version.
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

    -- Row exists but is already at/over the limit.
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

COMMIT;
