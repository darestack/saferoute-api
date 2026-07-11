-- SafeRoute API Migration 006 — webhook_logs.updated_at for the retry reaper
-- Run against an EXISTING Supabase deployment. For fresh deploys, schema.sql
-- already contains the column and trigger.
--
-- Background: process_retries() runs a reaper that resets rows stranded in
-- the 'retrying' state (e.g. a worker that died mid-retry) back to 'pending'
-- so they are retried instead of lost. The reaper filters on
-- webhook_logs.updated_at, but that column did not exist on webhook_logs, so
-- the reaper silently errored and stuck rows were never reaped -> permanent
-- delivery loss. This adds the column and a before-update trigger that keeps
-- it current, so the reaper can tell how long a row has been 'retrying'.

alter table public.webhook_logs
    add column if not exists updated_at
    timestamp with time zone default timezone('utc'::text, now()) not null;

drop trigger if exists update_webhook_logs_updated_at on public.webhook_logs;
create trigger update_webhook_logs_updated_at
    before update on public.webhook_logs
    for each row
    execute function public.update_updated_at();
