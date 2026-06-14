# PaperTrade - Claude Code Guide

## ⚠️ HARD CONSTRAINT — LOCAL MACHINE HAS 8GB RAM
The user's local Mac Mini has **8GB RAM**. Gemma 4 e2b alone is ~7GB. Heavy local LLM calls crash the box and force a reboot — this has already happened. Before adding ANY new local LLM call:
- Verify the prompt is short and `max_tokens` is small
- Do NOT run multiple Gemma calls in parallel (`asyncio.gather`) without confirming serial execution
- Prefer Cloud Run + paid API (Mistral) over local Gemma for new LLM work
- When in doubt, ASK the user before running. Do not "smoke test" speculative Gemma additions locally.

## Project Overview
Paper trading platform with $100k virtual portfolios. 25 AI traders (5 personality lines x 5 LLM models) compete alongside human users. FastAPI backend, Next.js frontend, Supabase DB.

## Tech Stack
- **Backend:** FastAPI (Python 3.13) — `backend/`
- **Frontend:** Next.js 16 + TypeScript + Tailwind — `frontend/`
- **Database:** Supabase (Postgres + Auth)
- **Hosting:** GCP Cloud Run (backend), Vercel (frontend)
- **CI/CD:** Cloud Build (backend, manual deploy), Vercel auto-deploy (frontend)
- **Cron:** GCP Cloud Scheduler (2 jobs) + local launchd (Gemma preprocessing)
- **Secrets:** GCP Secret Manager
- **Local AI:** Ollama + Gemma 4 e2b for free preprocessing (headline clustering, analyst consensus, insider flow, movers narrative)
- **LLMs:** 5 models = Mistral Small, Mistral Medium, Mistral Large, Mistral Large 2 (via Mistral HTTP API, 2 keys x 10 traders) + Llama 4 Maverick (via NVIDIA API, 5 traders), no SDKs. Groq/Gemini configs preserved but no longer used for trading.

## Architecture

### AI Trader Pipeline (3-Phase)
The daily pipeline is split across Cloud Run and local Mac to leverage free Gemma preprocessing:

**Phase 1 — Cloud Run (5:00 PM ET)**
`POST /api/ai/pipeline/trigger?steps=brief,reflections`
1. **Market Brief** (`market_brief.py`) — fetches stock/crypto quotes, news, fundamentals, technicals, sentiment, insider trades from Finnhub/CoinGecko/Yahoo. Runs Gemma preprocessing if Ollama available (Cloud Run: no; local: yes).
2. **Reflections** (`reflection.py`) — reviews settled trades (3-5 days old, >3% price move) via Mistral, extracts lessons

**Phase 2 — Local Mac via launchd (5:05 PM ET)**
`backend/scripts/local_preprocess.py` — fetches today's brief from Supabase, runs Gemma 4 e2b preprocessing via Ollama, updates the brief in-place. Skips if preprocessing already exists. Four preprocessors run in parallel:
1. **Headline Clustering** — groups 15-25 headlines into 3-6 themed clusters with sentiment scores
2. **Analyst Consensus** — condenses per-symbol analyst recs into 1-line narratives
3. **Insider Flow** — aggregates insider buy/sell patterns into actionable summaries
4. **Movers Narrative** — explains *why* top gainers/losers moved (cross-references news, technicals, fundamentals)

**Phase 3 — Cloud Run (5:10 PM ET)**
`POST /api/ai/pipeline/trigger?steps=trading,commentary`
3. **Trading** (`ai_trader.py`) — each AI gets personalized RAG prompt with Gemma-enriched data, makes buy/sell decisions. Auto-snapshots all portfolios after.
4. **Commentary** (`ai_commentary.py`) — each AI writes a daily blog post explaining their decisions

All Gemma preprocessing has graceful fallback — if Ollama is unavailable, traders get raw data.

### AI Personalities
- **Vanilla** — balanced portfolio manager
- **Steady Eddie** — conservative, dividend-focused
- **YOLO Bot** — momentum/high-risk
- **Contrarian Carl** — buys fear, sells euphoria (mid-migration to **Contrarian Carl New** / `contrarian_carl_patient`: deep-value, long-horizon swing variant)
- **Crypto Chad** — crypto-heavy with stock hedges (mid-migration to **Crypto Chad New** / `crypto_chad_swing`: patient, tiered BTC/ETH-core swing variant)

Each personality line runs on 5 models (Mistral Small, Mistral Medium, Mistral Large, Mistral Large 2, Llama 4 Maverick) = 25 AI traders total. The Crypto Chad and Contrarian Carl lines are being migrated model-by-model from the base personality to the patient "New" variants (`V2_PERSONALITY_KEYS` in `ai_trader.py`), so the live DB mix is uneven (e.g. base Crypto Chad on 1 model, Crypto Chad New on 4). 20 Mistral traders split across 2 keys (10 each); 5 Llama 4 Maverick traders on the NVIDIA key.

### Key Services
| Service | Purpose |
|---------|---------|
| `ai_trader.py` | Trading decisions, performance intelligence, peer comparison |
| `rag_toolkit.py` | Assembles personalized data prompts per personality |
| `market_brief.py` | Daily market data collection (stocks, crypto, news, sentiment) |
| `reflection.py` | Post-trade learning loop (Mistral reviews settled trades) |
| `ai_commentary.py` | Daily blog posts per trader |
| `analytics.py` | Sortino ratio, module attribution, reflection trends, trade reasoning |
| `backtest.py` | Benchmark comparison, regime analysis, period comparison |
| `portfolio_optimizer.py` | Correlation analysis, target allocation, confidence-weighted position sizing |
| `gemma_preprocess.py` | Local Gemma preprocessors (headlines, analyst, insider, movers) |
| `snapshots.py` | Daily portfolio value snapshots |

### Data Sources (Free Tier)
| Source | Data | Notes |
|--------|------|-------|
| Finnhub | Stock quotes, news, fundamentals, analyst recs, earnings, insider trades | 60 req/min free tier. Economic calendar requires paid plan. |
| CoinGecko | Crypto prices, market cap, multi-timeframe changes, global stats (BTC dominance), categories/sectors, trending coins | No API key needed. 4 endpoints: /coins/markets, /global, /coins/categories, /search/trending |
| Yahoo Finance | Trending tickers (retail attention proxy) | No API key needed |
| alternative.me | Crypto Fear & Greed Index | No API key needed |

### Convergence Prevention
Peer comparison prompts in `_format_peer_comparison()` are hardened to prevent AI personality convergence:
- Explicitly identifies peer as another competing AI
- Adds staleness warnings on past trades
- Emphasizes independent decision-making with repetitive framing
- Warns against copying already-executed trades

## External Services

### GCP Cloud Run (Backend Hosting)
- Service: `papertrade-backend` in `us-east1`
- URL: `https://papertrade-backend-333762334828.us-east1.run.app`
- Dockerfile in `backend/`, built via Cloud Build
- Min instances: 1 (always-on), Max: 3, Memory: 512Mi, Timeout: 300s
- Deploy: `cd backend && gcloud run deploy papertrade-backend --source . --region us-east1`

### GCP Cloud Scheduler (Daily Automation)
Two scheduled jobs (timezone: America/New_York):
1. **papertrade-pipeline-phase1** — 5:00 PM daily → `POST /api/ai/pipeline/trigger?steps=brief,reflections`
2. **papertrade-pipeline-phase3** — 5:10 PM daily → `POST /api/ai/pipeline/trigger?steps=trading,commentary`
3. **papertrade-snapshots** — 5:30 PM daily → `POST /api/portfolio/snapshots/trigger` (safety net for human portfolios)

### Local launchd Job (Gemma Preprocessing)
- **Plist:** `~/Library/LaunchAgents/com.papertrade.preprocess.plist`
- **Script:** `backend/scripts/local_preprocess.py`
- **Schedule:** 5:05 PM ET daily (between Phase 1 and Phase 3)
- **Requires:** Ollama running locally with `gemma4:e2b` model pulled
- **Config:** `OLLAMA_BASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` in `.env`

### GCP Secret Manager
`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `FINNHUB_API_KEY`, `MISTRAL_API_KEY`, `MISTRAL_API_KEY_2`, `NVIDIA_API_KEY`

Plain env vars on Cloud Run: `STARTING_BALANCE=100000.00`, `FRONTEND_URL=https://papertrade-iota.vercel.app`

`MISTRAL_API_KEY` powers 10 traders (Mistral Large + Mistral Medium models) plus reflections and sentiment scoring.
`MISTRAL_API_KEY_2` powers the other 10 traders (Mistral Small + Mistral Large 2 models).
`NVIDIA_API_KEY` powers the 5 Llama 4 Maverick traders (`_call_nvidia_nim`, `nvidia-deepseek-r1` model key). Traders silently skip if unset.
`GROQ_API_KEY` is no longer used for trading but config is preserved.

## API Routes
- `/api/ai/` — AI trading triggers, commentary, trader profiles
- `/api/analytics/` — Performance analytics, reasoning viewer, comparisons
- `/api/market/` — Market data, briefs, quotes
- `/api/portfolio/` — Positions, snapshots, leaderboard
- `/api/auth/` — Supabase auth

## Database Tables (Key)
- `profiles` — user/AI accounts with personality and model info
- `transactions` — all trades with `reasoning` and `modules_used` fields
- `portfolio_snapshots` — daily portfolio values
- `market_briefs` — cached daily market data
- `ai_commentary` — daily blog posts per trader
- `trade_reflections` — post-trade analysis with outcome scores and lessons

## Development Notes
- Run backend locally: `cd backend && uvicorn app.main:app --reload --port 8001`
- Python command is `python3` on macOS (not `python`)
- LLM API keys default to empty string if unset — traders silently skip
- When replacing strings across codebase, always do exhaustive search first
- Deploy backend: `cd backend && gcloud run deploy papertrade-backend --source . --region us-east1`
- GCP project: `project-b95d122b-3728-497b-93f`
- Health check: `GET /api/health` — deep check of Supabase, Finnhub, Mistral, and today's brief
