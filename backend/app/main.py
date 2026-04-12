import logging
import os
import sys

# Force unbuffered stdout so print() from background threads shows in Railway logs
sys.stdout.reconfigure(line_buffering=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Configure root logger so all logger.error/warning/info calls show in Railway logs
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s: %(message)s",
)

from app.routers import ai, analytics, auth, consensus_qa, custom_traders, market, notifications, portfolio, simulator, trading, watchlist

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

app.include_router(ai.router, prefix="/api/ai", tags=["ai"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(consensus_qa.router, prefix="/api/consensus-qa", tags=["consensus-qa"])
app.include_router(custom_traders.router, prefix="/api/custom-traders", tags=["custom-traders"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(market.router, prefix="/api/market", tags=["market"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(simulator.router, prefix="/api/simulator", tags=["simulator"])
app.include_router(trading.router, prefix="/api/trading", tags=["trading"])
app.include_router(watchlist.router, prefix="/api/watchlist", tags=["watchlist"])


@app.get("/api/health")
async def health_check():
    """Deep health check: verify Supabase, Finnhub, Mistral, and today's brief."""
    import httpx
    from datetime import date
    from app.config import get_settings

    settings = get_settings()
    checks: dict = {}

    # 1. Supabase — lightweight query
    try:
        from app.services.supabase_client import get_supabase_admin
        db = get_supabase_admin()
        result = db.table("profiles").select("id").limit(1).execute()
        checks["supabase"] = "ok" if result.data else "empty"
    except Exception as e:
        checks["supabase"] = f"error: {str(e)[:100]}"

    # 2. Finnhub — quote endpoint
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": "AAPL", "token": settings.finnhub_api_key},
            )
            data = resp.json()
            checks["finnhub"] = "ok" if data.get("c", 0) > 0 else "no_price"
    except Exception as e:
        checks["finnhub"] = f"error: {str(e)[:100]}"

    # 3. Mistral — lightweight models list
    if settings.mistral_api_key:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    "https://api.mistral.ai/v1/models",
                    headers={"Authorization": f"Bearer {settings.mistral_api_key}"},
                )
                checks["mistral"] = "ok" if resp.status_code == 200 else f"http_{resp.status_code}"
        except Exception as e:
            checks["mistral"] = f"error: {str(e)[:100]}"
    else:
        checks["mistral"] = "no_key"

    # 4. Today's market brief
    try:
        from app.services.supabase_client import get_supabase_admin
        db = get_supabase_admin()
        today_str = date.today().isoformat()
        brief = (
            db.table("market_briefs")
            .select("id, created_at")
            .gte("created_at", f"{today_str}T00:00:00")
            .limit(1)
            .execute()
        )
        checks["todays_brief"] = "ok" if brief.data else "missing"
    except Exception as e:
        checks["todays_brief"] = f"error: {str(e)[:100]}"

    all_ok = all(v == "ok" for v in checks.values())
    return {"status": "ok" if all_ok else "degraded", "checks": checks}
