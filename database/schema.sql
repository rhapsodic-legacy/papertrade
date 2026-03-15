-- PaperTrade Database Schema
-- Run this in Supabase SQL Editor

-- Profiles table (extends Supabase auth.users)
create table public.profiles (
    id uuid references auth.users on delete cascade primary key,
    display_name text not null,
    cash_balance numeric(15, 2) not null default 100000.00,
    is_ai boolean not null default false,
    ai_model text default null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Enable RLS
alter table public.profiles enable row level security;

create policy "Users can view their own profile"
    on public.profiles for select
    using (auth.uid() = id);

create policy "Users can update their own profile"
    on public.profiles for update
    using (auth.uid() = id);

-- Positions table (current holdings)
create table public.positions (
    id uuid default gen_random_uuid() primary key,
    user_id uuid references public.profiles(id) on delete cascade not null,
    symbol text not null,
    asset_type text not null check (asset_type in ('stock', 'crypto')),
    quantity numeric(18, 8) not null default 0,
    avg_cost_basis numeric(18, 8) not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(user_id, symbol)
);

alter table public.positions enable row level security;

create policy "Users can view their own positions"
    on public.positions for select
    using (auth.uid() = user_id);

create policy "Users can manage their own positions"
    on public.positions for all
    using (auth.uid() = user_id);

-- Transactions table (trade history)
create table public.transactions (
    id uuid default gen_random_uuid() primary key,
    user_id uuid references public.profiles(id) on delete cascade not null,
    symbol text not null,
    asset_type text not null check (asset_type in ('stock', 'crypto')),
    side text not null check (side in ('buy', 'sell')),
    quantity numeric(18, 8) not null,
    price numeric(18, 8) not null,
    total numeric(18, 8) not null,
    created_at timestamptz not null default now()
);

alter table public.transactions enable row level security;

create policy "Users can view their own transactions"
    on public.transactions for select
    using (auth.uid() = user_id);

create policy "Users can insert their own transactions"
    on public.transactions for insert
    with check (auth.uid() = user_id);

-- Watchlist table
create table public.watchlist (
    id uuid default gen_random_uuid() primary key,
    user_id uuid references public.profiles(id) on delete cascade not null,
    symbol text not null,
    asset_type text not null check (asset_type in ('stock', 'crypto')),
    created_at timestamptz not null default now(),
    unique(user_id, symbol)
);

alter table public.watchlist enable row level security;

create policy "Users can manage their own watchlist"
    on public.watchlist for all
    using (auth.uid() = user_id);

-- Portfolio snapshots table (daily value tracking)
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

create policy "Service role can insert snapshots"
    on public.portfolio_snapshots for insert
    with check (true);

create index idx_snapshots_user_date
    on public.portfolio_snapshots(user_id, snapshot_date desc);

-- Function to auto-create profile on signup
create or replace function public.handle_new_user()
returns trigger as $$
begin
    insert into public.profiles (id, display_name, cash_balance)
    values (
        new.id,
        coalesce(new.raw_user_meta_data->>'display_name', split_part(new.email, '@', 1)),
        100000.00
    );
    return new;
end;
$$ language plpgsql security definer;

create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

-- Index for filtering AI vs human profiles
create index idx_profiles_is_ai on public.profiles(is_ai);

-- Market briefs table for AI trader daily data
create table public.market_briefs (
    id uuid default gen_random_uuid() primary key,
    brief_date date not null unique,
    brief_data jsonb not null,
    created_at timestamptz not null default now()
);

alter table public.market_briefs enable row level security;

create policy "Service role full access on market_briefs"
    on public.market_briefs for all
    with check (true);
