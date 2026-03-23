-- Create trade_reflections table for post-trade learning loop
CREATE TABLE trade_reflections (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    trade_id UUID NOT NULL,
    user_id UUID NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    trade_price NUMERIC(18, 8) NOT NULL,
    outcome_price NUMERIC(18, 8) NOT NULL,
    price_change_pct REAL NOT NULL,
    outcome_score REAL NOT NULL,
    reflection_text TEXT NOT NULL,
    lessons TEXT,
    reflected_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_reflections_user ON trade_reflections (user_id, reflected_at DESC);
CREATE INDEX idx_reflections_trade ON trade_reflections (trade_id);
