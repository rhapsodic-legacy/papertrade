# Consensus Quality Engine — Generalization Plan

## What To Do Right Now

**DO NOT start Phase 2 generalization work.** Phase 1 validation needs ~3 more weeks of trading data (started April 4, 2026). The immediate work is fixing the open issues below that affect the quality of the data being collected during Phase 1.

### Immediate Priority: Fix Open Issues

These are ordered by impact on Phase 1 data quality:

#### 1. FRED 10Y/30Y Yield Data Missing (HIGH)
- **Problem:** `_fetch_yield_curve()` in `backend/app/services/market_brief.py` fetches DGS2, DGS10, DGS30, DFF from FRED API. DGS2 and DFF return data, but DGS10 and DGS30 return empty. Without 10Y data, the 10Y-2Y spread (key recession indicator) can't be computed.
- **What was tried:** Increased lookback from 5 to 15 to 30 observations. Switched from sequential to parallel fetch with asyncio.gather. Added print logging to diagnose on next pipeline run.
- **Next step:** Check Railway logs after the next 5PM pipeline run (`POST /api/ai/pipeline/trigger?session=close`). Search logs for "FRED" to see what the API actually returns. If still empty, try different FRED series IDs or add a Yahoo Finance fallback for Treasury rates.
- **Where:** `backend/app/services/market_brief.py`, function `_fetch_yield_curve()`

#### 2. Options Flow Zero Adoption (HIGH)
- **Problem:** 0/12 expected traders cited options flow in trade reasoning on Day 8, despite the module being assigned to Vanilla, Steady Eddie, and Contrarian Carl.
- **Possible causes:** (a) VIX data from Yahoo Finance isn't populating in the brief, (b) the `_format_options_flow()` formatter in `rag_toolkit.py` returns None/empty when data is missing, (c) prompt isn't directive enough for models to cite it.
- **Next step:** Check the market brief for today: `curl -s http://localhost:8001/api/market/brief | python3 -m json.tool | grep -A20 options_flow`. If data exists in the brief, check `_format_options_flow()` output. If the formatter produces text, the models are ignoring it — make the prompt more directive.
- **Where:** `backend/app/services/market_brief.py` (`_fetch_options_flow()`), `backend/app/services/rag_toolkit.py` (`_format_options_flow()`)

#### 3. Signal Ranker 7.7% Win Rate (MEDIUM)
- **Problem:** Signal Ranker is the most-adopted Wave 2 module (8/20 traders citing it) but has the worst win rate at 7.7% across 13 trades. If the composite scoring is miscalibrated, it's actively hurting performance.
- **Next step:** Pull Signal Ranker trades: `curl -s 'http://localhost:8001/api/analytics/reasoning?days=7'` and filter for trades citing "composite" or "signal score". Look at what composite scores led to buys — are high composite scores actually correlating with losing trades? Compare against the scoring formula in `rag_toolkit.py` (`_format_signal_ranker()`).
- **Possible fix:** The composite score may be weighting one factor too heavily, or the anti-convergence framing may be backfiring. Wait for more data (13 trades is thin) before changing the formula.
- **Where:** `backend/app/services/rag_toolkit.py` (`_format_signal_ranker()`)

#### 4. Mistral Small Wave 2 Compliance (LOW)
- **Problem:** 0/5 Mistral Small traders adopted Signal Ranker. All other models show some adoption. Mistral Small may not have enough context window or instruction-following capability to absorb Wave 2 modules on top of existing prompts.
- **Next step:** Compare prompt length for Mistral Small vs Mistral Medium traders. If the full toolkit prompt exceeds Mistral Small's effective context, consider trimming lower-weight modules for Small or shortening the Wave 2 module text.
- **Where:** `backend/app/services/rag_toolkit.py` (`assemble_toolkit_prompt()`), `backend/app/services/ai_trader.py` (personality toolkit assignments)

---

## Day 8 Impact Check Baseline (April 4, 2026)

Use these numbers to compare trends in future impact checks.

### Wave 1 Feature Adoption (deployed ~March 27)
| Feature | Adoption | Notes |
|---------|----------|-------|
| ATR Stops | 3/20 (15%) | Only Vanilla and Steady Eddie citing it |
| Earnings | 0/20 (0%) | 12/20 discuss in commentary but 0 cite in trade reasoning |
| Aging | 14/20 (70%) | Strongest feature — driving 54% of all sells |

### Wave 2 Feature Adoption (deployed April 1)
| Feature | Adoption | Expected | Notes |
|---------|----------|----------|-------|
| Signal Ranker | 8/20 (40%) | 20 | Mistral Medium: 5/5, Large: 2/4, Large 2: 1/5, Small: 0/5 |
| Trade Context | 1/20 (5%) | 20 | Only Contrarian Carl (Mistral Small) |
| Dynamic Risk | 4/12 (33%) | 12 | Mostly generic "defensive" usage |
| Options Flow | 0/12 (0%) | 12 | Likely data issue — see Open Issue #2 |
| Yield Curve | 1/16 (6%) | 16 | Only Steady Eddie (Mistral Medium) |

### Module Attribution (all-time)
| Module | Trades | Win Rate | Total P&L |
|--------|--------|----------|-----------|
| Trade Context | 7 | 71.4% | +$78 |
| Yield Curve | 1 | 100.0% | +$18 |
| Dynamic Risk | 1 | 0.0% | -$29 |
| Signal Ranker | 13 | 7.7% | -$737 |

### Convergence Quality
| Metric | Convergence | Independent |
|--------|------------|-------------|
| Total trades | 289 | 360 |
| Win rate | 48.1% | 44.7% |
| Avg return | -0.33% | -1.06% |
| Buy win rate | 62.4% | 49.7% |
| Sell win rate | 24.1% | 40.0% |
| Edge verdict | `convergence_outperforms` | — |

### Weekly Convergence Trend
| Week | Conv Win Rate | Indep Win Rate | Conv Count | Indep Count |
|------|--------------|----------------|------------|-------------|
| W10 (Mar 9) | 58.3% | 16.7% | 36 | 12 |
| W11 (Mar 16) | 47.0% | 53.0% | 66 | 149 |
| W12 (Mar 23) | 49.6% | 39.3% | 141 | 168 |
| W13 (Mar 30) | 37.0% | 45.2% | 46 | 31 |

**W13 is the concern** — first week convergence underperformed. Monitor whether this reverses or becomes a trend.

### Model Performance
| Model | Win Rate | Avg Return | Signal Ranker Adoption |
|-------|----------|------------|----------------------|
| Mistral Medium | 45.6% | +0.27% | 5/5 (100%) |
| Mistral Small | 36.7% | -3.61% | 0/5 (0%) |
| Mistral Large 2 | 25.9% | -4.89% | 1/5 (20%) |
| Mistral Large | 22.8% | -5.23% | 2/4 (50%) |

### Personality Performance
| Personality | Win Rate | Avg Return |
|------------|----------|------------|
| Steady Eddie | 43.2% | -1.49% |
| Contrarian Carl | 40.0% | -3.91% |
| Vanilla | 38.1% | -2.12% |
| YOLO Bot | 25.8% | -5.48% |
| Crypto Chad | 16.6% | -3.82% |

### Other Metrics
- **Sell rate:** 35 sells / 35 buys (50/50)
- **Aging-driven sells:** 19/35 (54%)
- **Benchmark:** 18/20 traders beating SPY (SPY: -0.15%, avg alpha: +0.70%)
- **Reflections:** avg outcome score trending up (W13: 0.006 → W14: 0.126), 10/19 improving
- **Regime dashboard:** working (200)
- **Watchlist signals:** working (401 without auth, expected)

---

## What Exists Today

A convergence quality analysis system built into PaperTrade's analytics service. It answers: **"When multiple AI traders agree on a trade, is that smart consensus or herding?"**

### Current Implementation (all complete and deployed)

**Files:**
- `backend/app/services/analytics.py` — Core logic:
  - `get_convergence_quality(days, outcome_horizon, convergence_threshold)` — main pipeline
  - `_compute_module_diversity(module_lists)` — Jaccard distance between module sets across trades in a cluster (0.0 = identical inputs, 1.0 = completely different inputs)
  - `_compute_reasoning_overlap(reasoning_texts)` — token-level overlap between reasoning texts
  - `_get_outcome_price(symbol, asset_type, trade_date, horizon_days)` — looks up price N days after trade to determine if the decision was correct
- `backend/app/routers/analytics.py` — API endpoint: `GET /api/analytics/convergence-quality?days=30&outcome_horizon=5&threshold=3`

**What it produces:**
- Convergence vs independent trade win rates and returns (with buy/sell breakdown)
- Convergence edge verdict: `convergence_outperforms`, `convergence_underperforms`, or `insufficient_data`
- Diversity analysis per cluster: classified as `diverse`, `signal_ranker_driven`, `homogeneous`, `no_modules`, or `single_trade`
- Top convergence cluster details (symbol, traders involved, outcome, diversity class, shared modules)
- Weekly trend time series

---

## Why This Generalizes

The core pattern is domain-agnostic: **multiple AI agents make parallel decisions from overlapping-but-not-identical inputs, and you want to know if agreement predicts better outcomes.**

The three reusable components:
1. **Clustering** — group decisions by (subject, action, time window) to find agreement
2. **Outcome resolution** — domain-specific "was this decision correct?" check
3. **Diversity scoring** — Jaccard distance on input modules + token overlap on reasoning to distinguish "same conclusion from different evidence" vs "same conclusion from same narrow input"

### Applicable Domains
- Content moderation (does multi-model consensus reduce false positives?)
- Medical triage (does model agreement improve diagnostic accuracy?)
- Hiring/resume screening (do models agreeing on candidates predict better hires?)
- Fraud detection (does convergent flagging reduce false positive rate?)
- Legal document review (does consensus on risky clauses correlate with actual legal risk?)

---

## Execution Phases

### Phase 1 — Validate on PaperTrade (started April 4, 2026 → target April 25)

**Goal:** Confirm the +3.4% convergence edge holds over 30+ trading days, not just the first 8.

**What to watch:**
- Does the weekly trend stabilize or does the W13 dip (convergence underperformed 37.0% vs 45.2%) recur?
- Does diverse-input consensus outperform homogeneous consensus? (Current data: 40 diverse clusters exist but not enough to compare statistically)
- Does the edge hold across market regimes (bull, bear, sideways)?

**Success criteria:**
- Convergence edge remains positive over 30+ days
- At least 500+ settled convergence trades for statistical significance
- Diverse-input consensus shows higher win rate than homogeneous consensus

**Action items:**
- [ ] Fix open issues #1-4 above (these affect data quality during validation)
- [ ] Run `/impact-check` daily to monitor convergence quality trends
- [ ] After 3 weeks (~April 25), pull the full 30-day convergence quality report and document findings
- [ ] If W13-style dips recur, investigate whether they correlate with specific market conditions

### Phase 2 — Second Domain Pilot

**Goal:** Test whether the "consensus = better outcomes" finding replicates in a non-trading domain.

**DO NOT START running evaluations until Phase 1 success criteria are met.**

**Domain chosen: Multi-model Factual QA (TriviaQA)**

Why this domain:
- 3 Mistral models × 4 prompting strategies = 12 agents per question
- Clear binary outcome: correct or incorrect vs known ground truth
- Prompting strategies serve as "input modules" (bare, chain-of-thought, few-shot, RAG)
- Reuses existing Mistral API keys and FastAPI stack — zero new vendors
- Genuinely different from finance — validates generalization, not domain specifics

**Schema mapping:**
| PaperTrade | QA Domain |
|---|---|
| `(date, symbol, side)` cluster key | `(round_id, question_id)` cluster key |
| AI trader (personality + model) | Agent (model + prompting strategy) |
| Buy/sell decision | Answer text (normalized) |
| RAG toolkit modules | Prompting strategies: `bare`, `cot`, `few_shot`, `rag` |
| Price moved favorably after N days | Answer matches ground truth |
| Convergence threshold: 3 | Consensus threshold: 2 (fewer agents) |

**Implementation (scaffolded April 4, 2026 — ready to run):**
| File | Role |
|---|---|
| `backend/app/services/consensus_qa.py` | Core: load questions, run agents, score, compute consensus quality |
| `backend/app/routers/consensus_qa.py` | API: `/api/consensus-qa/evaluate`, `/rounds`, `/consensus-quality`, `/config`, `/setup` |
| `backend/app/main.py` | Router registered |

**To run when Phase 1 completes:**
1. `POST /api/consensus-qa/setup` — create `qa_rounds` and `qa_answers` tables
2. `POST /api/consensus-qa/evaluate?count=50` — triggers background evaluation (~600 API calls, ~10 min)
3. `GET /api/consensus-qa/consensus-quality` — view results

**What's reused from PaperTrade:**
- `_compute_module_diversity()` from `analytics.py` — Jaccard distance on `[model_id, strategy]` pairs
- `_compute_reasoning_overlap()` from `analytics.py` — token overlap on raw model answers
- Mistral HTTP API call pattern (standalone copy to avoid coupling)
- Supabase client, config, settings

**What's new:**
- TriviaQA loading via HuggingFace datasets HTTP API (no pip install)
- Wikipedia context fetcher for RAG strategy
- Answer extraction (CoT `ANSWER:` parsing) and normalization
- Ground truth matching with alias support
- Consensus grouping (simpler: no time windows, just group by question_id)

**Success criteria:**
- Consensus edge is measurable (positive or negative — either is informative)
- Module diversity scoring produces meaningful cluster classifications
- Results are interpretable without domain expertise

### Phase 3 — Cross-Domain Validation

**Goal:** Confirm generalizability with a third domain.

**Key questions to answer:**
- Is "consensus outperforms" universal, or domain-dependent?
- Does the magnitude of the consensus edge correlate with input diversity? (Hypothesis: diverse-input consensus should be more reliable than homogeneous consensus across all domains)
- Are there domains where consensus is a *negative* signal (groupthink)?

**Success criteria:**
- Pattern holds in 2+ of 3 domains → proceed to Phase 4
- Pattern holds in only 1 → the engine is domain-specific, not generalizable; stop here

### Phase 4 — Productize

**Only proceed if Phase 3 confirms generalization.**

**Technical work:**
- Extract consensus engine into standalone module/package
- Domain config via YAML:
  ```yaml
  domain: papertrade
  decision_schema:
    subject: symbol
    action: side
    value: price
    agent_id: trader_id
  outcome_resolver: papertrade.get_outcome_price
  modules:
    - technical_analysis
    - fundamentals
    - signal_ranker
    # ...
  convergence_threshold: 3
  outcome_horizon_days: 5
  ```
- Multi-domain API: `GET /api/consensus/{domain}/quality`
- Dashboard comparing consensus accuracy across domains

### Phase 5 — Advanced Analytics (Future)

Ideas to explore once the foundation is proven:

- **Weighted diversity** — some modules matter more than others per domain; weight Jaccard accordingly
- **Confidence calibration** — do agents expressing higher confidence in consensus clusters actually perform better?
- **Minimum viable ensemble** — what's the smallest subset of agents whose agreement matches full-group consensus accuracy? (Cost optimization)
- **Consensus decay** — does the consensus edge degrade over time as agents learn from each other? (Convergence-over-time detection)
- **Adversarial probing** — intentionally give one agent contradictory data to test if the others still converge on the right answer

---

## Architecture Context

Key files and how they connect (read these to understand the system):

| File | Role |
|------|------|
| `backend/app/services/analytics.py` | Convergence quality engine, module attribution, trade reasoning, reflection trends |
| `backend/app/routers/analytics.py` | API endpoints for all analytics including `/convergence-quality` |
| `backend/app/services/rag_toolkit.py` | RAG module system — `RAG_MODULES` dict, `_MODULE_FORMATTERS` dispatch, `assemble_toolkit_prompt()`. Signal Ranker, Trade Context, Dynamic Risk, Options Flow, Yield Curve formatters all here |
| `backend/app/services/market_brief.py` | Data fetching — `_fetch_options_flow()` (Yahoo Finance VIX), `_fetch_yield_curve()` (FRED API), wired into `compile_market_brief()` |
| `backend/app/services/ai_trader.py` | Personality toolkit assignments (which modules each personality gets with what weights) |
| `backend/app/config.py` | `fred_api_key` config |
| `~/.claude/skills/impact-check/SKILL.md` | Impact check skill definition with Wave 1 + Wave 2 keyword groups |

### Module Assignment Map
| Module | Vanilla | Steady Eddie | YOLO Bot | Contrarian Carl | Crypto Chad |
|--------|---------|-------------|----------|----------------|-------------|
| Signal Ranker | weight 3 | weight 3 | weight 3 | weight 3 | weight 3 |
| Trade Context | weight 2 | weight 2 | weight 2 | weight 2 | weight 2 |
| Dynamic Risk | weight 1 | weight 1 | — | weight 1 | — |
| Options Flow | weight 2 | weight 4 | — | weight 5 | — |
| Yield Curve | weight 2 | weight 5 | — | weight 2 | weight 4 |

Each personality runs on 4 Mistral models (Small, Medium, Large, Large 2) = 20 AI traders total.

### Daily Pipeline
Runs at 5:00 PM via cron-job.org → `POST /api/ai/pipeline/trigger?session=close`
1. Market Brief (fetches all data including VIX and FRED)
2. Reflections (reviews settled trades)
3. Trading (each AI gets personalized RAG prompt, makes decisions)
4. Commentary (each AI writes daily blog post)
5. Snapshots (safety net at 5:30 PM)

---

## Current State Summary

| Item | Status |
|------|--------|
| Core engine (`get_convergence_quality`) | Deployed, live on Railway |
| API endpoint (`/convergence-quality`) | Deployed, tested |
| Diversity scoring (Jaccard) | Deployed |
| Reasoning overlap | Deployed |
| PaperTrade validation (Phase 1) | In progress — Day 8 of ~30 |
| Open Issue #1: FRED data | Logging deployed, awaiting next pipeline run |
| Open Issue #2: Options Flow adoption | Not yet diagnosed |
| Open Issue #3: Signal Ranker win rate | Monitoring, need more data |
| Open Issue #4: Mistral Small compliance | Not yet diagnosed |
| Phase 2 domain selection | Done — Factual QA (TriviaQA) |
| Phase 2 scaffold | Done — `consensus_qa.py` service + router, ready to run |
| Abstraction/refactoring | Deferred — reusing analytics.py helpers directly for now |
