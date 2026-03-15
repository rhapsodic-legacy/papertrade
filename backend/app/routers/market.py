from fastapi import APIRouter, HTTPException

from app.services.market_brief import compile_market_brief, get_latest_brief
from app.services.market_data import (
    get_quote,
    get_available_assets,
    is_stock_market_open,
    TOP_STOCKS,
    CRYPTO_MAP,
)

router = APIRouter()


@router.get("/assets")
async def list_assets():
    return await get_available_assets()


@router.get("/quote/{asset_type}/{symbol}")
async def quote(asset_type: str, symbol: str):
    if asset_type not in ("stock", "crypto"):
        raise HTTPException(status_code=400, detail="asset_type must be 'stock' or 'crypto'")

    if asset_type == "stock" and symbol.upper() not in TOP_STOCKS:
        raise HTTPException(status_code=400, detail=f"{symbol} is not in the supported stock list")

    if asset_type == "crypto" and symbol.upper() not in CRYPTO_MAP:
        raise HTTPException(status_code=400, detail=f"{symbol} is not in the supported crypto list")

    result = await get_quote(symbol, asset_type)
    if not result:
        raise HTTPException(status_code=502, detail=f"Failed to fetch quote for {symbol}")
    return result


@router.get("/status")
async def market_status():
    return {
        "stock_market_open": is_stock_market_open(),
        "crypto_market_open": True,  # 24/7
    }


@router.post("/brief/trigger")
async def trigger_brief():
    """Compile today's market brief. Call daily via cron before AI trading."""
    brief = await compile_market_brief()
    return {
        "message": "Market brief compiled",
        "date": brief["date"],
        "stocks": len(brief["stocks"]),
        "crypto": len(brief["crypto"]),
        "news": len(brief["news"]),
    }


@router.get("/brief")
async def latest_brief():
    """Get the most recent market brief."""
    brief = await get_latest_brief()
    if not brief:
        raise HTTPException(status_code=404, detail="No market brief available")
    return brief
