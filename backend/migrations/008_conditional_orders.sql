-- Conditional orders: limit buys, stop losses, take profits, trailing stops
-- Created by AI traders during daily sessions, executed by intraday subagent

CREATE TABLE conditional_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL CHECK (asset_type IN ('stock', 'crypto')),
    order_type TEXT NOT NULL CHECK (order_type IN ('limit_buy', 'stop_loss', 'take_profit', 'trailing_stop')),
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    trigger_price NUMERIC,          -- target price for limit_buy, stop_loss, take_profit
    trail_pct NUMERIC,              -- percentage for trailing_stop (e.g. 8.0 = 8%)
    high_water_mark NUMERIC,        -- tracked high price for trailing_stop
    reasoning TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'triggered', 'executed', 'failed', 'expired', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '5 days'),
    triggered_at TIMESTAMPTZ,
    executed_at TIMESTAMPTZ,
    execution_price NUMERIC,
    CONSTRAINT trigger_or_trail CHECK (
        (order_type IN ('limit_buy', 'stop_loss', 'take_profit') AND trigger_price IS NOT NULL)
        OR (order_type = 'trailing_stop' AND trail_pct IS NOT NULL)
    )
);

-- Index for the subagent's hot path: fetch all pending orders
CREATE INDEX idx_conditional_orders_pending ON conditional_orders (status) WHERE status = 'pending';

-- Index for per-user lookups (API + RAG context)
CREATE INDEX idx_conditional_orders_user ON conditional_orders (user_id, status);

-- Index for sibling cancellation (same user + symbol)
CREATE INDEX idx_conditional_orders_sibling ON conditional_orders (user_id, symbol, status);

-- RLS: AI traders use service role (no RLS needed for backend).
-- If human users get conditional orders later, add RLS policies here.
