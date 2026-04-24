-- Analyst blog content: scraped articles from independent financial analysts
-- Summarized by Gemma, injected into AI trader prompts as "Expert Opinion" module

CREATE TABLE analyst_content (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_key TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    published_at TIMESTAMPTZ,
    content_text TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('macro', 'crypto', 'tech_finance')),
    scraped_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Gemma-generated summary fields (NULL until processed)
    summary TEXT,
    tickers TEXT[],
    sentiment NUMERIC,
    analyst_call TEXT,
    confidence NUMERIC,

    -- Pipeline tracking
    used_in_brief_date DATE,
    outcome_score NUMERIC  -- filled by reflections later (Phase 4)
);

-- Index for fetching unsummarized articles
CREATE INDEX idx_analyst_content_unsummarized
    ON analyst_content (published_at DESC)
    WHERE summary IS NULL;

-- Index for fetching recent summarized articles (RAG injection)
CREATE INDEX idx_analyst_content_recent_summarized
    ON analyst_content (published_at DESC)
    WHERE summary IS NOT NULL AND confidence >= 0.3;

-- Index for dedup by URL (covered by UNIQUE constraint, but explicit for clarity)
-- The UNIQUE constraint on url already creates an index, so no extra index needed.

-- Index for source-level quality tracking (Phase 4)
CREATE INDEX idx_analyst_content_source ON analyst_content (source_key, published_at DESC);
