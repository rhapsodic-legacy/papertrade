import logging
from datetime import date

from app.services.market_data import get_quote
from app.services.supabase_client import get_supabase_admin

logger = logging.getLogger(__name__)


async def take_all_snapshots() -> int:
    """Snapshot every user's portfolio value. Returns count of snapshots created."""
    db = get_supabase_admin()
    today = date.today().isoformat()

    # Get all profiles
    profiles_resp = db.table("profiles").select("id, cash_balance").execute()

    # Get all open positions
    positions_resp = db.table("positions").select("*").gt("quantity", 0).execute()

    # Group positions by user
    positions_by_user: dict[str, list] = {}
    for pos in positions_resp.data:
        positions_by_user.setdefault(pos["user_id"], []).append(pos)

    # Fetch live prices for all unique symbols
    prices: dict[str, float] = {}
    for pos in positions_resp.data:
        key = f"{pos['asset_type']}:{pos['symbol']}"
        if key not in prices:
            quote = await get_quote(pos["symbol"], pos["asset_type"])
            prices[key] = quote["price"] if quote else float(pos["avg_cost_basis"])

    # Build snapshot rows
    rows = []
    for profile in profiles_resp.data:
        cash = float(profile["cash_balance"])
        invested = 0.0
        for pos in positions_by_user.get(profile["id"], []):
            key = f"{pos['asset_type']}:{pos['symbol']}"
            price = prices.get(key, float(pos["avg_cost_basis"]))
            invested += float(pos["quantity"]) * price

        rows.append({
            "user_id": profile["id"],
            "total_value": round(cash + invested, 2),
            "cash_balance": round(cash, 2),
            "invested_value": round(invested, 2),
            "snapshot_date": today,
        })

    if rows:
        # Upsert so re-running on the same day updates rather than errors
        db.table("portfolio_snapshots").upsert(
            rows, on_conflict="user_id,snapshot_date"
        ).execute()

    # Check price alerts using the prices we already fetched
    try:
        from app.services.notifications import check_price_alerts
        # Convert "asset_type:SYMBOL" keys to just "SYMBOL"
        symbol_prices = {k.split(":", 1)[1]: v for k, v in prices.items()}
        await check_price_alerts(symbol_prices)
    except Exception as e:
        logger.error("Failed to check price alerts: %s", e)

    return len(rows)
