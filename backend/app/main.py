import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, market, portfolio, trading, watchlist

app = FastAPI(
    title="PaperTrade",
    description="Learn to invest risk-free with virtual money",
    version="0.1.0",
)

allowed_origins = [
    "http://localhost:3000",
    "https://papertrade-iota.vercel.app",
]
frontend_url = os.environ.get("FRONTEND_URL")
if frontend_url and frontend_url not in allowed_origins:
    allowed_origins.append(frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(market.router, prefix="/api/market", tags=["market"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(trading.router, prefix="/api/trading", tags=["trading"])
app.include_router(watchlist.router, prefix="/api/watchlist", tags=["watchlist"])


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


@app.get("/api/debug-env")
async def debug_env():
    from app.config import get_settings
    try:
        settings = get_settings()
        has_settings = True
        settings_error = None
    except Exception as e:
        has_settings = False
        settings_error = str(e)
    return {
        "has_supabase_url": bool(os.environ.get("SUPABASE_URL")),
        "has_supabase_anon_key": bool(os.environ.get("SUPABASE_ANON_KEY")),
        "has_supabase_service_role_key": bool(os.environ.get("SUPABASE_SERVICE_ROLE_KEY")),
        "has_finnhub_api_key": bool(os.environ.get("FINNHUB_API_KEY")),
        "has_starting_balance": bool(os.environ.get("STARTING_BALANCE")),
        "env_var_count": len(os.environ),
        "has_settings": has_settings,
        "settings_error": settings_error,
    }
