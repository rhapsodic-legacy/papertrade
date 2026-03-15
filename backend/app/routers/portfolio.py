from fastapi import APIRouter, Request

from app.services.auth import get_user_id_from_token
from app.services.leaderboard import get_scored_leaderboard
from app.services.market_data import get_quote
from app.services.snapshots import take_all_snapshots
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
async def get_leaderboard(
    request: Request,
    category: str = "human",
    limit: int = 25,
):
    # Get user_id if authenticated (optional for leaderboard)
    try:
        user_id = get_user_id_from_token(request)
    except Exception:
        user_id = None

    return await get_scored_leaderboard(
        user_id=user_id,
        category=category,
        limit=limit,
    )


@router.get("/snapshots")
async def get_portfolio_snapshots(request: Request, days: int = 30):
    user_id = get_user_id_from_token(request)
    db = get_supabase_admin()

    resp = (
        db.table("portfolio_snapshots")
        .select("snapshot_date, total_value, cash_balance, invested_value")
        .eq("user_id", user_id)
        .order("snapshot_date", desc=False)
        .limit(days)
        .execute()
    )

    return resp.data


@router.post("/snapshots/trigger")
async def trigger_snapshots():
    """Take a snapshot of all users' portfolios. Call daily via cron."""
    count = await take_all_snapshots()
    return {"message": f"Snapshots created for {count} users"}
