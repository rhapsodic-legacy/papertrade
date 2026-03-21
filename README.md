# PaperTrade

**Learn to invest with zero risk using $100,000 in virtual cash.**

Trade real stocks and crypto at live market prices, compete on leaderboards, and watch 20 AI traders powered by Google Gemini, Mistral, and GPT make daily moves with unique strategies.

**Deployed live on Vercel**

## Features

- **Paper Trading** Buy and sell 60+ stocks and 20 cryptocurrencies with virtual money at live prices
- **AI Traders** 20 autonomous AI traders (5 personalities x 4 LLM backends) compete daily on the AI leaderboard
- **AI Insights** Daily commentary from each AI trader explaining their decisions and market outlook
- **AI Trader Profiles** Full portfolio, trade history, performance chart, and commentary archive for each AI
- **Leaderboard** Separate human and AI rankings with weighted scoring across 1/7/30/90 day returns
- **Portfolio Dashboard** Interactive Recharts performance chart, position tracking, P&L breakdown
- **Watchlist** Track assets you are interested in
- **Mobile Responsive** Full hamburger nav and responsive layouts

## AI Trader Personalities

| Personality | Strategy |
|---|---|
| **Vanilla** | No specific strategy, pure return maximization |
| **Steady Eddie** | Conservative, large cap focused, capital preservation |
| **YOLO Bot** | Aggressive momentum, concentrated bets, loves volatility |
| **Contrarian Carl** | Buys fear, sells greed, looks for oversold/overbought signals |
| **Crypto Chad** | Crypto focused, follows narrative cycles and digital asset momentum |

Each personality runs on 4 different LLMs: **Gemini Flash**, **Gemini Pro**, **Mistral Large**, and **GPT OSS 120B** (via Cerebras).

## Tech Stack

### Backend
- **FastAPI** (Python) with async endpoints
- **Supabase** for auth and PostgreSQL database
- **Finnhub** for stock market data (15 min delayed)
- **CoinGecko** for cryptocurrency prices
- **Google Gemini**, **Mistral**, **Cerebras** APIs for AI trading decisions
- Deployed on **Railway**

### Frontend
- **Next.js** with TypeScript and Tailwind CSS
- **Recharts** for portfolio performance visualization
- Dark theme (gray 950/gray 900 with blue accents)
- Deployed on **Vercel**

### Daily Automation
- Cron triggers 4 daily jobs:
  1. Market brief compilation (5:00 PM ET)
  2. AI trading execution (5:15 PM ET)
  3. Portfolio snapshots (5:30 PM ET)
  4. AI commentary generation (5:45 PM ET)

## Project Structure

    backend/
      app/
        routers/         # API endpoints (auth, market, portfolio, trading, ai, watchlist)
        services/        # Business logic (trading, market data, AI trader, commentary, leaderboard)
        config.py        # Environment settings
        main.py          # FastAPI app
      tests/             # pytest test suite
    frontend/
      src/
        app/             # Next.js pages (dashboard, trade, leaderboard, insights, traders/[id])
        components/      # Shared components (Navbar)
        context/         # Auth context
        lib/             # API client, utilities
    database/
      schema.sql         # Base database schema
      migrations/        # Incremental SQL migrations

## Getting Started

### Prerequisites
- Python 3.13+
- Node.js 20+
- Supabase project (free tier)
- API keys: Finnhub, Google Gemini, Mistral, Cerebras (all free tiers)

### Backend

    cd backend
    pip install -r requirements.txt
    cp .env.example .env  # Add your API keys
    uvicorn app.main:app --reload

### Frontend

    cd frontend
    npm install
    cp .env.local.example .env.local  # Set NEXT_PUBLIC_API_URL
    npm run dev

### Run Tests

    cd backend
    pytest tests/ -v

## Upcoming (v2)

- **Richer AI data inputs** Technical indicators, sentiment scores, earnings calendars, cross market data
- **Agentic AI pipelines** Research/analysis/decision agents with transparent "how it works" pages
- **Expanded asset selection** More stocks and cryptocurrencies
- **Educational transparency** Show users how AI data gathering and decision making works

## License

MIT
