"""Performance analytics for AI and human traders.

Computes win rate, Sharpe ratio, max drawdown, realized P&L,
sector exposure, and model/personality comparisons from existing
transaction and snapshot data.
"""

import math
from datetime import date, timedelta

from app.services.supabase_client import get_supabase_admin
from app.services.market_data import STOCK_SECTORS, get_quote


STARTING_BALANCE = 100_000.0
TRADING_DAYS_PER_YEAR = 252


async def get_trader_analytics(trader_id: str) -> dict:
    """Compute full analytics for a single trader."""
    db = get_supabase_admin()

    # Fetch all transactions for this trader
    tx_resp = (
        db.table("transactions")
        .select("symbol, asset_type, side, quantity, price, total, created_at")
        .eq("user_id", trader_id)
        .order("created_at", desc=False)
        .execute()
    )
    transactions = tx_resp.data

    # Fetch snapshots
    snap_resp = (
        db.table("portfolio_snapshots")
        .select("snapshot_date, total_value")
        .eq("user_id", trader_id)
        .order("snapshot_date", desc=False)
        .execute()
    )
    snapshots = snap_resp.data

    # Fetch current positions for sector exposure
    pos_resp = (
        db.table("positions")
        .select("symbol, asset_type, quantity, avg_cost_basis")
        .eq("user_id", trader_id)
        .gt("quantity", 0)
        .execute()
    )
    positions = pos_resp.data

    # Compute all metrics
    trade_metrics = _compute_trade_metrics(transactions)
    risk_metrics = _compute_risk_metrics(snapshots)
    sector_exposure = await _compute_sector_exposure(positions)
    trade_history = _compute_trade_history(transactions)

    return {
        **trade_metrics,
        **risk_metrics,
        "sector_exposure": sector_exposure,
        "trade_history": trade_history,
        "total_snapshots": len(snapshots),
    }


def _compute_trade_metrics(transactions: list[dict]) -> dict:
    """Compute win rate, avg win/loss, realized P&L from transactions."""
    if not transactions:
        return {
            "total_trades": 0,
            "buy_count": 0,
            "sell_count": 0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "largest_win": 0.0,
            "largest_loss": 0.0,
            "total_realized_pnl": 0.0,
            "profit_factor": 0.0,
        }

    buys = [t for t in transactions if t["side"] == "buy"]
    sells = [t for t in transactions if t["side"] == "sell"]

    # Reconstruct avg cost basis at time of each sell by replaying trades
    # {symbol: {"qty": float, "cost_basis": float}}
    positions: dict[str, dict] = {}
    realized_trades: list[float] = []  # P&L per closed trade

    for tx in transactions:
        sym = tx["symbol"]
        qty = float(tx["quantity"])
        price = float(tx["price"])

        if tx["side"] == "buy":
            if sym not in positions:
                positions[sym] = {"qty": 0.0, "cost_basis": 0.0}
            pos = positions[sym]
            total_cost = pos["qty"] * pos["cost_basis"] + qty * price
            pos["qty"] += qty
            pos["cost_basis"] = total_cost / pos["qty"] if pos["qty"] > 0 else 0
        else:  # sell
            pos = positions.get(sym)
            if pos and pos["qty"] > 0:
                pnl = (price - pos["cost_basis"]) * qty
                realized_trades.append(pnl)
                pos["qty"] -= qty
                if pos["qty"] <= 0.001:
                    pos["qty"] = 0
                    pos["cost_basis"] = 0

    wins = [p for p in realized_trades if p > 0]
    losses = [p for p in realized_trades if p < 0]
    total_realized = sum(realized_trades)

    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0

    return {
        "total_trades": len(transactions),
        "buy_count": len(buys),
        "sell_count": len(sells),
        "win_rate": round(len(wins) / len(realized_trades) * 100, 1) if realized_trades else 0.0,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "largest_win": round(max(wins), 2) if wins else 0.0,
        "largest_loss": round(min(losses), 2) if losses else 0.0,
        "total_realized_pnl": round(total_realized, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0,
    }


def _compute_risk_metrics(snapshots: list[dict]) -> dict:
    """Compute Sharpe ratio, max drawdown, volatility from daily snapshots."""
    if len(snapshots) < 2:
        return {
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "max_drawdown_date": None,
            "annualized_volatility": 0.0,
            "current_drawdown_pct": 0.0,
            "total_return_pct": 0.0,
            "daily_returns": [],
        }

    values = [float(s["total_value"]) for s in snapshots]
    dates = [s["snapshot_date"] for s in snapshots]

    # Daily returns
    daily_returns = []
    for i in range(1, len(values)):
        if values[i - 1] > 0:
            daily_returns.append((values[i] - values[i - 1]) / values[i - 1])

    # Total return
    total_return = (values[-1] - STARTING_BALANCE) / STARTING_BALANCE * 100

    # Sharpe ratio (annualized, assuming risk-free rate ~4.5%)
    risk_free_daily = 0.045 / TRADING_DAYS_PER_YEAR
    if daily_returns:
        mean_excess = sum(r - risk_free_daily for r in daily_returns) / len(daily_returns)
        std = _std(daily_returns)
        sharpe = (mean_excess / std * math.sqrt(TRADING_DAYS_PER_YEAR)) if std > 0 else 0.0
    else:
        sharpe = 0.0

    # Annualized volatility
    vol = _std(daily_returns) * math.sqrt(TRADING_DAYS_PER_YEAR) if daily_returns else 0.0

    # Max drawdown
    peak = values[0]
    max_dd = 0.0
    max_dd_date = dates[0]
    current_dd = 0.0
    for i, val in enumerate(values):
        if val > peak:
            peak = val
        dd = (peak - val) / peak * 100
        if dd > max_dd:
            max_dd = dd
            max_dd_date = dates[i]
        if i == len(values) - 1:
            current_dd = dd

    # Return series for chart (last 30 points max)
    chart_returns = []
    for i in range(len(snapshots)):
        ret = (values[i] - STARTING_BALANCE) / STARTING_BALANCE * 100
        chart_returns.append({
            "date": dates[i],
            "total_value": round(values[i], 2),
            "return_pct": round(ret, 2),
        })

    return {
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "max_drawdown_date": max_dd_date,
        "annualized_volatility": round(vol * 100, 2),
        "current_drawdown_pct": round(current_dd, 2),
        "total_return_pct": round(total_return, 2),
        "daily_returns": chart_returns,
    }


async def _compute_sector_exposure(positions: list[dict]) -> list[dict]:
    """Compute sector allocation from current positions."""
    if not positions:
        return []

    sector_values: dict[str, float] = {}
    total_value = 0.0

    for pos in positions:
        qty = float(pos["quantity"])
        # Use avg_cost_basis as fallback (avoids API calls for every position)
        price = float(pos["avg_cost_basis"])
        quote = await get_quote(pos["symbol"], pos["asset_type"])
        if quote:
            price = quote["price"]

        value = qty * price
        total_value += value

        if pos["asset_type"] == "crypto":
            sector = "Crypto"
        else:
            sector = STOCK_SECTORS.get(pos["symbol"], "Other")

        sector_values[sector] = sector_values.get(sector, 0) + value

    if total_value == 0:
        return []

    return sorted(
        [
            {
                "sector": sector,
                "value": round(val, 2),
                "pct": round(val / total_value * 100, 1),
            }
            for sector, val in sector_values.items()
        ],
        key=lambda x: x["pct"],
        reverse=True,
    )


def _compute_trade_history(transactions: list[dict]) -> list[dict]:
    """Aggregate trades by day for activity chart."""
    daily: dict[str, dict] = {}
    for tx in transactions:
        day = tx["created_at"][:10]  # YYYY-MM-DD
        if day not in daily:
            daily[day] = {"date": day, "buys": 0, "sells": 0, "volume": 0.0}
        if tx["side"] == "buy":
            daily[day]["buys"] += 1
        else:
            daily[day]["sells"] += 1
        daily[day]["volume"] += float(tx["total"])

    result = sorted(daily.values(), key=lambda x: x["date"])
    for entry in result:
        entry["volume"] = round(entry["volume"], 2)
    return result


async def get_ai_comparison() -> dict:
    """Compare all AI traders side-by-side."""
    db = get_supabase_admin()

    # Get all AI profiles
    profiles_resp = (
        db.table("profiles")
        .select("id, display_name, ai_model, is_ai")
        .eq("is_ai", True)
        .execute()
    )

    if not profiles_resp.data:
        return {"traders": [], "by_model": {}, "by_personality": {}}

    trader_ids = [p["id"] for p in profiles_resp.data]

    # Batch fetch all transactions
    tx_resp = (
        db.table("transactions")
        .select("user_id, symbol, asset_type, side, quantity, price, total, created_at")
        .in_("user_id", trader_ids)
        .order("created_at", desc=False)
        .execute()
    )

    # Batch fetch all snapshots
    snap_resp = (
        db.table("portfolio_snapshots")
        .select("user_id, snapshot_date, total_value")
        .in_("user_id", trader_ids)
        .order("snapshot_date", desc=False)
        .execute()
    )

    # Group by user
    tx_by_user: dict[str, list] = {}
    for tx in tx_resp.data:
        tx_by_user.setdefault(tx["user_id"], []).append(tx)

    snap_by_user: dict[str, list] = {}
    for s in snap_resp.data:
        snap_by_user.setdefault(s["user_id"], []).append(s)

    # Import personality mapping
    from app.services.ai_trader import PERSONALITIES

    # Compute per-trader
    traders = []
    for profile in profiles_resp.data:
        uid = profile["id"]
        txs = tx_by_user.get(uid, [])
        snaps = snap_by_user.get(uid, [])

        trade_metrics = _compute_trade_metrics(txs)
        risk_metrics = _compute_risk_metrics(snaps)

        # Determine personality
        personality = None
        for pkey, pinfo in PERSONALITIES.items():
            if pinfo["name"] in profile["display_name"]:
                personality = pkey
                break

        traders.append({
            "id": uid,
            "display_name": profile["display_name"],
            "model": profile["ai_model"],
            "personality": personality,
            "win_rate": trade_metrics["win_rate"],
            "total_trades": trade_metrics["total_trades"],
            "total_realized_pnl": trade_metrics["total_realized_pnl"],
            "profit_factor": trade_metrics["profit_factor"],
            "sharpe_ratio": risk_metrics["sharpe_ratio"],
            "max_drawdown_pct": risk_metrics["max_drawdown_pct"],
            "total_return_pct": risk_metrics["total_return_pct"],
            "annualized_volatility": risk_metrics["annualized_volatility"],
        })

    # Aggregate by model
    by_model: dict[str, list] = {}
    for t in traders:
        by_model.setdefault(t["model"], []).append(t)

    model_stats = {}
    for model, group in by_model.items():
        model_stats[model] = _aggregate_group(group)

    # Aggregate by personality
    by_personality: dict[str, list] = {}
    for t in traders:
        if t["personality"]:
            by_personality.setdefault(t["personality"], []).append(t)

    personality_stats = {}
    for personality, group in by_personality.items():
        personality_stats[personality] = _aggregate_group(group)

    return {
        "traders": sorted(traders, key=lambda x: x["total_return_pct"], reverse=True),
        "by_model": model_stats,
        "by_personality": personality_stats,
    }


def _aggregate_group(group: list[dict]) -> dict:
    """Average metrics across a group of traders."""
    n = len(group)
    if n == 0:
        return {}
    return {
        "count": n,
        "avg_win_rate": round(sum(t["win_rate"] for t in group) / n, 1),
        "avg_return_pct": round(sum(t["total_return_pct"] for t in group) / n, 2),
        "avg_sharpe": round(sum(t["sharpe_ratio"] for t in group) / n, 2),
        "avg_max_drawdown": round(sum(t["max_drawdown_pct"] for t in group) / n, 2),
        "avg_profit_factor": round(sum(t["profit_factor"] for t in group) / n, 2),
        "total_trades": sum(t["total_trades"] for t in group),
        "best_trader": max(group, key=lambda t: t["total_return_pct"])["display_name"],
        "worst_trader": min(group, key=lambda t: t["total_return_pct"])["display_name"],
    }


def _std(values: list[float]) -> float:
    """Standard deviation of a list of floats."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)
