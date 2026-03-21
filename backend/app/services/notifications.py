"""Notification service: create notifications and check alert rules."""

import logging
from datetime import datetime, timezone

from app.services.supabase_client import get_supabase_admin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Create notifications
# ---------------------------------------------------------------------------

def create_notification(
    user_id: str,
    type: str,
    title: str,
    message: str,
    metadata: dict | None = None,
) -> dict | None:
    """Insert a notification for a user. Returns the row or None on error."""
    db = get_supabase_admin()
    try:
        row = {
            "user_id": user_id,
            "type": type,
            "title": title,
            "message": message,
            "metadata": metadata or {},
        }
        resp = db.table("notifications").insert(row).execute()
        return resp.data[0] if resp.data else None
    except Exception as e:
        logger.error("Failed to create notification for %s: %s", user_id, e)
        return None


def create_bulk_notifications(rows: list[dict]) -> int:
    """Insert multiple notifications at once. Returns count created."""
    if not rows:
        return 0
    db = get_supabase_admin()
    try:
        resp = db.table("notifications").insert(rows).execute()
        return len(resp.data) if resp.data else 0
    except Exception as e:
        logger.error("Failed to bulk-create notifications: %s", e)
        return 0


# ---------------------------------------------------------------------------
# Query notifications
# ---------------------------------------------------------------------------

def get_user_notifications(user_id: str, limit: int = 50, unread_only: bool = False) -> list[dict]:
    db = get_supabase_admin()
    query = (
        db.table("notifications")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
    )
    if unread_only:
        query = query.eq("read", False)
    resp = query.execute()
    return resp.data or []


def get_unread_count(user_id: str) -> int:
    db = get_supabase_admin()
    resp = (
        db.table("notifications")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("read", False)
        .execute()
    )
    return resp.count or 0


def mark_read(user_id: str, notification_ids: list[str]) -> int:
    """Mark specific notifications as read. Returns count updated."""
    if not notification_ids:
        return 0
    db = get_supabase_admin()
    resp = (
        db.table("notifications")
        .update({"read": True})
        .eq("user_id", user_id)
        .in_("id", notification_ids)
        .execute()
    )
    return len(resp.data) if resp.data else 0


def mark_all_read(user_id: str) -> int:
    db = get_supabase_admin()
    resp = (
        db.table("notifications")
        .update({"read": True})
        .eq("user_id", user_id)
        .eq("read", False)
        .execute()
    )
    return len(resp.data) if resp.data else 0


# ---------------------------------------------------------------------------
# Alert rules CRUD
# ---------------------------------------------------------------------------

def get_alert_rules(user_id: str) -> list[dict]:
    db = get_supabase_admin()
    resp = (
        db.table("alert_rules")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data or []


def create_alert_rule(user_id: str, type: str, config: dict) -> dict | None:
    db = get_supabase_admin()
    try:
        resp = (
            db.table("alert_rules")
            .insert({"user_id": user_id, "type": type, "config": config})
            .execute()
        )
        return resp.data[0] if resp.data else None
    except Exception as e:
        logger.error("Failed to create alert rule for %s: %s", user_id, e)
        return None


def update_alert_rule(user_id: str, rule_id: str, updates: dict) -> dict | None:
    db = get_supabase_admin()
    try:
        resp = (
            db.table("alert_rules")
            .update(updates)
            .eq("id", rule_id)
            .eq("user_id", user_id)
            .execute()
        )
        return resp.data[0] if resp.data else None
    except Exception as e:
        logger.error("Failed to update alert rule %s: %s", rule_id, e)
        return None


def delete_alert_rule(user_id: str, rule_id: str) -> bool:
    db = get_supabase_admin()
    try:
        db.table("alert_rules").delete().eq("id", rule_id).eq("user_id", user_id).execute()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Check alert rules and generate notifications
# ---------------------------------------------------------------------------

async def check_price_alerts(prices: dict[str, float]) -> int:
    """Check all active price alerts against current prices.
    prices: dict of "SYMBOL" -> current_price.
    Returns number of notifications created."""
    db = get_supabase_admin()
    now = datetime.now(timezone.utc).isoformat()

    # Get all active price alerts
    resp = (
        db.table("alert_rules")
        .select("*")
        .in_("type", ["price_above", "price_below"])
        .eq("active", True)
        .execute()
    )
    rules = resp.data or []
    if not rules:
        return 0

    notifications = []
    triggered_ids = []

    for rule in rules:
        config = rule.get("config", {})
        symbol = config.get("symbol", "").upper()
        target = config.get("target_price", 0)
        current = prices.get(symbol)

        if current is None:
            continue

        triggered = False
        if rule["type"] == "price_above" and current >= target:
            triggered = True
            title = f"{symbol} hit ${current:,.2f}"
            message = f"{symbol} crossed above your target of ${target:,.2f} (now ${current:,.2f})"
        elif rule["type"] == "price_below" and current <= target:
            triggered = True
            title = f"{symbol} dropped to ${current:,.2f}"
            message = f"{symbol} fell below your target of ${target:,.2f} (now ${current:,.2f})"

        if triggered:
            notifications.append({
                "user_id": rule["user_id"],
                "type": "price_alert",
                "title": title,
                "message": message,
                "metadata": {"symbol": symbol, "target_price": target, "current_price": current},
            })
            triggered_ids.append(rule["id"])

    count = create_bulk_notifications(notifications)

    # Deactivate triggered one-shot price alerts
    if triggered_ids:
        for rule_id in triggered_ids:
            db.table("alert_rules").update(
                {"active": False, "triggered_at": now}
            ).eq("id", rule_id).execute()

    return count


def notify_ai_trades(trading_results: list[dict]) -> int:
    """After AI trading, notify users who follow specific AI traders.
    trading_results: list of results from run_ai_trading().
    Returns number of notifications created."""
    db = get_supabase_admin()

    # Get all active AI follow rules
    resp = (
        db.table("alert_rules")
        .select("*")
        .eq("type", "ai_follow")
        .eq("active", True)
        .execute()
    )
    rules = resp.data or []
    if not rules:
        return 0

    # Build lookup: trader_name -> list of user_ids watching
    watchers: dict[str, list[str]] = {}
    for rule in rules:
        config = rule.get("config", {})
        trader_name = config.get("trader_name", "")
        if trader_name:
            watchers.setdefault(trader_name, []).append(rule["user_id"])

    if not watchers:
        return 0

    notifications = []
    for result in trading_results:
        trader_name = result.get("trader", "")
        if result.get("status") != "ok" or not result.get("trades"):
            continue

        follower_ids = watchers.get(trader_name, [])
        if not follower_ids:
            continue

        trades = result["trades"]
        trade_summary = ", ".join(
            f"{t['side'].upper()} {t.get('quantity', '?')} {t['symbol']}"
            for t in trades[:5]
        )
        title = f"{trader_name} made {len(trades)} trade{'s' if len(trades) != 1 else ''}"
        message = f"{trader_name} just traded: {trade_summary}"

        # Add reasoning from first trade if available
        first_reasoning = trades[0].get("reasoning", "")
        if first_reasoning:
            message += f"\n\nReasoning: {first_reasoning[:200]}"

        for user_id in follower_ids:
            notifications.append({
                "user_id": user_id,
                "type": "ai_trade",
                "title": title,
                "message": message,
                "metadata": {
                    "trader_name": trader_name,
                    "trades": [{"symbol": t["symbol"], "side": t["side"]} for t in trades[:5]],
                },
            })

    return create_bulk_notifications(notifications)


def check_portfolio_alerts(user_id: str, positions: list[dict]) -> int:
    """Check portfolio-level alerts for a user (position P&L thresholds).
    Called after snapshots or when user views portfolio.
    Returns number of notifications created."""
    db = get_supabase_admin()
    now = datetime.now(timezone.utc).isoformat()

    resp = (
        db.table("alert_rules")
        .select("*")
        .eq("user_id", user_id)
        .eq("type", "portfolio_pnl")
        .eq("active", True)
        .execute()
    )
    rules = resp.data or []
    if not rules:
        return 0

    # Build position P&L map
    pnl_by_symbol = {}
    for pos in positions:
        if pos.get("avg_cost_basis") and pos["avg_cost_basis"] > 0:
            pnl_pct = ((pos["current_price"] / pos["avg_cost_basis"]) - 1) * 100
            pnl_by_symbol[pos["symbol"]] = pnl_pct

    notifications = []
    triggered_ids = []

    for rule in rules:
        config = rule.get("config", {})
        symbol = config.get("symbol", "").upper()
        threshold_pct = config.get("threshold_pct", 0)
        direction = config.get("direction", "above")  # "above" or "below"

        pnl = pnl_by_symbol.get(symbol)
        if pnl is None:
            continue

        triggered = False
        if direction == "above" and pnl >= threshold_pct:
            triggered = True
            title = f"{symbol} up {pnl:+.1f}%"
            message = f"Your {symbol} position is up {pnl:+.1f}%, crossing your +{threshold_pct}% alert threshold."
        elif direction == "below" and pnl <= threshold_pct:
            triggered = True
            title = f"{symbol} down {pnl:+.1f}%"
            message = f"Your {symbol} position is down {pnl:+.1f}%, crossing your {threshold_pct}% alert threshold."

        if triggered:
            notifications.append({
                "user_id": user_id,
                "type": "portfolio",
                "title": title,
                "message": message,
                "metadata": {"symbol": symbol, "pnl_pct": round(pnl, 2), "threshold_pct": threshold_pct},
            })
            triggered_ids.append(rule["id"])

    count = create_bulk_notifications(notifications)

    if triggered_ids:
        for rule_id in triggered_ids:
            db.table("alert_rules").update(
                {"active": False, "triggered_at": now}
            ).eq("id", rule_id).execute()

    return count
