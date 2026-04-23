-- Pipeline timings: per-trader, per-phase duration tracking.
-- Used to watch for Cloud Run timeout risk as the fleet grows and to
-- attribute slow runs to specific models/providers.

CREATE TABLE pipeline_timings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_date DATE NOT NULL,
    phase TEXT NOT NULL,              -- 'trading' | 'commentary' | 'brief' | 'reflections'
    trader_id UUID,                   -- NULL for phase-level aggregates
    trader_name TEXT,
    model_key TEXT,
    personality_key TEXT,
    duration_seconds NUMERIC NOT NULL,
    trades_executed INTEGER,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    status TEXT DEFAULT 'ok',         -- 'ok' | 'error' | 'skipped'
    error_message TEXT
);

CREATE INDEX idx_pipeline_timings_run_date ON pipeline_timings (run_date DESC);
CREATE INDEX idx_pipeline_timings_trader ON pipeline_timings (trader_id, run_date DESC);
CREATE INDEX idx_pipeline_timings_phase ON pipeline_timings (phase, run_date DESC);
CREATE INDEX idx_pipeline_timings_model ON pipeline_timings (model_key, run_date DESC);
