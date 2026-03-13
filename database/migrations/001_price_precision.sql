-- Migration: Increase price precision from 2 to 8 decimal places
-- Run this in Supabase SQL Editor

-- Must drop leaderboard view first since it depends on avg_cost_basis
drop view if exists public.leaderboard;

alter table public.transactions
    alter column price type numeric(18, 8),
    alter column total type numeric(18, 8);

alter table public.positions
    alter column avg_cost_basis type numeric(18, 8);

-- Recreate leaderboard view to use updated column types
create or replace view public.leaderboard as
select
    p.id,
    p.display_name,
    p.cash_balance,
    p.created_at,
    coalesce(sum(pos.quantity * pos.avg_cost_basis), 0) as invested_value,
    p.cash_balance + coalesce(sum(pos.quantity * pos.avg_cost_basis), 0) as total_portfolio_value
from public.profiles p
left join public.positions pos on p.id = pos.user_id and pos.quantity > 0
group by p.id, p.display_name, p.cash_balance, p.created_at
order by total_portfolio_value desc;
