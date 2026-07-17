-- Add payment transactions table for Paystack integration.
--
-- Stores credit pack purchase transactions and their verification status.

create table public.payment_transactions (
    id uuid default uuid_generate_v4() primary key,
    user_id uuid not null references auth.users(id) on delete cascade,
    reference text not null unique,
    amount integer not null,
    currency text not null default 'NGN',
    tier text not null,
    credits_to_add integer not null,
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
