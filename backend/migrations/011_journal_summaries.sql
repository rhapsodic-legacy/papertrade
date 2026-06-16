-- Weekly/monthly journal summaries.
-- Traders roll up their daily commentary into reflective weekly entries, and
-- their 4 weekly entries into a monthly entry. Reuses the ai_commentary table:
-- a summary is just a commentary row with summary_type != 'daily' and a period
-- window. These are reflective/narrative for humans (and a future learning
-- substrate) — they are NOT injected into the daily trading prompt.

ALTER TABLE ai_commentary
    ADD COLUMN IF NOT EXISTS summary_type TEXT NOT NULL DEFAULT 'daily'
        CHECK (summary_type IN ('daily', 'weekly', 'monthly'));

-- Period window. For daily rows these stay NULL (commentary_date is the day).
-- For weekly/monthly, period_start..period_end is the window summarized, and
-- commentary_date is the period end (publication date) so existing
-- date-ordered queries keep working.
ALTER TABLE ai_commentary
    ADD COLUMN IF NOT EXISTS period_start DATE;
ALTER TABLE ai_commentary
    ADD COLUMN IF NOT EXISTS period_end DATE;

-- The old UNIQUE(user_id, commentary_date) would now collide a weekly and a
-- daily published on the same date. Fold summary_type into the constraint.
ALTER TABLE ai_commentary
    DROP CONSTRAINT IF EXISTS ai_commentary_user_id_commentary_date_key;
ALTER TABLE ai_commentary
    ADD CONSTRAINT ai_commentary_user_period_key
        UNIQUE (user_id, commentary_date, summary_type);

-- Fetch summaries of a given type, newest first (the /insights toggle).
CREATE INDEX IF NOT EXISTS idx_ai_commentary_type_date
    ON ai_commentary (summary_type, commentary_date DESC);
