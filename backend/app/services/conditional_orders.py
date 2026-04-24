"""Conditional order engine — save, check triggers, execute, expire, cancel siblings.

Pure code logic: no LLM calls. The intraday subagent polls prices and calls
check_and_execute_orders() on a schedule.
"""

import logging
from datetime import datetime, timezone

from app.services.market_data import get_batch_quotes, CRYPTO_MAP, TOP_STOCKS
from app.services.supabase_client import get_supabase_admin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Save orders from daily LLM output
# ---------------------------------------------------------------------------

VALID_ORDER_TYPES = {"limit_buy", "stop_loss", "take_profit", "trailing_stop"}
VALID_SIDES = {"buy", "sell"}


def save_conditional_orders(user_id: str, orders: list[dict]) -> list[dict]:
    """Persist conditional orders from AI trader output. Returns saved rows."""
    db = get_supabase_admin()
    saved = []

    for order in orders:
        order_type = order.get("order_type", "")
        if order_type not in VALID_ORDER_TYPES:
            logger.warning("Skipping invalid order_type: %s", order_type)
            continue

        symbol = order.get("symbol", "").upper()
        asset_type = order.get("asset_type", "")
        side = order.get("side", "")
        quantity = order.get("quantity", 0)

        # Validate basics
        if asset_type not in ("stock", "crypto"):
            continue
        if side not in VALID_SIDES:
            continue
        if not quantity or quantity <= 0:
            continue
        if asset_type == "stock" and symbol not in TOP_STOCKS:
            continue
        if asset_type == "crypto" and symbol not in CRYPTO_MAP:
            continue

        row = {
            "user_id": user_id,
            "symbol": symbol,
            "asset_type": asset_type,
            "order_type": order_type,
            "side": side,
            "quantity": quantity,
            "reasoning": (order.get("reasoning") or "")[:500],
        }

        if order_type == "trailing_stop":
            trail_pct = order.get("trail_pct")
            if not trail_pct or trail_pct <= 0:
                continue
            row["trail_pct"] = trail_pct
            # high_water_mark will be set on first price check
        else:
            trigger_price = order.get("trigger_price")
            if not trigger_price or trigger_price <= 0:
                continue
            row["trigger_price"] = trigger_price

        try:
            result = db.table("conditional_orders").insert(row).execute()
            if result.data:
                saved.append(result.data[0])
        except Exception as e:
            logger.error("Failed to save conditional order: %s", e)

    return saved


# ---------------------------------------------------------------------------
# Check triggers and execute
# ---------------------------------------------------------------------------

async def check_and_execute_orders() -> dict:
    """Main subagent loop body: check all pending orders against live prices.

    Returns summary of actions taken.
    """
    db = get_supabase_admin()

    # Fetch all pending orders
    pending = (
        db.table("conditional_orders")
        .select("*")
        .eq("status", "pending")
        .execute()
    )

    if not pending.data:
        return {"checked": 0, "triggered": 0, "expired": 0}

    orders = pending.data
    now = datetime.now(timezone.utc)

    # Expire old orders first
    expired_count = 0
    active_orders = []
    for order in orders:
        expires_at = datetime.fromisoformat(order["expires_at"].replace("Z", "+00:00"))
        if now >= expires_at:
            _mark_status(db, order["id"], "expired")
            expired_count += 1
        else:
            active_orders.append(order)

    if not active_orders:
        return {"checked": 0, "triggered": 0, "expired": expired_count}

    # Collect unique symbols and batch-fetch prices
    unique_symbols = list({(o["symbol"], o["asset_type"]) for o in active_orders})
    symbols = await get_batch_quotes(unique_symbols)

    # Check each order
    triggered_count = 0
    for order in active_orders:
        price = symbols.get((order["symbol"], order["asset_type"]))
        if price is None:
            continue  # Couldn't get quote, skip this cycle

        triggered = _check_trigger(db, order, price)
        if triggered:
            success = await _execute_order(db, order, price)
            if success:
                triggered_count += 1
                # Cancel sibling orders on same symbol/user
                _cancel_siblings(db, order)

    return {
        "checked": len(active_orders),
        "triggered": triggered_count,
        "expired": expired_count,
    }


def _check_trigger(db, order: dict, current_price: float) -> bool:
    """Check if an order's trigger condition is met. Returns True if triggered."""
    order_type = order["order_type"]

    if order_type == "limit_buy":
        # Buy when price drops to or below target
        return current_price <= float(order["trigger_price"])

    elif order_type == "stop_loss":
        # Sell when price drops to or below target
        return current_price <= float(order["trigger_price"])

    elif order_type == "take_profit":
        # Sell when price rises to or above target
        return current_price >= float(order["trigger_price"])

    elif order_type == "trailing_stop":
        trail_pct = float(order["trail_pct"])
        hwm = float(order["high_water_mark"]) if order.get("high_water_mark") else None

        if hwm is None or current_price > hwm:
            # Update high water mark
            new_hwm = current_price
            db.table("conditional_orders").update(
                {"high_water_mark": new_hwm}
            ).eq("id", order["id"]).execute()

            if hwm is None:
                return False  # First check — just set HWM, don't trigger
            hwm = new_hwm

        # Trigger if price dropped trail_pct% from high water mark
        trigger_level = hwm * (1 - trail_pct / 100)
        return current_price <= trigger_level

    return False


async def _execute_order(db, order: dict, current_price: float) -> bool:
    """Execute a triggered conditional order. Uses the same DB logic as ai_trader."""
    order_id = order["id"]
    user_id = order["user_id"]
    symbol = order["symbol"]
    asset_type = order["asset_type"]
    side = order["side"]
    quantity = float(order["quantity"])

    # Mark as triggered first (double-execution prevention)
    db.table("conditional_orders").update({
        "status": "triggered",
        "triggered_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", order_id).eq("status", "pending").execute()

    try:
        # Get profile for cash balance
        profile = db.table("profiles").select("cash_balance").eq("id", user_id).single().execute()
        cash = float(profile.data["cash_balance"])

        if asset_type == "stock":
            quantity = int(quantity)

        total = round(current_price * quantity, 8)

        if side == "buy":
            if total > cash:
                _mark_status(db, order_id, "failed")
                logger.warning("Conditional order %s failed: insufficient funds ($%.2f need $%.2f)", order_id, cash, total)
                return False

            # Deduct cash
            db.table("profiles").update(
                {"cash_balance": cash - total}
            ).eq("id", user_id).execute()

            # Update or create position
            pos_resp = db.table("positions").select("*").eq("user_id", user_id).eq("symbol", symbol).execute()
            if pos_resp.data:
                existing = pos_resp.data[0]
                old_qty = float(existing["quantity"])
                old_cost = float(existing["avg_cost_basis"])
                new_qty = old_qty + quantity
                new_avg = ((old_qty * old_cost) + (quantity * current_price)) / new_qty
                db.table("positions").update(
                    {"quantity": new_qty, "avg_cost_basis": round(new_avg, 8)}
                ).eq("id", existing["id"]).execute()
            else:
                db.table("positions").insert({
                    "user_id": user_id,
                    "symbol": symbol,
                    "asset_type": asset_type,
                    "quantity": quantity,
                    "avg_cost_basis": current_price,
                }).execute()

        elif side == "sell":
            pos_resp = db.table("positions").select("*").eq("user_id", user_id).eq("symbol", symbol).execute()
            if not pos_resp.data:
                _mark_status(db, order_id, "failed")
                logger.warning("Conditional order %s failed: no position in %s", order_id, symbol)
                return False

            existing = pos_resp.data[0]
            held = float(existing["quantity"])
            if quantity > held:
                quantity = held  # Sell what we have

            total = round(current_price * quantity, 8)
            db.table("profiles").update(
                {"cash_balance": cash + total}
            ).eq("id", user_id).execute()

            new_qty = held - quantity
            if new_qty == 0:
                db.table("positions").delete().eq("id", existing["id"]).execute()
            else:
                db.table("positions").update(
                    {"quantity": new_qty}
                ).eq("id", existing["id"]).execute()

        # Record transaction with conditional order tag
        order_type = order["order_type"].upper()
        reasoning = f"[CONDITIONAL {order_type}] {order.get('reasoning', '')}"
        tx_data = {
            "user_id": user_id,
            "symbol": symbol,
            "asset_type": asset_type,
            "side": side,
            "quantity": quantity,
            "price": current_price,
            "total": total,
            "reasoning": reasoning[:500],
        }
        db.table("transactions").insert(tx_data).execute()

        # Mark executed
        db.table("conditional_orders").update({
            "status": "executed",
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "execution_price": current_price,
        }).eq("id", order_id).execute()

        logger.info(
            "Conditional %s executed: %s %s %.4f %s @ $%.2f",
            order_type, side, symbol, quantity, asset_type, current_price,
        )
        return True

    except Exception as e:
        logger.error("Conditional order %s execution failed: %s", order_id, e)
        _mark_status(db, order_id, "failed")
        return False


def _cancel_siblings(db, executed_order: dict):
    """Cancel other pending orders on the same symbol/user.

    E.g. if stop_loss triggers, cancel the take_profit on the same position.
    """
    user_id = executed_order["user_id"]
    symbol = executed_order["symbol"]
    order_id = executed_order["id"]

    siblings = (
        db.table("conditional_orders")
        .select("id, order_type")
        .eq("user_id", user_id)
        .eq("symbol", symbol)
        .eq("status", "pending")
        .neq("id", order_id)
        .execute()
    )

    for sib in siblings.data:
        db.table("conditional_orders").update(
            {"status": "cancelled"}
        ).eq("id", sib["id"]).execute()
        logger.info("Cancelled sibling %s order %s on %s", sib["order_type"], sib["id"], symbol)


def _mark_status(db, order_id: str, status: str):
    """Helper to update order status."""
    db.table("conditional_orders").update(
        {"status": status}
    ).eq("id", order_id).execute()


# ---------------------------------------------------------------------------
# Query helpers (for RAG context + API)
# ---------------------------------------------------------------------------

def get_pending_orders(user_id: str) -> list[dict]:
    """Get all pending conditional orders for a user."""
    db = get_supabase_admin()
    result = (
        db.table("conditional_orders")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "pending")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


def get_recent_triggered_orders(user_id: str, limit: int = 10) -> list[dict]:
    """Get recently triggered/executed/expired orders for RAG context."""
    db = get_supabase_admin()
    result = (
        db.table("conditional_orders")
        .select("*")
        .eq("user_id", user_id)
        .in_("status", ["executed", "expired", "failed"])
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


def get_all_orders(user_id: str, status: str | None = None, limit: int = 50) -> list[dict]:
    """Get conditional orders for API endpoint."""
    db = get_supabase_admin()
    query = (
        db.table("conditional_orders")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
    )
    if status:
        query = query.eq("status", status)
    return query.execute().data


def cancel_order(order_id: str, user_id: str) -> bool:
    """Cancel a pending order. Returns True if cancelled."""
    db = get_supabase_admin()
    result = (
        db.table("conditional_orders")
        .update({"status": "cancelled"})
        .eq("id", order_id)
        .eq("user_id", user_id)
        .eq("status", "pending")
        .execute()
    )
    return bool(result.data)
