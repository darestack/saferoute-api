-- SafeRoute API Migration 005 — Fix per-IP rate limiter
-- Run this against an EXISTING Supabase deployment.
-- For fresh deployments, schema.sql already contains the corrected function.
--
-- Background:
--   The previous increment_rate_limit() stored `now - 60s` as the row's
--   window_start and matched on `window_start >= p_window_start`. Because every
--   call passed a *drifting* cutoff, no stored row ever matched, so a new row
--   was inserted on every request. The counter never accumulated and the
--   429 limit was effectively never enforced.
--
--   The fix computes a STABLE 60-second bucket inside Postgres (date_bin) and
--   matches on the exact bucket, so the UPDATE path hits and counts accumulate.
--   No signature/behaviour change to the columns or the unique constraint
--   (unique(route_id, ip_address, window_start) is preserved), so this is safe
--   to apply to a live database.

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
