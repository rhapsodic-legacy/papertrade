import asyncio

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.services.market_brief import compile_market_brief, get_latest_brief
from app.services.market_data import (
    get_quote,
    get_available_assets,
    is_stock_market_open,
    get_stock_candles,
    get_crypto_history,
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


@router.get("/history/{asset_type}/{symbol}")
async def price_history(
    asset_type: str,
    symbol: str,
    days: int = Query(30, ge=1, le=365),
):
    """Get historical price data for charting."""
    if asset_type == "stock":
        if symbol.upper() not in TOP_STOCKS:
            raise HTTPException(status_code=400, detail=f"{symbol} not supported")
        data = await get_stock_candles(symbol, days)
    elif asset_type == "crypto":
        if symbol.upper() not in CRYPTO_MAP:
            raise HTTPException(status_code=400, detail=f"{symbol} not supported")
        data = await get_crypto_history(symbol, days)
    else:
        raise HTTPException(status_code=400, detail="asset_type must be 'stock' or 'crypto'")

    if not data:
        raise HTTPException(status_code=502, detail=f"No history available for {symbol}")
    return {"symbol": symbol.upper(), "asset_type": asset_type, "candles": data}


@router.get("/status")
async def market_status():
    return {
        "stock_market_open": is_stock_market_open(),
        "crypto_market_open": True,  # 24/7
    }


@router.post("/brief/trigger")
async def trigger_brief(background_tasks: BackgroundTasks):
    """Compile today's market brief. Call daily via cron before AI trading.
    Returns immediately; compilation runs in the background."""
    background_tasks.add_task(asyncio.to_thread, _run_brief_sync)
    return {"message": "Market brief compilation triggered — running in background"}


@router.get("/brief")
async def latest_brief():
    """Get the most recent market brief."""
    brief = await get_latest_brief()
    if not brief:
        raise HTTPException(status_code=404, detail="No market brief available")
    return brief


def _run_brief_sync():
    """Wrapper to run the async brief compilation from a sync context."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(compile_market_brief())
    finally:
        loop.close()
