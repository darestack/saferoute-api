-- SafeRoute API Migration 004 — Retention / cleanup
-- Run this against an EXISTING Supabase deployment.
-- For fresh deployments, use schema.sql directly.
--
-- Changes:
--   1. Add public.cleanup_webhook_logs(p_keep_days) to prune old delivery
--      logs and their dead-letter rows, bounding storage growth.
--
-- How to run it:
--   * Fresh deploy  -> schema.sql already contains this function.
--   * Existing deploy -> run this file in the Supabase SQL Editor.
--
-- Scheduling (choose one, all $0):
--   * Call the internal endpoint on a cron (see .github/workflows/cleanup.yml):
--       POST /internal/cleanup   (Authorization: Bearer <RETRY_ENDPOINT_SECRET>)
--   * Or enable pg_cron in Supabase and schedule, e.g.:
--       select cron.schedule(
--         'cleanup-webhook-logs', '0 3 * * *',
--         $$ select public.cleanup_webhook_logs(30); $$
--       );

create or replace function public.cleanup_webhook_logs(p_keep_days integer default 30)
returns integer as $$
declare
    v_cutoff timestamp with time zone := timezone('utc'::text, now()) - (p_keep_days || ' days')::interval;
    v_removed integer;
begin
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
