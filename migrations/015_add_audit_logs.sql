-- Add audit_logs table for security event tracking
-- Applied to existing databases after schema.sql is deployed

create table if not exists public.audit_logs (
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

create index if not exists idx_audit_logs_user_id on public.audit_logs(user_id);
create index if not exists idx_audit_logs_action on public.audit_logs(action);
create index if not exists idx_audit_logs_created_at on public.audit_logs(created_at);

alter table public.audit_logs enable row level security;

drop policy if exists "Service role full access audit_logs" on public.audit_logs;
create policy "Service role full access audit_logs"
    on public.audit_logs for all
    to service_role
    using (true);

drop policy if exists "Users can view own audit logs" on public.audit_logs;
create policy "Users can view own audit logs"
    on public.audit_logs for select
    to authenticated
    using (auth.uid() = user_id);
