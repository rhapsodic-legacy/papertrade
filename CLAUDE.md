# PaperTrade - Claude Code Guide

## Project Overview
Paper trading platform with $100k virtual portfolios. 20 AI traders (5 personalities x 4 LLM models) compete alongside human users. FastAPI backend, Next.js frontend, Supabase DB.

## Tech Stack
- **Backend:** FastAPI (Python 3.12) — `backend/`
- **Frontend:** Next.js 14 + TypeScript + Tailwind — `frontend/`
- **Database:** Supabase (Postgres + Auth)
- **Hosting:** Railway (backend), Vercel (frontend) — auto-deploy on push to main
- **LLMs:** Llama 3.1 8B, GPT-OSS 120B, Mistral, Llama 3.3 70B — all via Groq/Mistral HTTP APIs, no SDKs. Gemini disabled (spending cap), config preserved for re-enablement.

## Architecture

### AI Trader Pipeline
Single daily pipeline triggered via `POST /api/ai/pipeline/trigger?session=close`:
1. **Market Brief** (`market_brief.py`) — fetches stock/crypto quotes, news, fundamentals, technicals, sentiment, insider trades from Finnhub/CoinGecko/Yahoo
2. **Reflections** (`reflection.py`) — reviews settled trades (3-5 days old, >3% price move) via Groq, extracts lessons
3. **Trading** (`ai_trader.py`) — each AI gets personalized RAG prompt, makes buy/sell decisions. Auto-snapshots all portfolios after.
4. **Commentary** (`ai_commentary.py`) — each AI writes a daily blog post explaining their decisions

### AI Personalities
- **Vanilla** — balanced portfolio manager
- **Steady Eddie** — conservative, dividend-focused
- **YOLO Bot** — momentum/high-risk
- **Contrarian Carl** — buys fear, sells euphoria
- **Crypto Chad** — crypto-heavy with stock hedges

Each personality runs on 4 models (Llama 3.1 8B, GPT-OSS 120B, Mistral, Llama 3.3 70B) = 20 AI traders total.

### Key Services
| Service | Purpose |
|---------|---------|
| `ai_trader.py` | Trading decisions, performance intelligence, peer comparison |
| `rag_toolkit.py` | Assembles personalized data prompts per personality |
| `market_brief.py` | Daily market data collection (stocks, crypto, news, sentiment) |
| `reflection.py` | Post-trade learning loop (Groq reviews settled trades) |
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

### cron-job.org (Daily Automation)
Two active cron jobs:
1. **AI Pipeline** — 5:00 PM daily → `POST /api/ai/pipeline/trigger?session=close` (runs brief → reflections → trading → commentary)
2. **Daily Snapshots** — 5:30 PM daily → `POST /api/portfolio/snapshots/trigger` (safety net for human portfolios)

### Railway Environment Variables
`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `FINNHUB_API_KEY`, `STARTING_BALANCE`, `FRONTEND_URL`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `GROQ_API_KEY`

GROQ_API_KEY is required for reflections and Llama-based traders.

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
