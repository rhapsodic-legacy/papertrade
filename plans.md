# PaperTrade — Future Feature Plans

## 1. Intraday Conditional Order Subagent

### MVP: Code-Only Execution

During the daily 5 PM trading session, each Mistral trader outputs an optional `conditional_orders` array alongside their normal trades. A local Python script (launchd, no Gemma needed) monitors prices and executes when conditions are met.

**Order types:**

| Type | Trigger | Use Case |
|------|---------|----------|
| `limit_buy` | Price drops to or below target | Buy the dip |
| `stop_loss` | Price drops to or below target | Cut losses |
| `take_profit` | Price rises to or above target | Lock gains |
| `trailing_stop` | Price drops trail_pct% from high-water mark | Dynamic stop-loss |

**JSON format change (added to daily trade output):**
```json
{
  "trades": [...],
  "conditional_orders": [
    {"symbol": "AAPL", "asset_type": "stock", "order_type": "stop_loss", "side": "sell", "quantity": 10, "trigger_price": 165.00, "reasoning": "Protect position"},
    {"symbol": "ETH", "asset_type": "crypto", "order_type": "limit_buy", "side": "buy", "quantity": 0.5, "trigger_price": 2800.00, "reasoning": "Buy ETH at support"},
    {"symbol": "NVDA", "asset_type": "stock", "order_type": "trailing_stop", "side": "sell", "quantity": 5, "trail_pct": 8.0, "reasoning": "Ride momentum, 8% trail"}
  ]
}
```

**New DB table: `conditional_orders`**
- id, user_id, symbol, asset_type, order_type, side, quantity
- trigger_price, trail_pct, high_water_mark (for trailing stops)
- reasoning, status (pending/triggered/executed/failed/expired/cancelled)
- created_at, expires_at (default +5 days), triggered_at, executed_at, execution_price

**Subagent execution:**
- Runs via launchd: every 5 min during market hours, every 15 min off-hours (crypto)
- Fetches prices ONLY for symbols with pending orders (~15-20 Finnhub calls/cycle, 6.7% of 60/min budget)
- Pure code logic: `current_price <= trigger_price` → execute. No LLM reasoning needed
- Reuses existing buy/sell DB operations from trading.py
- Safety: double-execution prevention (mark `triggered` before executing), position validation, cash validation, file-based concurrency lock
- Sibling order cancellation: if stop-loss triggers, auto-cancel take-profit on same symbol/user

**Feedback to next daily session:**
- Triggered orders appear in trade history as `[CONDITIONAL STOP_LOSS]` in reasoning
- Pending orders shown in a new "Your Pending Conditional Orders" prompt section
- Expired orders shown so traders learn if their targets were realistic

**Rate limit math:**
- 21 API calls per 5-min cycle × 12 cycles/hour = 252/hour (budget: 3,600/hour). Comfortable.
- Worst case (80 orders, 63 unique stocks): 64 calls/cycle, still fits with batching

**Finnhub caveat:** Free tier quotes are 15-minute delayed. Stop-losses trigger on delayed prices. Acceptable for paper trading.

**Files to create/modify:**
- NEW: `backend/app/services/conditional_orders.py` — core logic (save, check, execute, expire)
- NEW: `backend/scripts/intraday_subagent.py` — standalone launchd runner with file lock
- NEW: `com.papertrade.intraday.plist` — launchd config (5-min interval)
- NEW: `backend/migrations/add_conditional_orders.sql` — Supabase migration
- MODIFY: `ai_trader.py` — add conditional_orders to TRADE_SYSTEM prompt, parse from LLM output, inject pending orders into RAG context
- MODIFY: `trading.py` — extract reusable execute_buy_db/execute_sell_db functions
- MODIFY: `market_data.py` — add get_batch_stock_quotes() helper
- MODIFY: `ai.py` router — GET/DELETE endpoints for conditional orders
- MODIFY: `config.py` — add intraday interval settings

---

### Expansion: Gemma-Powered Intelligent Monitoring

The MVP is pure code execution — "did price cross the trigger?" But Gemma can add intelligence on top by monitoring market conditions and identifying opportunities the static orders miss.

**Cross-asset correlation trades:**
- BTC moves up → ETH follows with a ~15-30 min lag. Gemma monitors BTC price action and pre-emptively buys ETH before the correlation catches up.
- SPY drops sharply → GLD/TLT often rally (flight to safety). Gemma detects the SPY move and triggers defensive buys.
- Tech sector rotation: if NVDA spikes on AI news, Gemma could flag AMD/MSFT as correlated plays before they move.

**Implementation:** A second tier of conditional orders: `smart_trigger` type. Instead of a static price target, these have a natural language condition that Gemma evaluates each cycle:
```json
{
  "order_type": "smart_trigger",
  "condition": "BTC rises >3% in the last 2 hours",
  "action": {"symbol": "ETH", "side": "buy", "quantity": 0.5},
  "reasoning": "ETH lags BTC rallies by ~30 min historically"
}
```

**How Gemma evaluates:**
- Each cycle, collect recent price changes for a watchlist of correlated assets
- Feed the price data + the smart_trigger conditions to Gemma as a batch
- Gemma returns which conditions are met (yes/no + confidence)
- Only execute at confidence > 0.8

**Cost:** ~1 Gemma call per cycle (batch all smart triggers into one prompt). At 20-30s per call, this fits within the 5-min interval. No API costs.

**Correlation patterns to hardcode (v1) or learn (v2):**
- BTC → ETH, SOL, AVAX (crypto beta)
- SPY → QQQ (same direction), GLD/TLT (inverse in stress)
- NVDA → AMD, MSFT (AI/semiconductor sector)
- Oil (XOM, CVX) → energy sector rotation
- VIX spike → broad risk-off (sell equities, buy GLD)

**Build sequence:** MVP (pure code) first. Run it for 2+ weeks to validate the infrastructure. Then layer Gemma intelligence on top as a separate phase.

---

## 2. Analyst Blog Scraping Pipeline

### Sources (All Free, Public RSS)

**Macro:**
| Source | URL | Frequency | Value |
|--------|-----|-----------|-------|
| Wolf Street | wolfstreet.com | Daily | Contrarian macro, CRE, rates |
| Calculated Risk | calculatedriskblog.com | Daily | Leading indicators, housing |
| Pragmatic Capitalism | pragcap.com | 2-3x/week | Asset allocation frameworks |
| Mish Talk | mishtalk.com | Daily | Economic contrarianism |
| Kyla Scanlon | kylascanlon.com | 2-3x/week | Plain-language macro context |
| Noahpinion | noahpinion.substack.com | 2-3x/week | Economic analysis |

**Crypto:**
| Source | URL | Frequency | Value |
|--------|-----|-----------|-------|
| Bankless | bankless.com/blog | Daily | DeFi, L1/L2 thesis |
| Messari Research | messari.io/research | Daily | On-chain metrics, sectors |
| The Block Research | theblock.co/research | Daily | Institutional flows |

**Tech/Finance:**
| Source | URL | Frequency | Value |
|--------|-----|-----------|-------|
| The Diff | thediff.co | Daily | Capital allocation, tech biz models |

### Architecture

**Scraping (runs at brief compilation time, ~2 min):**
- RSS-first via `feedparser`, HTTP+BeautifulSoup fallback for truncated entries
- No headless browsers — all sources have RSS/Atom feeds
- Dedup by URL against `analyst_content` Supabase table
- 2-second delays between requests to same domain, respect robots.txt
- Graceful degradation: if a source 403s, skip it, don't block the pipeline

**Gemma summarization (~4-6 min):**
- Each article → single Gemma call → structured JSON:
  ```json
  {"summary": "...", "tickers": ["BTC", "ETH"], "sentiment": 0.7,
   "analyst_call": "BULLISH ETH post-Dencun", "confidence": 0.8, "category": "crypto"}
  ```
- Then one compression call: all summaries → ~500-word "Expert Opinion Digest"
- Digest groups by theme, flags consensus AND conflicts between analysts
- Articles processed sequentially (single Ollama GPU), not parallel

**New DB table: `analyst_content`**
- source_key, title, url (UNIQUE), published_at, content_text
- summary, tickers[], sentiment, analyst_call, confidence, category
- scraped_at, used_in_brief_date, outcome_score (filled by reflections later)

### RAG Integration

**New module: `expert_opinion`**
```python
"expert_opinion": {
    "label": "Expert Opinion",
    "description": "Daily digest from independent analysts — consensus, conflicts, high-conviction calls",
    "icon": "brain", "color": "rose",
}
```

**Per-personality weighting:**
| Personality | Weight | Notes |
|-------------|--------|-------|
| Contrarian Carl | 7, inverted | Uses analyst consensus as contrarian signal |
| Steady Eddie | 6 | Values fundamental/macro opinions |
| Crypto Chad | 6 | Values crypto analyst opinions |
| Vanilla | 5 | Supplementary signal |
| YOLO Bot | 3 | Momentum > opinions |

**Prompt framing (critical):**
> "These are opinions from external analysts. They may be wrong, biased, or outdated.
> Treat as ONE perspective among many. Cross-reference against your raw data before acting."

### Quality Control

- **Confidence threshold:** Only include calls with Gemma confidence >= 0.3
- **Staleness:** 72-hour cutoff. Articles >72h excluded from digest
- **Outcome tracking (Phase 4):** Reflection system scores analyst calls against trade outcomes. Sources that consistently mislead get downweighted or removed
- **Source scoring table:** `analyst_source_scores` tracks accuracy per source over time

### Implementation Phases

**Phase 1 — Core scraping + storage (2-3 hours):**
- Create `analyst_scraper.py` (RSS parsing, content extraction, Supabase storage)
- Add `feedparser`, `beautifulsoup4` to requirements
- Create `analyst_content` Supabase table

**Phase 2 — Gemma summarization (2-3 hours):**
- Add `summarize_analyst_articles()` and `compress_analyst_digest()` to gemma_preprocess.py
- Wire into `compile_market_brief()` or `run_preprocessing()`

**Phase 3 — RAG integration (1-2 hours):**
- Add `expert_opinion` module to rag_toolkit.py
- Add to each personality's toolkit config in ai_trader.py

**Phase 4 — Quality tracking (2-3 hours, build later):**
- Extend reflection.py to score analyst call outcomes
- Create `analyst_source_scores` table
- Add source weighting to digest compression

### Dependencies
- `feedparser` (~50KB, pure Python, RSS/Atom parsing)
- `beautifulsoup4` (~100KB, HTML content extraction)
- No paid APIs, no premium subscriptions

---

## Priority Notes

The conditional order subagent and analyst scraping are independent features. Either can be built first. The conditional order subagent is more mechanically complex (new DB table, new launchd job, modifications to trade execution) but has clearer ROI — it directly enables more frequent trading. The analyst pipeline is simpler to build but its value depends on the quality of the sources.

**Recommended order:**
1. Conditional order subagent MVP (pure code execution)
2. Analyst scraping pipeline (phases 1-3)
3. Conditional order Gemma expansion (cross-asset intelligence)
4. Analyst quality tracking (phase 4)
