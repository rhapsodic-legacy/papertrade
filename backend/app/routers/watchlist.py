from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Literal

from app.services.auth import get_user_id_from_token
from app.services.market_data import get_quote, TOP_STOCKS, CRYPTO_MAP
from app.services.supabase_client import get_supabase_admin

router = APIRouter()


class WatchlistAddRequest(BaseModel):
    symbol: str
    asset_type: Literal["stock", "crypto"]


@router.get("/")
async def get_watchlist(request: Request):
    user_id = get_user_id_from_token(request)
    db = get_supabase_admin()

    resp = (
        db.table("watchlist")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=False)
        .execute()
    )

    items = []
    for entry in resp.data:
        quote = await get_quote(entry["symbol"], entry["asset_type"])
        items.append(
            {
                "id": entry["id"],
                "symbol": entry["symbol"],
                "asset_type": entry["asset_type"],
                "price": quote["price"] if quote else None,
                "change": quote["change"] if quote else None,
                "change_pct": quote["change_pct"] if quote else None,
                "name": quote["name"] if quote else entry["symbol"],
            }
        )

    return items


@router.post("/")
async def add_to_watchlist(request: Request, body: WatchlistAddRequest):
    user_id = get_user_id_from_token(request)
    symbol = body.symbol.upper()

    if body.asset_type == "stock" and symbol not in TOP_STOCKS:
        raise HTTPException(status_code=400, detail=f"{symbol} is not a supported stock")
    if body.asset_type == "crypto" and symbol not in CRYPTO_MAP:
        raise HTTPException(status_code=400, detail=f"{symbol} is not a supported crypto")

    db = get_supabase_admin()

    # Check for duplicate
    existing = (
        db.table("watchlist")
        .select("id")
        .eq("user_id", user_id)
        .eq("symbol", symbol)
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=409, detail=f"{symbol} is already in your watchlist")

    resp = (
        db.table("watchlist")
        .insert(
            {
                "user_id": user_id,
                "symbol": symbol,
                "asset_type": body.asset_type,
            }
        )
        .execute()
    )

    return resp.data[0]


@router.delete("/{symbol}")
async def remove_from_watchlist(request: Request, symbol: str):
    user_id = get_user_id_from_token(request)
    db = get_supabase_admin()

    resp = (
        db.table("watchlist")
        .delete()
        .eq("user_id", user_id)
        .eq("symbol", symbol.upper())
        .execute()
    )

    if not resp.data:
        raise HTTPException(status_code=404, detail=f"{symbol} not found in watchlist")

    return {"message": f"{symbol.upper()} removed from watchlist"}
