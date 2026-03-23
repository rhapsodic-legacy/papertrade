-- Create headline_sentiments table for persistent sentiment scoring
CREATE TABLE headline_sentiments (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    scored_date DATE NOT NULL,
    symbol TEXT,
    headline TEXT NOT NULL,
    summary TEXT,
    source TEXT,
    sentiment_score REAL NOT NULL,
    confidence REAL NOT NULL,
    categories TEXT[],
    news_type TEXT NOT NULL DEFAULT 'general',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_hs_symbol_date ON headline_sentiments (symbol, scored_date DESC);
CREATE INDEX idx_hs_date ON headline_sentiments (scored_date DESC);
