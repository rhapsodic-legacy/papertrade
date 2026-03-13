from fastapi import APIRouter, Request

from app.services.auth import get_user_id_from_token
from app.services.market_data import get_quote
from app.services.supabase_client import get_supabase_admin

router = APIRouter()


@router.get("/")
async def get_portfolio(request: Request):
    user_id = get_user_id_from_token(request)
    db = get_supabase_admin()

    # Get profile
    profile = db.table("profiles").select("*").eq("id", user_id).single().execute()
    cash_balance = float(profile.data["cash_balance"])

    # Get positions
    positions_resp = (
        db.table("positions")
        .select("*")
        .eq("user_id", user_id)
        .gt("quantity", 0)
        .execute()
    )

    positions = []
    invested_value = 0.0

    for pos in positions_resp.data:
        qty = float(pos["quantity"])
        avg_cost = float(pos["avg_cost_basis"])
        cost_basis_total = qty * avg_cost

        # Fetch live price
        quote = await get_quote(pos["symbol"], pos["asset_type"])
        current_price = quote["price"] if quote else avg_cost
        market_value = qty * current_price
        pnl = market_value - cost_basis_total
        pnl_pct = (pnl / cost_basis_total * 100) if cost_basis_total > 0 else 0

        invested_value += market_value
        positions.append(
            {
                "symbol": pos["symbol"],
                "asset_type": pos["asset_type"],
                "quantity": qty,
                "avg_cost_basis": avg_cost,
                "current_price": current_price,
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(pnl, 2),
                "unrealized_pnl_pct": round(pnl_pct, 2),
            }
        )

    return {
        "cash_balance": cash_balance,
        "invested_value": round(invested_value, 2),
        "total_value": round(cash_balance + invested_value, 2),
        "positions": positions,
    }


@router.get("/history")
async def get_transaction_history(request: Request, limit: int = 50):
    user_id = get_user_id_from_token(request)
    db = get_supabase_admin()

    resp = (
        db.table("transactions")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )

    return resp.data


@router.get("/leaderboard")
async def get_leaderboard(limit: int = 20):
    db = get_supabase_admin()

    # Get all profiles
    profiles_resp = db.table("profiles").select("*").execute()

    # Get all open positions
    positions_resp = db.table("positions").select("*").gt("quantity", 0).execute()

    # Group positions by user
    positions_by_user: dict[str, list] = {}
    for pos in positions_resp.data:
        positions_by_user.setdefault(pos["user_id"], []).append(pos)

    # Fetch live prices for all unique symbols (cache makes this fast)
    symbols_seen: dict[str, float] = {}
    for pos in positions_resp.data:
        key = f"{pos['asset_type']}:{pos['symbol']}"
        if key not in symbols_seen:
            quote = await get_quote(pos["symbol"], pos["asset_type"])
            symbols_seen[key] = quote["price"] if quote else float(pos["avg_cost_basis"])

    # Calculate live portfolio values
    entries = []
    for profile in profiles_resp.data:
        cash = float(profile["cash_balance"])
        invested = 0.0
        for pos in positions_by_user.get(profile["id"], []):
            key = f"{pos['asset_type']}:{pos['symbol']}"
            price = symbols_seen.get(key, float(pos["avg_cost_basis"]))
            invested += float(pos["quantity"]) * price

        entries.append(
            {
                "display_name": profile["display_name"],
                "total_portfolio_value": round(cash + invested, 2),
                "cash_balance": round(cash, 2),
                "invested_value": round(invested, 2),
            }
        )

    # Sort by total value descending, add ranks
    entries.sort(key=lambda e: e["total_portfolio_value"], reverse=True)
    for i, entry in enumerate(entries[:limit], 1):
        entry["rank"] = i

    return entries[:limit]
