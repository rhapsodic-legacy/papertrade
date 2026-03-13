from fastapi import HTTPException

from app.services.market_data import get_quote, is_stock_market_open
from app.services.supabase_client import get_supabase_admin


async def execute_trade(
    user_id: str, symbol: str, asset_type: str, side: str, quantity: float
) -> dict:
    # Check market hours for stocks
    if asset_type == "stock" and not is_stock_market_open():
        raise HTTPException(
            status_code=400,
            detail="Stock market is currently closed. Trading hours: Mon-Fri 9:30 AM - 4:00 PM ET.",
        )

    # Get current price
    quote = await get_quote(symbol, asset_type)
    if not quote:
        raise HTTPException(status_code=404, detail=f"Could not get quote for {symbol}")

    price = quote["price"]
    total = round(price * quantity, 8)

    db = get_supabase_admin()

    # Get user profile
    profile_resp = db.table("profiles").select("*").eq("id", user_id).single().execute()
    profile = profile_resp.data
    if not profile:
        raise HTTPException(status_code=404, detail="User profile not found")

    cash_balance = float(profile["cash_balance"])

    if side == "buy":
        if total > cash_balance:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient funds. Need ${total:.2f}, have ${cash_balance:.2f}",
            )
        _execute_buy(db, user_id, symbol, asset_type, quantity, price, total, cash_balance)

    elif side == "sell":
        _execute_sell(db, user_id, symbol, asset_type, quantity, price, total, cash_balance)

    # Record transaction
    tx = (
        db.table("transactions")
        .insert(
            {
                "user_id": user_id,
                "symbol": symbol,
                "asset_type": asset_type,
                "side": side,
                "quantity": quantity,
                "price": price,
                "total": total,
            }
        )
        .execute()
    )

    return tx.data[0]


def _execute_buy(
    db, user_id: str, symbol: str, asset_type: str,
    quantity: float, price: float, total: float, cash_balance: float
):
    # Update cash balance
    db.table("profiles").update(
        {"cash_balance": cash_balance - total}
    ).eq("id", user_id).execute()

    # Update or create position
    pos_resp = (
        db.table("positions")
        .select("*")
        .eq("user_id", user_id)
        .eq("symbol", symbol)
        .execute()
    )

    if pos_resp.data:
        existing = pos_resp.data[0]
        old_qty = float(existing["quantity"])
        old_cost = float(existing["avg_cost_basis"])
        new_qty = old_qty + quantity
        new_avg_cost = ((old_qty * old_cost) + (quantity * price)) / new_qty

        db.table("positions").update(
            {"quantity": new_qty, "avg_cost_basis": round(new_avg_cost, 8)}
        ).eq("id", existing["id"]).execute()
    else:
        db.table("positions").insert(
            {
                "user_id": user_id,
                "symbol": symbol,
                "asset_type": asset_type,
                "quantity": quantity,
                "avg_cost_basis": price,
            }
        ).execute()


def _execute_sell(
    db, user_id: str, symbol: str, asset_type: str,
    quantity: float, price: float, total: float, cash_balance: float
):
    # Check existing position
    pos_resp = (
        db.table("positions")
        .select("*")
        .eq("user_id", user_id)
        .eq("symbol", symbol)
        .execute()
    )

    if not pos_resp.data or float(pos_resp.data[0]["quantity"]) < quantity:
        available = float(pos_resp.data[0]["quantity"]) if pos_resp.data else 0
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient shares. Have {available}, trying to sell {quantity}",
        )

    existing = pos_resp.data[0]
    new_qty = float(existing["quantity"]) - quantity

    # Update cash balance
    db.table("profiles").update(
        {"cash_balance": cash_balance + total}
    ).eq("id", user_id).execute()

    # Update position
    if new_qty == 0:
        db.table("positions").delete().eq("id", existing["id"]).execute()
    else:
        db.table("positions").update(
            {"quantity": new_qty}
        ).eq("id", existing["id"]).execute()
