from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, market, portfolio, trading

app = FastAPI(
    title="PaperTrade",
    description="Learn to invest risk-free with virtual money",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(market.router, prefix="/api/market", tags=["market"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(trading.router, prefix="/api/trading", tags=["trading"])


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
