# PaperTrade - Claude Code Guide

## Project Overview
Paper trading platform with $100k virtual portfolios. 20 AI traders (5 personalities x 4 LLM models) compete alongside human users. FastAPI backend, Next.js frontend, Supabase DB.

## Tech Stack
- **Backend:** FastAPI (Python 3.13) — `backend/`
- **Frontend:** Next.js 16 + TypeScript + Tailwind — `frontend/`
- **Database:** Supabase (Postgres + Auth)
- **Hosting:** GCP Cloud Run (backend), Vercel (frontend)
- **CI/CD:** Cloud Build (backend, manual deploy), Vercel auto-deploy (frontend)
- **Cron:** GCP Cloud Scheduler (2 jobs: pipeline + snapshots)
- **Secrets:** GCP Secret Manager
- **LLMs:** Mistral Small, Mistral Medium, Mistral Large, Mistral Large 2 — all via Mistral HTTP API (2 API keys, 10 traders each), no SDKs. Groq/Gemini configs preserved but no longer used for trading.

## Architecture

### AI Trader Pipeline
Single daily pipeline triggered via `POST /api/ai/pipeline/trigger?session=close`:
1. **Market Brief** (`market_brief.py`) — fetches stock/crypto quotes, news, fundamentals, technicals, sentiment, insider trades from Finnhub/CoinGecko/Yahoo
2. **Reflections** (`reflection.py`) — reviews settled trades (3-5 days old, >3% price move) via Mistral, extracts lessons
3. **Trading** (`ai_trader.py`) — each AI gets personalized RAG prompt, makes buy/sell decisions. Auto-snapshots all portfolios after.
4. **Commentary** (`ai_commentary.py`) — each AI writes a daily blog post explaining their decisions

### AI Personalities
- **Vanilla** — balanced portfolio manager
- **Steady Eddie** — conservative, dividend-focused
- **YOLO Bot** — momentum/high-risk
- **Contrarian Carl** — buys fear, sells euphoria
- **Crypto Chad** — crypto-heavy with stock hedges

Each personality runs on 4 Mistral models (Mistral Small, Mistral Medium, Mistral Large, Mistral Large 2) = 20 AI traders total. Split across 2 API keys (10 each).

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
| `portfolio_optimizer.py` | Position sizing suggestions |
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
1. **papertrade-pipeline** — 5:00 PM daily → `POST /api/ai/pipeline/trigger?session=close` (brief → reflections → trading → commentary)
2. **papertrade-snapshots** — 5:30 PM daily → `POST /api/portfolio/snapshots/trigger` (safety net for human portfolios)

### GCP Secret Manager
`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `FINNHUB_API_KEY`, `MISTRAL_API_KEY`, `MISTRAL_API_KEY_2`

Plain env vars on Cloud Run: `STARTING_BALANCE=100000.00`, `FRONTEND_URL=https://papertrade-iota.vercel.app`

`MISTRAL_API_KEY` powers 10 traders (Mistral Large + Mistral Medium models) plus reflections and sentiment scoring.
`MISTRAL_API_KEY_2` powers the other 10 traders (Mistral Small + Mistral Large 2 models).
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
