-- Add app_settings table for runtime configuration
-- Applied to existing databases after schema.sql is deployed

create table if not exists public.app_settings (
    key text primary key,
    value jsonb not null default '{}'::jsonb,
    updated_at timestamp with time zone default timezone('utc'::text, now()) not null
);

alter table public.app_settings enable row level security;

drop policy if exists "Service role full access app_settings" on public.app_settings;
create policy "Service role full access app_settings"
    on public.app_settings for all
    to service_role
    using (true);
