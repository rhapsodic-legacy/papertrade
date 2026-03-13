-- Migration: Add portfolio snapshots table for historical tracking
-- Run this in Supabase SQL Editor

create table public.portfolio_snapshots (
    id uuid default gen_random_uuid() primary key,
    user_id uuid references public.profiles(id) on delete cascade not null,
    total_value numeric(18, 2) not null,
    cash_balance numeric(18, 2) not null,
    invested_value numeric(18, 2) not null,
    snapshot_date date not null default current_date,
    created_at timestamptz not null default now(),
    unique(user_id, snapshot_date)
);

alter table public.portfolio_snapshots enable row level security;

create policy "Users can view their own snapshots"
    on public.portfolio_snapshots for select
    using (auth.uid() = user_id);

-- Index for fast lookups by user and date range
create index idx_snapshots_user_date
    on public.portfolio_snapshots(user_id, snapshot_date desc);

-- Allow the service role to insert snapshots for all users
create policy "Service role can insert snapshots"
    on public.portfolio_snapshots for insert
    with check (true);
