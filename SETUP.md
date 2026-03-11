# PaperTrade Setup Guide

## Prerequisites
- Python 3.11+
- Node.js 18+
- A free Supabase account (https://supabase.com)
- A free Finnhub account (https://finnhub.io)

## 1. Supabase Setup

1. Create a new project at https://supabase.com
2. Go to **SQL Editor** and paste the contents of database/schema.sql, then run it
3. Go to **Settings > API** and copy:
   - Project URL
   - anon public key
   - service_role secret key

## 2. Finnhub Setup

1. Sign up at https://finnhub.io
2. Copy your API key from the dashboard

## 3. Backend Setup

    cd backend
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt

    # Create .env from the example
    cp .env.example .env
    # Edit .env with your Supabase and Finnhub credentials

    # Run the server
    uvicorn app.main:app --reload --port 8000

The API will be available at http://localhost:8000
API docs at http://localhost:8000/docs

## 4. Frontend Setup

    cd frontend

    # Create .env.local from the example
    cp .env.local.example .env.local
    # Edit .env.local with your Supabase URL and anon key

    npm install
    npm run dev

The app will be available at http://localhost:3000

## Project Structure

    fintech_support/
      backend/
        app/
          main.py            -- FastAPI entry point
          config.py          -- Environment config
          routers/           -- API route handlers
            auth.py          -- Sign up, sign in, profile
            market.py        -- Quotes, asset lists, market status
            portfolio.py     -- Portfolio, history, leaderboard
            trading.py       -- Place trades
          services/          -- Business logic
            auth.py          -- Auth helpers
            market_data.py   -- Finnhub + CoinGecko integration
            trading.py       -- Trade execution engine
            supabase_client.py
          schemas/           -- Pydantic models
      frontend/
        src/
          app/               -- Next.js pages
            auth/            -- Login / signup
            dashboard/       -- Portfolio overview
            trade/           -- Buy / sell interface
            history/         -- Transaction log
            leaderboard/     -- Rankings
          components/        -- Shared UI components
          context/           -- React context (auth)
          lib/               -- API client, utilities
      database/
        schema.sql           -- Supabase schema (run in SQL editor)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/auth/signup | Create account |
| POST | /api/auth/signin | Log in |
| GET | /api/auth/profile | Get user profile |
| GET | /api/market/assets | List available assets |
| GET | /api/market/quote/{type}/{symbol} | Get price quote |
| GET | /api/market/status | Check market hours |
| POST | /api/trading/trade | Place a trade |
| GET | /api/portfolio/ | Get portfolio + positions |
| GET | /api/portfolio/history | Transaction history |
| GET | /api/portfolio/leaderboard | Top traders |
