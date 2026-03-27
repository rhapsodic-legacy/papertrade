from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.services.analytics import get_portfolio_health
from app.services.auth import get_user_id_from_token
from app.services.leaderboard import get_scored_leaderboard
from app.services.market_data import get_quote, STOCK_SECTORS
from app.services.market_brief import get_latest_brief
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


@router.get("/health")
async def portfolio_health(request: Request):
    """Portfolio health score with AI comparison. Requires auth."""
    user_id = get_user_id_from_token(request)
    return await get_portfolio_health(user_id)


class RiskCheckRequest(BaseModel):
    symbol: str
    asset_type: str
    side: str
    quantity: float


@router.post("/risk-check")
async def pre_trade_risk_check(request: Request, body: RiskCheckRequest):
    """Pre-trade risk check: shows how a proposed trade would affect the portfolio.
    Returns concentration warnings, correlation risks, and position sizing feedback."""
    user_id = get_user_id_from_token(request)
    db = get_supabase_admin()

    # Get current portfolio state
    profile = db.table("profiles").select("cash_balance").eq("id", user_id).single().execute()
    cash = float(profile.data["cash_balance"])

    positions_resp = (
        db.table("positions")
        .select("symbol, asset_type, quantity, avg_cost_basis")
        .eq("user_id", user_id)
        .gt("quantity", 0)
        .execute()
    )

    # Build current portfolio picture
    positions = []
    total_invested = 0.0
    for pos in positions_resp.data:
        qty = float(pos["quantity"])
        avg_cost = float(pos["avg_cost_basis"])
        quote = await get_quote(pos["symbol"], pos["asset_type"])
        price = quote["price"] if quote else avg_cost
        mv = qty * price
        total_invested += mv
        positions.append({
            "symbol": pos["symbol"],
            "asset_type": pos["asset_type"],
            "quantity": qty,
            "market_value": mv,
        })

    total_value = cash + total_invested

    # Get price for proposed trade
    trade_quote = await get_quote(body.symbol, body.asset_type)
    if not trade_quote:
        return {"warnings": [], "info": []}

    trade_price = trade_quote["price"]
    trade_value = trade_price * body.quantity

    warnings = []
    info = []

    if body.side == "buy":
        # Cash check
        if trade_value > cash:
            warnings.append({
                "type": "insufficient_cash",
                "severity": "high",
                "message": f"This trade costs {_fmt_currency(trade_value)} but you only have {_fmt_currency(cash)} cash.",
            })

        # New portfolio value after trade
        new_total = total_value  # buying doesn't change total, just moves cash to position

        # Find existing position in this symbol
        existing = next((p for p in positions if p["symbol"] == body.symbol.upper()), None)
        existing_value = existing["market_value"] if existing else 0
        new_position_value = existing_value + trade_value
        new_position_pct = (new_position_value / new_total * 100) if new_total > 0 else 0

        if new_position_pct > 15:
            warnings.append({
                "type": "concentration",
                "severity": "high" if new_position_pct > 25 else "medium",
                "message": f"This would make {body.symbol.upper()} {new_position_pct:.1f}% of your portfolio. Most fund managers cap single positions at 10-15%.",
            })

        # Sector concentration
        trade_sector = STOCK_SECTORS.get(body.symbol.upper(), "Crypto" if body.asset_type == "crypto" else "Other")
        sector_value = trade_value
        for p in positions:
            p_sector = STOCK_SECTORS.get(p["symbol"], "Crypto" if p["asset_type"] == "crypto" else "Other")
            if p_sector == trade_sector:
                sector_value += p["market_value"]
        sector_pct = (sector_value / new_total * 100) if new_total > 0 else 0
        if sector_pct > 40:
            warnings.append({
                "type": "sector_concentration",
                "severity": "medium",
                "message": f"Your {trade_sector} sector exposure would be {sector_pct:.0f}%. Consider diversifying across sectors.",
            })

        # Check for correlated holdings
        correlated_holdings = []
        tech_stocks = {"AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "CRM", "ORCL", "ADBE", "AMD", "INTC", "AVGO"}
        if body.symbol.upper() in tech_stocks:
            for p in positions:
                if p["symbol"] in tech_stocks and p["symbol"] != body.symbol.upper():
                    correlated_holdings.append(p["symbol"])
        if correlated_holdings:
            warnings.append({
                "type": "correlation",
                "severity": "low",
                "message": f"You already hold {', '.join(correlated_holdings[:3])} which tend to move together with {body.symbol.upper()}.",
            })

        # Cash allocation after trade
        remaining_cash_pct = ((cash - trade_value) / new_total * 100) if new_total > 0 else 0
        if remaining_cash_pct < 5 and cash - trade_value > 0:
            warnings.append({
                "type": "low_cash",
                "severity": "low",
                "message": f"You'd have {remaining_cash_pct:.1f}% cash remaining ({_fmt_currency(cash - trade_value)}). Consider keeping some dry powder.",
            })

        # Helpful info
        info.append(f"Position size: {new_position_pct:.1f}% of portfolio")
        info.append(f"Remaining cash: {_fmt_currency(max(0, cash - trade_value))}")

    else:
        # Sell side — simpler checks
        existing = next((p for p in positions if p["symbol"] == body.symbol.upper()), None)
        if not existing:
            warnings.append({
                "type": "no_position",
                "severity": "high",
                "message": f"You don't hold any {body.symbol.upper()} to sell.",
            })
        elif body.quantity > existing["quantity"]:
            warnings.append({
                "type": "insufficient_quantity",
                "severity": "high",
                "message": f"You only have {existing['quantity']} {body.symbol.upper()} but are trying to sell {body.quantity}.",
            })

    # Earnings warning
    brief = await get_latest_brief()
    if brief:
        earnings = brief.get("earnings_calendar", [])
        for e in earnings:
            if e.get("symbol") == body.symbol.upper():
                eps_str = f" (est. EPS ${e['estimate_eps']:.2f})" if e.get("estimate_eps") else ""
                info.append(f"Earnings report on {e['date']}{eps_str} — expect volatility")
                break

    return {
        "warnings": warnings,
        "info": info,
        "trade_value": round(trade_value, 2),
        "price": trade_price,
    }


def _fmt_currency(amount: float) -> str:
    return f"${amount:,.2f}"


@router.post("/snapshots/trigger")
async def trigger_snapshots():
    """Take a snapshot of all users' portfolios. Call daily via cron."""
    count = await take_all_snapshots()
    return {"message": f"Snapshots created for {count} users"}
