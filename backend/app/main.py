import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Configure root logger so all logger.error/warning/info calls show in Railway logs
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s: %(message)s",
)

from app.routers import ai, analytics, auth, market, notifications, portfolio, trading, watchlist

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
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(market.router, prefix="/api/market", tags=["market"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(trading.router, prefix="/api/trading", tags=["trading"])
app.include_router(watchlist.router, prefix="/api/watchlist", tags=["watchlist"])


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
