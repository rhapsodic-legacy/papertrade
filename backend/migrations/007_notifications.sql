-- Notifications & Alert Rules tables
-- Run this in Supabase SQL Editor

-- Notifications: stores generated notifications for users
CREATE TABLE IF NOT EXISTS public.notifications (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    type text NOT NULL,          -- 'ai_trade', 'price_alert', 'portfolio'
    title text NOT NULL,
    message text NOT NULL,
    metadata jsonb DEFAULT '{}', -- extra data (symbol, trader_name, etc.)
    read boolean DEFAULT false,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON public.notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON public.notifications(user_id, read);
CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON public.notifications(created_at DESC);

-- Alert Rules: user-configured alert triggers
CREATE TABLE IF NOT EXISTS public.alert_rules (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    type text NOT NULL,          -- 'price_above', 'price_below', 'ai_follow', 'portfolio_pnl'
    config jsonb NOT NULL,       -- type-specific config
    active boolean DEFAULT true,
    triggered_at timestamptz,    -- last time this alert fired
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_alert_rules_user_id ON public.alert_rules(user_id);
CREATE INDEX IF NOT EXISTS idx_alert_rules_active ON public.alert_rules(active) WHERE active = true;

-- Enable RLS
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alert_rules ENABLE ROW LEVEL SECURITY;

-- RLS policies: users can only see their own data
CREATE POLICY "Users can view own notifications"
    ON public.notifications FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can update own notifications"
    ON public.notifications FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can view own alert rules"
    ON public.alert_rules FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own alert rules"
    ON public.alert_rules FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own alert rules"
    ON public.alert_rules FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own alert rules"
    ON public.alert_rules FOR DELETE
    USING (auth.uid() = user_id);

-- Service role bypass (for backend to create notifications)
CREATE POLICY "Service role full access notifications"
    ON public.notifications FOR ALL
    USING (auth.role() = 'service_role');

CREATE POLICY "Service role full access alert_rules"
    ON public.alert_rules FOR ALL
    USING (auth.role() = 'service_role');
