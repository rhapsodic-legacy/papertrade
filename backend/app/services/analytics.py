"""Performance analytics for AI and human traders.

Computes win rate, Sharpe ratio, max drawdown, realized P&L,
sector exposure, and model/personality comparisons from existing
transaction and snapshot data.
"""

import math
from datetime import date, timedelta

from app.services.supabase_client import get_supabase_admin, fetch_all_rows
from app.services.market_data import STOCK_SECTORS, get_quote


STARTING_BALANCE = 100_000.0
TRADING_DAYS_PER_YEAR = 252

# Map internal model keys to display labels
MODEL_DISPLAY_LABELS = {
    "gemini-flash": "Mistral Small",
    "gemini-pro": "Mistral Large 2",
    "mistral": "Mistral Large",
    "llama": "Mistral Medium",
    "custom": "Custom (Mistral)",
}


def _model_label(key: str) -> str:
    return MODEL_DISPLAY_LABELS.get(key, key)


def _clean_display_name(name: str) -> str:
    """Replace legacy model names in display names with current model labels."""
    import re
    name = re.sub(r'\(Llama\)', '(Mistral Medium)', name)
    name = re.sub(r'\(llama\)', '(Mistral Medium)', name)
    name = re.sub(r'\(Groq\)', '(Mistral Medium)', name)
    name = re.sub(r'\(GPT\)', '(Mistral Large 2)', name)
    name = re.sub(r'\(Llama 3\.3 70B\)', '(Mistral Medium)', name)
    name = re.sub(r'\(Llama 3\.1 8B\)', '(Mistral Small)', name)
    name = re.sub(r'\(GPT-OSS 120B\)', '(Mistral Large 2)', name)
    return name


# With 5k+ AI trades, any unbounded .execute() reads only the oldest 1000
# rows — every full-history fetch in this module must paginate.
_fetch_all_rows = fetch_all_rows


async def get_trader_analytics(trader_id: str) -> dict:
    """Compute full analytics for a single trader."""
    db = get_supabase_admin()

    # Fetch all transactions for this trader
    transactions = _fetch_all_rows(
        db.table("transactions")
        .select("symbol, asset_type, side, quantity, price, total, created_at")
        .eq("user_id", trader_id)
        .order("created_at", desc=False)
    )

    # Fetch snapshots
    snapshots = _fetch_all_rows(
        db.table("portfolio_snapshots")
        .select("snapshot_date, total_value")
        .eq("user_id", trader_id)
        .order("snapshot_date", desc=False)
    )

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
            "sortino_ratio": 0.0,
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

    # Sortino ratio (only penalizes downside volatility)
    if daily_returns:
        downside = [min(r - risk_free_daily, 0) for r in daily_returns]
        downside_std = math.sqrt(sum(d ** 2 for d in downside) / len(downside))
        sortino = (mean_excess / downside_std * math.sqrt(TRADING_DAYS_PER_YEAR)) if downside_std > 0 else 0.0
    else:
        sortino = 0.0

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
        "sortino_ratio": round(sortino, 2),
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
    tx_rows = _fetch_all_rows(
        db.table("transactions")
        .select("user_id, symbol, asset_type, side, quantity, price, total, created_at")
        .in_("user_id", trader_ids)
        .order("created_at", desc=False)
    )

    # Batch fetch all snapshots
    snap_rows = _fetch_all_rows(
        db.table("portfolio_snapshots")
        .select("user_id, snapshot_date, total_value")
        .in_("user_id", trader_ids)
        .order("snapshot_date", desc=False)
    )

    # Group by user
    tx_by_user: dict[str, list] = {}
    for tx in tx_rows:
        tx_by_user.setdefault(tx["user_id"], []).append(tx)

    snap_by_user: dict[str, list] = {}
    for s in snap_rows:
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
            "display_name": _clean_display_name(profile["display_name"]),
            "model": _model_label(profile["ai_model"]),
            "personality": personality,
            "win_rate": trade_metrics["win_rate"],
            "total_trades": trade_metrics["total_trades"],
            "total_realized_pnl": trade_metrics["total_realized_pnl"],
            "profit_factor": trade_metrics["profit_factor"],
            "sharpe_ratio": risk_metrics["sharpe_ratio"],
            "sortino_ratio": risk_metrics["sortino_ratio"],
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


async def get_model_deep_dive(days: int = 7) -> dict:
    """Compare model performance over a recent window, eliminating duration bias.

    Uses snapshots to compute return over the last N days — so all models
    are measured over the same calendar period regardless of when they
    started trading.  Also computes per-model trade quality metrics
    (win rate, avg P&L per sell, trade frequency) over that window.
    """
    db = get_supabase_admin()
    from app.services.ai_trader import PERSONALITIES

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    today_str = date.today().isoformat()

    # AI profiles
    profiles_resp = (
        db.table("profiles")
        .select("id, display_name, ai_model, is_ai")
        .eq("is_ai", True)
        .execute()
    )
    if not profiles_resp.data:
        return {"error": "No AI traders found"}

    trader_ids = [p["id"] for p in profiles_resp.data]

    # Snapshots in the window
    snap_rows = _fetch_all_rows(
        db.table("portfolio_snapshots")
        .select("user_id, snapshot_date, total_value")
        .in_("user_id", trader_ids)
        .gte("snapshot_date", cutoff)
        .order("snapshot_date", desc=False)
    )

    snap_by_user: dict[str, list] = {}
    for s in snap_rows:
        snap_by_user.setdefault(s["user_id"], []).append(s)

    # Trades in the window
    tx_rows = _fetch_all_rows(
        db.table("transactions")
        .select("user_id, symbol, asset_type, side, quantity, price, total, created_at, reasoning")
        .in_("user_id", trader_ids)
        .gte("created_at", f"{cutoff}T00:00:00")
        .order("created_at", desc=False)
    )

    tx_by_user: dict[str, list] = {}
    for tx in tx_rows:
        tx_by_user.setdefault(tx["user_id"], []).append(tx)

    # Build per-trader results
    traders = []
    for profile in profiles_resp.data:
        uid = profile["id"]
        snaps = snap_by_user.get(uid, [])
        txs = tx_by_user.get(uid, [])

        # Window return from snapshots
        if len(snaps) >= 2:
            start_val = snaps[0]["total_value"]
            end_val = snaps[-1]["total_value"]
            window_return = ((end_val / start_val) - 1) * 100 if start_val else 0
        elif len(snaps) == 1:
            window_return = ((snaps[0]["total_value"] / STARTING_BALANCE) - 1) * 100
        else:
            window_return = 0

        # Trade metrics in window
        buys = [t for t in txs if t["side"] == "buy"]
        sells = [t for t in txs if t["side"] == "sell"]
        sell_pnls = _match_sell_pnl(txs)

        wins = [p for p in sell_pnls if p > 0]
        losses = [p for p in sell_pnls if p <= 0]
        win_rate = len(wins) / len(sell_pnls) * 100 if sell_pnls else 0
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0

        # Reasoning quality
        reasoning_lens = [len(t.get("reasoning", "") or "") for t in txs]
        avg_reasoning_len = sum(reasoning_lens) / len(reasoning_lens) if reasoning_lens else 0

        personality = None
        for pkey, pinfo in PERSONALITIES.items():
            if pinfo["name"] in profile["display_name"]:
                personality = pkey
                break

        if not personality and profile.get("ai_model") == "custom":
            personality = "custom"

        traders.append({
            "id": uid,
            "display_name": _clean_display_name(profile["display_name"]),
            "model": _model_label(profile["ai_model"]),
            "model_key": profile["ai_model"],
            "personality": personality,
            "window_return_pct": round(window_return, 2),
            "window_buys": len(buys),
            "window_sells": len(sells),
            "window_win_rate": round(win_rate, 1),
            "window_avg_win": round(avg_win, 2),
            "window_avg_loss": round(avg_loss, 2),
            "avg_reasoning_len": round(avg_reasoning_len),
            "snapshot_count": len(snaps),
        })

    # Aggregate by model
    by_model: dict[str, list] = {}
    for t in traders:
        by_model.setdefault(t["model"], []).append(t)

    model_stats = {}
    for model, group in by_model.items():
        n = len(group)
        total_trades = sum(t["window_buys"] + t["window_sells"] for t in group)
        model_stats[model] = {
            "count": n,
            "avg_window_return": round(sum(t["window_return_pct"] for t in group) / n, 2),
            "avg_win_rate": round(sum(t["window_win_rate"] for t in group) / n, 1),
            "total_trades": total_trades,
            "avg_trades_per_trader": round(total_trades / n, 1),
            "avg_reasoning_len": round(sum(t["avg_reasoning_len"] for t in group) / n),
            "best": max(group, key=lambda t: t["window_return_pct"])["display_name"],
            "worst": min(group, key=lambda t: t["window_return_pct"])["display_name"],
        }

    # Aggregate by personality
    by_pers: dict[str, list] = {}
    for t in traders:
        if t["personality"]:
            by_pers.setdefault(t["personality"], []).append(t)

    pers_stats = {}
    for pers, group in by_pers.items():
        n = len(group)
        pers_stats[pers] = {
            "count": n,
            "avg_window_return": round(sum(t["window_return_pct"] for t in group) / n, 2),
            "avg_win_rate": round(sum(t["window_win_rate"] for t in group) / n, 1),
            "total_trades": sum(t["window_buys"] + t["window_sells"] for t in group),
        }

    return {
        "window_days": days,
        "start_date": cutoff,
        "end_date": today_str,
        "traders": sorted(traders, key=lambda x: x["window_return_pct"], reverse=True),
        "by_model": model_stats,
        "by_personality": pers_stats,
    }


def _match_sell_pnl(txs: list[dict]) -> list[float]:
    """Simple FIFO P&L matching for sells within a transaction list."""
    # Track cost basis per symbol
    holdings: dict[str, list[tuple[float, float]]] = {}  # symbol -> [(qty, price)]
    pnls = []

    for tx in txs:
        sym = tx["symbol"]
        qty = tx["quantity"]
        price = tx["price"]

        if tx["side"] == "buy":
            holdings.setdefault(sym, []).append((qty, price))
        elif tx["side"] == "sell" and sym in holdings:
            remaining = qty
            cost = 0.0
            matched = 0.0
            lots = holdings[sym]
            while remaining > 0 and lots:
                lot_qty, lot_price = lots[0]
                take = min(remaining, lot_qty)
                cost += take * lot_price
                matched += take
                remaining -= take
                if take >= lot_qty:
                    lots.pop(0)
                else:
                    lots[0] = (lot_qty - take, lot_price)
            if matched > 0:
                revenue = matched * price
                pnl_pct = ((revenue / cost) - 1) * 100
                pnls.append(pnl_pct)

    return pnls


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
        "avg_sortino": round(sum(t.get("sortino_ratio", 0) for t in group) / n, 2),
        "avg_max_drawdown": round(sum(t["max_drawdown_pct"] for t in group) / n, 2),
        "avg_profit_factor": round(sum(t["profit_factor"] for t in group) / n, 2),
        "total_trades": sum(t["total_trades"] for t in group),
        "best_trader": max(group, key=lambda t: t["total_return_pct"])["display_name"],
        "worst_trader": min(group, key=lambda t: t["total_return_pct"])["display_name"],
    }


async def get_portfolio_health(user_id: str) -> dict:
    """Compute portfolio health score for a human trader, with AI comparison."""
    db = get_supabase_admin()

    tx_resp = (
        db.table("transactions")
        .select("symbol, asset_type, side, quantity, price, total, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=False)
        .execute()
    )
    snap_resp = (
        db.table("portfolio_snapshots")
        .select("snapshot_date, total_value")
        .eq("user_id", user_id)
        .order("snapshot_date", desc=False)
        .execute()
    )
    pos_resp = (
        db.table("positions")
        .select("symbol, asset_type, quantity, avg_cost_basis")
        .eq("user_id", user_id)
        .gt("quantity", 0)
        .execute()
    )

    trade_metrics = _compute_trade_metrics(tx_resp.data)
    risk_metrics = _compute_risk_metrics(snap_resp.data)
    sector_exposure = await _compute_sector_exposure(pos_resp.data)
    trade_history = _compute_trade_history(tx_resp.data)

    score, grade, breakdown = _compute_health_score(
        trade_metrics, risk_metrics, sector_exposure, len(snap_resp.data)
    )

    ai_comparison = await _get_ai_averages()
    ai_rank = _compute_ai_rank(
        risk_metrics["total_return_pct"], ai_comparison.get("all_returns", [])
    )

    return {
        "score": score,
        "grade": grade,
        "score_breakdown": breakdown,
        "metrics": {
            **trade_metrics,
            **risk_metrics,
            "sector_exposure": sector_exposure,
            "trade_history": trade_history,
            "total_snapshots": len(snap_resp.data),
        },
        "ai_comparison": {
            "avg_return_pct": ai_comparison.get("avg_return_pct", 0),
            "avg_sharpe": ai_comparison.get("avg_sharpe", 0),
            "avg_win_rate": ai_comparison.get("avg_win_rate", 0),
            "avg_max_drawdown": ai_comparison.get("avg_max_drawdown", 0),
            "avg_profit_factor": ai_comparison.get("avg_profit_factor", 0),
            "total_ai_traders": ai_comparison.get("total_ai_traders", 0),
            "user_beats_n": ai_rank["beats"],
            "user_rank": ai_rank["rank"],
        },
    }


def _compute_health_score(
    trade_metrics: dict,
    risk_metrics: dict,
    sector_exposure: list[dict],
    total_snapshots: int,
) -> tuple[int, str, list[dict]]:
    """Compute a 0-100 portfolio health score with letter grade.

    Components (each 0-20):
    1. Diversification — sector spread
    2. Risk management — drawdown, volatility
    3. Trading discipline — win rate, profit factor, sell ratio
    4. Returns — total return
    5. Activity — trading frequency
    """
    breakdown = []

    # 1. Diversification (0-20)
    n_sectors = len(sector_exposure)
    max_sector_pct = sector_exposure[0]["pct"] if sector_exposure else 100
    div_score = 0
    if n_sectors >= 5:
        div_score += 10
    elif n_sectors >= 3:
        div_score += 7
    elif n_sectors >= 1:
        div_score += 3
    if max_sector_pct <= 30:
        div_score += 10
    elif max_sector_pct <= 50:
        div_score += 6
    elif max_sector_pct <= 70:
        div_score += 3
    div_score = min(div_score, 20)
    breakdown.append({
        "name": "Diversification",
        "score": div_score,
        "max": 20,
        "tip": "Spread across 5+ sectors, no single sector >30%"
            if div_score < 15
            else "Well diversified across sectors",
    })

    # 2. Risk management (0-20)
    max_dd = risk_metrics.get("max_drawdown_pct", 0)
    vol = risk_metrics.get("annualized_volatility", 0)
    risk_score = 20
    if max_dd > 20:
        risk_score -= 10
    elif max_dd > 10:
        risk_score -= 5
    elif max_dd > 5:
        risk_score -= 2
    if vol > 40:
        risk_score -= 8
    elif vol > 25:
        risk_score -= 4
    elif vol > 15:
        risk_score -= 1
    risk_score = max(risk_score, 0)
    breakdown.append({
        "name": "Risk Management",
        "score": risk_score,
        "max": 20,
        "tip": "Keep max drawdown <10% and volatility <25%"
            if risk_score < 15
            else "Solid risk control",
    })

    # 3. Trading discipline (0-20)
    win_rate = trade_metrics.get("win_rate", 0)
    profit_factor = trade_metrics.get("profit_factor", 0)
    sell_count = trade_metrics.get("sell_count", 0)
    buy_count = trade_metrics.get("buy_count", 0)
    disc_score = 0
    if win_rate >= 55:
        disc_score += 7
    elif win_rate >= 45:
        disc_score += 5
    elif win_rate > 0:
        disc_score += 2
    if profit_factor >= 1.5:
        disc_score += 7
    elif profit_factor >= 1.0:
        disc_score += 5
    elif profit_factor > 0:
        disc_score += 2
    if buy_count > 0 and sell_count > 0:
        sell_ratio = sell_count / buy_count
        if sell_ratio >= 0.3:
            disc_score += 6
        elif sell_ratio >= 0.1:
            disc_score += 3
    disc_score = min(disc_score, 20)
    breakdown.append({
        "name": "Trading Discipline",
        "score": disc_score,
        "max": 20,
        "tip": "Take profits and cut losses — aim for >50% win rate"
            if disc_score < 15
            else "Strong buy/sell discipline",
    })

    # 4. Returns (0-20)
    total_return = risk_metrics.get("total_return_pct", 0)
    if total_return > 10:
        ret_score = 20
    elif total_return > 5:
        ret_score = 16
    elif total_return > 0:
        ret_score = 12
    elif total_return > -5:
        ret_score = 8
    elif total_return > -10:
        ret_score = 4
    else:
        ret_score = 0
    breakdown.append({
        "name": "Returns",
        "score": ret_score,
        "max": 20,
        "tip": "Aim for positive returns first, then beat the AI average"
            if ret_score < 15
            else "Strong returns",
    })

    # 5. Activity (0-20)
    total_trades = trade_metrics.get("total_trades", 0)
    act_score = 0
    if total_trades >= 20:
        act_score += 10
    elif total_trades >= 10:
        act_score += 7
    elif total_trades >= 3:
        act_score += 4
    elif total_trades >= 1:
        act_score += 2
    if total_trades > 0 and total_snapshots > 0:
        trades_per_day = total_trades / max(total_snapshots, 1)
        if trades_per_day >= 0.5:
            act_score += 10
        elif trades_per_day >= 0.2:
            act_score += 6
        elif trades_per_day > 0:
            act_score += 3
    act_score = min(act_score, 20)
    breakdown.append({
        "name": "Activity",
        "score": act_score,
        "max": 20,
        "tip": "Trade regularly — a few trades per week helps you learn"
            if act_score < 15
            else "Consistently active",
    })

    total_score = sum(b["score"] for b in breakdown)

    if total_score >= 90:
        grade = "A+"
    elif total_score >= 80:
        grade = "A"
    elif total_score >= 70:
        grade = "B+"
    elif total_score >= 60:
        grade = "B"
    elif total_score >= 50:
        grade = "C+"
    elif total_score >= 40:
        grade = "C"
    elif total_score >= 30:
        grade = "D"
    else:
        grade = "F"

    return total_score, grade, breakdown


async def _get_ai_averages() -> dict:
    """Compute average metrics across all AI traders for comparison."""
    db = get_supabase_admin()
    profiles_resp = (
        db.table("profiles").select("id").eq("is_ai", True).execute()
    )
    if not profiles_resp.data:
        return {"total_ai_traders": 0, "all_returns": []}

    trader_ids = [p["id"] for p in profiles_resp.data]

    tx_rows = _fetch_all_rows(
        db.table("transactions")
        .select("user_id, symbol, side, quantity, price")
        .in_("user_id", trader_ids)
        .order("created_at", desc=False)
    )
    snap_rows = _fetch_all_rows(
        db.table("portfolio_snapshots")
        .select("user_id, snapshot_date, total_value")
        .in_("user_id", trader_ids)
        .order("snapshot_date", desc=False)
    )

    tx_by_user: dict[str, list] = {}
    for tx in tx_rows:
        tx_by_user.setdefault(tx["user_id"], []).append(tx)
    snap_by_user: dict[str, list] = {}
    for s in snap_rows:
        snap_by_user.setdefault(s["user_id"], []).append(s)

    returns, sharpes, win_rates, drawdowns, profit_factors = [], [], [], [], []
    for uid in trader_ids:
        tm = _compute_trade_metrics(tx_by_user.get(uid, []))
        rm = _compute_risk_metrics(snap_by_user.get(uid, []))
        returns.append(rm["total_return_pct"])
        sharpes.append(rm["sharpe_ratio"])
        win_rates.append(tm["win_rate"])
        drawdowns.append(rm["max_drawdown_pct"])
        profit_factors.append(tm["profit_factor"])

    n = len(trader_ids)
    return {
        "total_ai_traders": n,
        "avg_return_pct": round(sum(returns) / n, 2) if n else 0,
        "avg_sharpe": round(sum(sharpes) / n, 2) if n else 0,
        "avg_win_rate": round(sum(win_rates) / n, 1) if n else 0,
        "avg_max_drawdown": round(sum(drawdowns) / n, 2) if n else 0,
        "avg_profit_factor": round(sum(profit_factors) / n, 2) if n else 0,
        "all_returns": sorted(returns, reverse=True),
    }


def _compute_ai_rank(user_return: float, ai_returns: list[float]) -> dict:
    """Where does the user rank among AI trader returns."""
    if not ai_returns:
        return {"rank": 0, "beats": 0}
    beats = sum(1 for r in ai_returns if user_return > r)
    rank = sum(1 for r in ai_returns if r > user_return) + 1
    return {"rank": rank, "beats": beats}


async def get_reflection_trends(trader_id: str | None = None) -> dict:
    """Track reflection outcome scores over time to measure learning.

    Returns weekly averages of outcome_score per trader/personality,
    showing whether trade quality is improving over time.
    """
    db = get_supabase_admin()

    query = (
        db.table("trade_reflections")
        .select("user_id, symbol, side, outcome_score, reflection_text, lessons, reflected_at")
        .order("reflected_at", desc=False)
    )
    if trader_id:
        query = query.eq("user_id", trader_id)

    reflection_rows = _fetch_all_rows(query)
    if not reflection_rows:
        return {"trends": [], "by_trader": {}, "summary": {}}

    # Get personality mapping
    user_ids = list({r["user_id"] for r in reflection_rows})
    profiles_resp = (
        db.table("profiles")
        .select("id, display_name, ai_model, is_ai")
        .in_("id", user_ids)
        .execute()
    )

    from app.services.ai_trader import PERSONALITIES

    profile_map = {}
    for p in profiles_resp.data:
        personality = None
        for pkey, pinfo in PERSONALITIES.items():
            if pinfo["name"] in p["display_name"]:
                personality = pkey
                break
        profile_map[p["id"]] = {
            "display_name": _clean_display_name(p["display_name"]),
            "personality": personality,
        }

    # Group by week for trend
    from datetime import datetime
    weekly: dict[str, list[float]] = {}  # "YYYY-WW" -> scores
    by_trader: dict[str, list[dict]] = {}  # user_id -> reflections

    for r in reflection_rows:
        score = float(r["outcome_score"])
        ref_date = r["reflected_at"][:10]

        # Week key
        dt = datetime.strptime(ref_date, "%Y-%m-%d")
        week_key = f"{dt.year}-W{dt.isocalendar()[1]:02d}"
        weekly.setdefault(week_key, []).append(score)

        # Per trader
        uid = r["user_id"]
        by_trader.setdefault(uid, []).append(score)

    # Weekly trend
    trends = []
    for week, scores in sorted(weekly.items()):
        avg = sum(scores) / len(scores)
        trends.append({
            "week": week,
            "avg_score": round(avg, 3),
            "count": len(scores),
            "positive_pct": round(sum(1 for s in scores if s > 0) / len(scores) * 100, 1),
        })

    # Per trader summary
    trader_summaries = {}
    for uid, scores in by_trader.items():
        info = profile_map.get(uid, {"display_name": "Unknown", "personality": None})
        avg = sum(scores) / len(scores)
        # Split into first half / second half to check improvement
        mid = len(scores) // 2
        first_half_avg = sum(scores[:mid]) / mid if mid > 0 else 0
        second_half_avg = sum(scores[mid:]) / (len(scores) - mid) if len(scores) - mid > 0 else 0

        trader_summaries[uid] = {
            "display_name": info["display_name"],
            "personality": info["personality"],
            "total_reflections": len(scores),
            "avg_score": round(avg, 3),
            "positive_pct": round(sum(1 for s in scores if s > 0) / len(scores) * 100, 1),
            "first_half_avg": round(first_half_avg, 3),
            "second_half_avg": round(second_half_avg, 3),
            "improving": second_half_avg > first_half_avg if mid > 0 else None,
        }

    # Overall summary
    all_scores = [float(r["outcome_score"]) for r in reflection_rows]
    improving_count = sum(1 for t in trader_summaries.values() if t.get("improving") is True)
    total_with_data = sum(1 for t in trader_summaries.values() if t.get("improving") is not None)

    return {
        "trends": trends,
        "by_trader": trader_summaries,
        "summary": {
            "total_reflections": len(all_scores),
            "avg_outcome_score": round(sum(all_scores) / len(all_scores), 3),
            "positive_pct": round(sum(1 for s in all_scores if s > 0) / len(all_scores) * 100, 1),
            "traders_improving": improving_count,
            "traders_with_data": total_with_data,
        },
    }


async def get_module_attribution(trader_id: str | None = None, cite_days: int = 14) -> dict:
    """Compute win rate and P&L broken down by which toolkit modules were active.

    If trader_id is provided, scopes to one trader. Otherwise, all AI traders.
    Uses the modules_used JSON field on transactions to attribute outcomes.

    Also computes a recent cite-rate per module (last cite_days days): of the
    trades made by traders whose toolkit includes the module, what fraction
    actually cited it? Modules stuck near zero are surfaced in low_adoption —
    cross_asset sat at 0 citations for two pipeline runs before anyone noticed
    because uncited modules never appeared in this report at all.
    """
    import json

    db = get_supabase_admin()

    profiles_query = db.table("profiles").select("id, display_name")
    if trader_id:
        profiles_query = profiles_query.eq("id", trader_id)
    else:
        profiles_query = profiles_query.eq("is_ai", True)
    profiles_resp = profiles_query.execute()
    trader_ids = [p["id"] for p in profiles_resp.data]

    if not trader_ids:
        return {"modules": {}, "total_trades_analyzed": 0}

    tx_rows = _fetch_all_rows(
        db.table("transactions")
        .select("user_id, symbol, asset_type, side, quantity, price, total, created_at, modules_used")
        .in_("user_id", trader_ids)
        .order("created_at", desc=False)
    )

    if not tx_rows:
        return {"modules": {}, "total_trades_analyzed": 0}

    # Replay positions to compute per-sell P&L, then attribute to modules
    positions: dict[str, dict[str, dict]] = {}  # user_id -> symbol -> {qty, cost_basis}
    # Each sell gets: pnl, modules list
    sell_records: list[dict] = []

    for tx in tx_rows:
        uid = tx["user_id"]
        sym = tx["symbol"]
        qty = float(tx["quantity"])
        price = float(tx["price"])

        if uid not in positions:
            positions[uid] = {}

        if tx["side"] == "buy":
            if sym not in positions[uid]:
                positions[uid][sym] = {"qty": 0.0, "cost_basis": 0.0}
            pos = positions[uid][sym]
            total_cost = pos["qty"] * pos["cost_basis"] + qty * price
            pos["qty"] += qty
            pos["cost_basis"] = total_cost / pos["qty"] if pos["qty"] > 0 else 0
        else:
            pos = positions[uid].get(sym)
            if pos and pos["qty"] > 0:
                pnl = (price - pos["cost_basis"]) * qty
                # Parse modules from the sell transaction
                modules = []
                if tx.get("modules_used"):
                    try:
                        modules = json.loads(tx["modules_used"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                sell_records.append({"pnl": pnl, "modules": modules})
                pos["qty"] -= qty
                if pos["qty"] <= 0.001:
                    pos["qty"] = 0
                    pos["cost_basis"] = 0

    # Also attribute buy decisions (did the module lead to good entries?)
    # Track buys with their modules for entry quality analysis
    buy_records: list[dict] = []
    positions2: dict[str, dict[str, dict]] = {}
    for tx in tx_rows:
        uid = tx["user_id"]
        sym = tx["symbol"]
        qty = float(tx["quantity"])
        price = float(tx["price"])

        if uid not in positions2:
            positions2[uid] = {}

        if tx["side"] == "buy":
            modules = []
            if tx.get("modules_used"):
                try:
                    modules = json.loads(tx["modules_used"])
                except (json.JSONDecodeError, TypeError):
                    pass
            if sym not in positions2[uid]:
                positions2[uid][sym] = {"qty": 0.0, "cost_basis": 0.0, "buy_modules": modules}
            pos = positions2[uid][sym]
            total_cost = pos["qty"] * pos["cost_basis"] + qty * price
            pos["qty"] += qty
            pos["cost_basis"] = total_cost / pos["qty"] if pos["qty"] > 0 else 0
            pos["buy_modules"] = modules  # latest buy's modules
        else:
            pos = positions2[uid].get(sym)
            if pos and pos["qty"] > 0:
                pnl = (price - pos["cost_basis"]) * qty
                buy_records.append({"pnl": pnl, "modules": pos.get("buy_modules", [])})
                pos["qty"] -= qty
                if pos["qty"] <= 0.001:
                    pos["qty"] = 0
                    pos["cost_basis"] = 0

    # Aggregate by module
    module_stats: dict[str, dict] = {}

    def _add_record(records: list[dict], prefix: str) -> None:
        for rec in records:
            for mod in rec["modules"]:
                if mod not in module_stats:
                    module_stats[mod] = {
                        "sell_wins": 0, "sell_losses": 0, "sell_total_pnl": 0.0,
                        "buy_wins": 0, "buy_losses": 0, "buy_total_pnl": 0.0,
                        "total_trades": 0,
                    }
                stats = module_stats[mod]
                stats["total_trades"] += 1
                if rec["pnl"] > 0:
                    stats[f"{prefix}_wins"] += 1
                else:
                    stats[f"{prefix}_losses"] += 1
                stats[f"{prefix}_total_pnl"] += rec["pnl"]

    _add_record(sell_records, "sell")
    _add_record(buy_records, "buy")

    # Mark-to-market: attribute still-open positions using the latest brief's
    # current prices. Without this, modules whose trades are mostly unrealized
    # (e.g. signal_ranker — 247 of 267 trades open in recent data) get judged
    # only on the rare round-trip, which skews heavily negative when sells
    # happen to be the trigger-module.
    from app.services.market_brief import get_latest_brief

    brief = await get_latest_brief()
    price_map: dict[str, float] = {}
    if brief:
        for s in (brief.get("stocks") or []):
            if s.get("price"):
                price_map[s["symbol"]] = float(s["price"])
        for c in (brief.get("crypto") or []):
            if c.get("price"):
                price_map[c["symbol"]] = float(c["price"])

    open_buy_records: list[dict] = []
    for uid, syms in positions2.items():
        for sym, pos in syms.items():
            if pos["qty"] > 0 and sym in price_map:
                pnl = (price_map[sym] - pos["cost_basis"]) * pos["qty"]
                open_buy_records.append({"pnl": pnl, "modules": pos.get("buy_modules", [])})

    # Extend module_stats with open-buy tracking
    for rec in open_buy_records:
        for mod in rec["modules"]:
            if mod not in module_stats:
                module_stats[mod] = {
                    "sell_wins": 0, "sell_losses": 0, "sell_total_pnl": 0.0,
                    "buy_wins": 0, "buy_losses": 0, "buy_total_pnl": 0.0,
                    "open_wins": 0, "open_losses": 0, "open_total_pnl": 0.0,
                    "total_trades": 0,
                }
            stats = module_stats[mod]
            if "open_wins" not in stats:
                stats["open_wins"] = 0
                stats["open_losses"] = 0
                stats["open_total_pnl"] = 0.0
            if rec["pnl"] > 0:
                stats["open_wins"] += 1
            else:
                stats["open_losses"] += 1
            stats["open_total_pnl"] += rec["pnl"]

    # Format results
    from app.services.rag_toolkit import RAG_MODULES

    modules_result = {}
    for mod, stats in module_stats.items():
        sell_total = stats["sell_wins"] + stats["sell_losses"]
        buy_total = stats["buy_wins"] + stats["buy_losses"]
        open_wins = stats.get("open_wins", 0)
        open_losses = stats.get("open_losses", 0)
        open_total = open_wins + open_losses
        open_pnl = stats.get("open_total_pnl", 0.0)
        meta = RAG_MODULES.get(mod, {})

        # Full-buy view merges realized + unrealized buys
        full_buy_wins = stats["buy_wins"] + open_wins
        full_buy_losses = stats["buy_losses"] + open_losses
        full_buy_total = full_buy_wins + full_buy_losses
        full_buy_pnl = stats["buy_total_pnl"] + open_pnl

        modules_result[mod] = {
            "label": meta.get("label", mod),
            "color": meta.get("color", "#888"),
            "sell_win_rate": round(stats["sell_wins"] / sell_total * 100, 1) if sell_total > 0 else 0,
            "sell_trades": sell_total,
            "sell_total_pnl": round(stats["sell_total_pnl"], 2),
            "buy_win_rate": round(stats["buy_wins"] / buy_total * 100, 1) if buy_total > 0 else 0,
            "buy_trades": buy_total,
            "buy_total_pnl": round(stats["buy_total_pnl"], 2),
            "open_buy_win_rate": round(open_wins / open_total * 100, 1) if open_total > 0 else 0,
            "open_buy_trades": open_total,
            "open_buy_pnl_mtm": round(open_pnl, 2),
            "full_buy_win_rate": round(full_buy_wins / full_buy_total * 100, 1) if full_buy_total > 0 else 0,
            "full_buy_trades": full_buy_total,
            "full_buy_pnl": round(full_buy_pnl, 2),
            "combined_win_rate": round(
                (stats["sell_wins"] + full_buy_wins) /
                max(sell_total + full_buy_total, 1) * 100, 1
            ),
            "combined_pnl": round(stats["sell_total_pnl"] + full_buy_pnl, 2),
        }

    # --- Cite-rate: did traders who HAVE a module actually use it recently? ---
    from datetime import datetime, timedelta, timezone
    from app.services.ai_trader import PERSONALITIES

    def _personality_for(display_name: str) -> str | None:
        # Longest-name match: "Crypto Chad New (...)" must resolve to
        # crypto_chad_swing, not crypto_chad, despite the substring overlap.
        best = None
        for pkey, pinfo in PERSONALITIES.items():
            if pinfo["name"] in display_name:
                if best is None or len(pinfo["name"]) > len(PERSONALITIES[best]["name"]):
                    best = pkey
        return best

    trader_personality = {
        p["id"]: _personality_for(p.get("display_name") or "")
        for p in profiles_resp.data
    }
    toolkit_modules = {
        pkey: {t["module"] for t in pinfo.get("toolkit", [])}
        for pkey, pinfo in PERSONALITIES.items()
    }

    cite_cutoff = datetime.now(timezone.utc) - timedelta(days=cite_days)
    cite_counts: dict[str, int] = {}
    eligible_counts: dict[str, int] = {}
    for tx in tx_rows:
        try:
            ts = datetime.fromisoformat(tx["created_at"].replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            continue
        if ts < cite_cutoff:
            continue
        available = toolkit_modules.get(trader_personality.get(tx["user_id"]), set())
        cited = []
        if tx.get("modules_used"):
            try:
                cited = json.loads(tx["modules_used"])
            except (json.JSONDecodeError, TypeError):
                pass
        for mod in available:
            eligible_counts[mod] = eligible_counts.get(mod, 0) + 1
            if mod in cited:
                cite_counts[mod] = cite_counts.get(mod, 0) + 1

    # A module nobody ever cited has no attribution stats — add a zeroed
    # entry so it shows up in the report instead of being invisible.
    for mod in eligible_counts:
        if mod not in modules_result:
            meta = RAG_MODULES.get(mod, {})
            modules_result[mod] = {
                "label": meta.get("label", mod),
                "color": meta.get("color", "#888"),
                "sell_win_rate": 0, "sell_trades": 0, "sell_total_pnl": 0.0,
                "buy_win_rate": 0, "buy_trades": 0, "buy_total_pnl": 0.0,
                "open_buy_win_rate": 0, "open_buy_trades": 0, "open_buy_pnl_mtm": 0.0,
                "full_buy_win_rate": 0, "full_buy_trades": 0, "full_buy_pnl": 0.0,
                "combined_win_rate": 0, "combined_pnl": 0.0,
            }

    for mod, entry in modules_result.items():
        eligible = eligible_counts.get(mod, 0)
        cites = cite_counts.get(mod, 0)
        entry["cite_count_recent"] = cites
        entry["eligible_trades_recent"] = eligible
        entry["cite_rate_recent"] = round(cites / eligible * 100, 1) if eligible else None

    low_adoption = sorted(
        (
            {
                "module": mod,
                "label": entry["label"],
                "cite_rate_recent": entry["cite_rate_recent"],
                "cite_count_recent": entry["cite_count_recent"],
                "eligible_trades_recent": entry["eligible_trades_recent"],
            }
            for mod, entry in modules_result.items()
            if entry["eligible_trades_recent"] >= 20
            and (entry["cite_rate_recent"] or 0) < 5.0
        ),
        key=lambda m: m["cite_rate_recent"] or 0,
    )

    # Sort by combined P&L (now includes mark-to-market on open positions)
    modules_result = dict(
        sorted(modules_result.items(), key=lambda x: x[1]["combined_pnl"], reverse=True)
    )

    return {
        "modules": modules_result,
        "total_sells_analyzed": len(sell_records),
        "total_buys_analyzed": len(buy_records),
        "total_open_buys_analyzed": len(open_buy_records),
        "cite_window_days": cite_days,
        "low_adoption": low_adoption,
    }


# ---------------------------------------------------------------------------
# Convergence quality analysis
# ---------------------------------------------------------------------------

def _compute_module_diversity(module_lists: list[list[str]]) -> dict:
    """Compute diversity of module usage across trades in a convergence cluster.

    Returns a score from 0.0 (all trades used identical modules) to 1.0
    (completely different modules), a classification, and shared modules.
    """
    if not module_lists or len(module_lists) < 2:
        return {"score": 0.0, "classification": "single_trade", "shared_modules": [], "all_modules": []}

    sets = [set(m) for m in module_lists if m]
    if not sets:
        return {"score": 0.0, "classification": "no_modules", "shared_modules": [], "all_modules": []}

    all_modules = sorted(set().union(*sets))
    shared = sorted(set.intersection(*sets)) if sets else []

    # Average pairwise Jaccard distance
    distances = []
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            union = sets[i] | sets[j]
            intersection = sets[i] & sets[j]
            if union:
                distances.append(1.0 - len(intersection) / len(union))
            else:
                distances.append(0.0)

    score = round(sum(distances) / max(len(distances), 1), 3)

    # Classify
    signal_ranker_in_all = all({"signal_ranker"} <= s for s in sets)
    if signal_ranker_in_all and score < 0.3:
        classification = "signal_ranker_driven"
    elif score > 0.3:
        classification = "diverse"
    else:
        classification = "homogeneous"

    return {
        "score": score,
        "classification": classification,
        "shared_modules": shared,
        "all_modules": all_modules,
    }


def _compute_reasoning_overlap(reasoning_texts: list[str]) -> float:
    """Compute keyword overlap between reasoning texts in a cluster.

    Returns 0.0 (no shared terms) to 1.0 (identical reasoning).
    Uses significant tokens only (>3 chars, no stopwords).
    """
    if len(reasoning_texts) < 2:
        return 0.0

    stopwords = {
        "the", "and", "for", "with", "this", "that", "from", "have", "has",
        "are", "was", "were", "been", "being", "will", "would", "could",
        "should", "may", "might", "can", "not", "but", "also", "than",
        "into", "more", "most", "some", "such", "very", "just", "about",
        "above", "below", "after", "before", "while", "during", "each",
        "which", "their", "there", "these", "those", "when", "where",
        "portfolio", "position", "trade", "buy", "sell", "stock", "crypto",
    }

    def tokenize(text: str) -> set[str]:
        words = set(text.lower().split())
        return {w for w in words if len(w) > 3 and w not in stopwords}

    token_sets = [tokenize(t) for t in reasoning_texts if t]
    if len(token_sets) < 2:
        return 0.0

    overlaps = []
    for i in range(len(token_sets)):
        for j in range(i + 1, len(token_sets)):
            union = token_sets[i] | token_sets[j]
            intersection = token_sets[i] & token_sets[j]
            if union:
                overlaps.append(len(intersection) / len(union))
    return round(sum(overlaps) / max(len(overlaps), 1), 3)


async def _get_outcome_price(
    symbol: str, asset_type: str, trade_date: str, horizon_days: int,
) -> float | None:
    """Look up the closing price `horizon_days` after `trade_date`.

    Uses historical candle data. Returns None if data not available.
    """
    from app.services.market_data import get_stock_candles, get_crypto_history, CRYPTO_MAP

    target_date = date.fromisoformat(trade_date) + timedelta(days=horizon_days)

    # Don't look up future dates
    if target_date > date.today():
        return None

    # Fetch candles covering the trade date + horizon window
    fetch_days = horizon_days + 15  # extra buffer for weekends/holidays
    if asset_type == "crypto" or symbol in CRYPTO_MAP:
        candles = await get_crypto_history(symbol, days=fetch_days)
    else:
        candles = await get_stock_candles(symbol, days=fetch_days)

    if not candles:
        return None

    # Find the closest candle on or after the target date
    target_str = target_date.isoformat()
    for candle in candles:
        candle_date = candle.get("date", "")
        if candle_date >= target_str:
            return candle["close"]

    # If no candle on/after target, use the most recent one before it
    if candles:
        return candles[-1]["close"]
    return None


async def get_convergence_quality(
    days: int = 30,
    outcome_horizon: int = 5,
    convergence_threshold: int = 3,
) -> dict:
    """Analyze whether convergence trades outperform independent trades.

    For each trade in the window, tags it as convergence (N+ AIs same symbol+side+day)
    or independent, then computes outcome returns after `outcome_horizon` days.
    Also analyzes signal diversity within convergence clusters.
    """
    import json as _json

    db = get_supabase_admin()

    # Fetch all AI profiles
    profiles_resp = db.table("profiles").select("id, display_name, ai_model, is_ai").eq("is_ai", True).execute()
    if not profiles_resp.data:
        return {"error": "No AI traders found"}

    ai_ids = [p["id"] for p in profiles_resp.data]
    profile_map = {p["id"]: _clean_display_name(p.get("display_name", "")) for p in profiles_resp.data}

    # Fetch trades in window
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    trades = _fetch_all_rows(
        db.table("transactions")
        .select("id, user_id, symbol, asset_type, side, quantity, price, reasoning, modules_used, created_at")
        .in_("user_id", ai_ids)
        .gte("created_at", f"{cutoff}T00:00:00")
        .order("created_at", desc=False)
    )

    if not trades:
        return {"total_trades_analyzed": 0, "convergence": {}, "independent": {}}

    # --- Step 1: Tag convergence vs independent ---
    # Group by (date, symbol, side)
    groups: dict[tuple, list[dict]] = {}
    for t in trades:
        day = t["created_at"][:10]
        key = (day, t["symbol"], t["side"])
        groups.setdefault(key, []).append(t)

    convergence_ids: set[str] = set()
    cluster_map: dict[str, tuple] = {}  # trade_id -> cluster key
    for key, group in groups.items():
        if len(group) >= convergence_threshold:
            for t in group:
                convergence_ids.add(t["id"])
                cluster_map[t["id"]] = key

    # --- Step 2: Compute outcomes ---
    # Batch outcome lookups by symbol to minimize API calls
    symbols_needed: dict[str, dict] = {}  # symbol -> {asset_type, dates: set}
    settle_cutoff = date.today() - timedelta(days=outcome_horizon)

    for t in trades:
        trade_date = t["created_at"][:10]
        if date.fromisoformat(trade_date) <= settle_cutoff:
            sym = t["symbol"]
            if sym not in symbols_needed:
                symbols_needed[sym] = {"asset_type": t["asset_type"], "dates": set()}
            symbols_needed[sym]["dates"].add(trade_date)

    # Fetch outcome prices
    outcome_cache: dict[tuple, float | None] = {}  # (symbol, trade_date) -> price
    for sym, info in symbols_needed.items():
        for td in info["dates"]:
            price = await _get_outcome_price(sym, info["asset_type"], td, outcome_horizon)
            outcome_cache[(sym, td)] = price

    # --- Step 3: Compute per-trade returns ---
    conv_results = []
    indep_results = []
    pending_count = 0

    for t in trades:
        trade_date = t["created_at"][:10]
        trade_price = float(t["price"])
        is_convergence = t["id"] in convergence_ids

        # Parse modules
        modules = []
        if t.get("modules_used"):
            try:
                modules = _json.loads(t["modules_used"]) if isinstance(t["modules_used"], str) else t["modules_used"]
            except Exception:
                pass

        outcome_price = outcome_cache.get((t["symbol"], trade_date))

        if outcome_price is None:
            pending_count += 1
            continue

        # Compute return
        if t["side"] == "buy":
            return_pct = round((outcome_price - trade_price) / trade_price * 100, 2) if trade_price > 0 else 0
        else:
            return_pct = round((trade_price - outcome_price) / trade_price * 100, 2) if trade_price > 0 else 0

        record = {
            "return_pct": return_pct,
            "is_win": return_pct > 0,
            "side": t["side"],
            "symbol": t["symbol"],
            "modules": modules,
            "trader": profile_map.get(t["user_id"], "Unknown"),
            "trade_date": trade_date,
            "trade_price": trade_price,
            "outcome_price": round(outcome_price, 2),
        }

        if is_convergence:
            conv_results.append(record)
        else:
            indep_results.append(record)

    # --- Step 4: Aggregate ---
    def _aggregate(records: list[dict]) -> dict:
        if not records:
            return {"total": 0, "win_rate": 0, "avg_return_pct": 0, "median_return_pct": 0, "by_side": {}}

        wins = sum(1 for r in records if r["is_win"])
        returns = sorted(r["return_pct"] for r in records)
        mid = len(returns) // 2
        median = returns[mid] if len(returns) % 2 else round((returns[mid - 1] + returns[mid]) / 2, 2)

        by_side = {}
        for side in ("buy", "sell"):
            side_recs = [r for r in records if r["side"] == side]
            if side_recs:
                side_wins = sum(1 for r in side_recs if r["is_win"])
                by_side[side] = {
                    "total": len(side_recs),
                    "win_rate": round(side_wins / len(side_recs) * 100, 1),
                    "avg_return_pct": round(sum(r["return_pct"] for r in side_recs) / len(side_recs), 2),
                }

        return {
            "total": len(records),
            "win_rate": round(wins / len(records) * 100, 1),
            "avg_return_pct": round(sum(r["return_pct"] for r in records) / len(records), 2),
            "median_return_pct": median,
            "by_side": by_side,
        }

    conv_agg = _aggregate(conv_results)
    indep_agg = _aggregate(indep_results)

    # --- Step 5: Convergence edge ---
    wr_delta = round(conv_agg["win_rate"] - indep_agg["win_rate"], 1) if conv_agg["total"] and indep_agg["total"] else 0
    ret_delta = round(conv_agg["avg_return_pct"] - indep_agg["avg_return_pct"], 2) if conv_agg["total"] and indep_agg["total"] else 0

    if conv_agg["total"] < 5 or indep_agg["total"] < 5:
        verdict = "insufficient_data"
    elif wr_delta > 3:
        verdict = "convergence_outperforms"
    elif wr_delta < -3:
        verdict = "independent_outperforms"
    else:
        verdict = "no_significant_difference"

    # --- Step 6: Cluster diversity analysis ---
    cluster_details = []
    diversity_buckets: dict[str, list[dict]] = {
        "diverse": [], "signal_ranker_driven": [], "homogeneous": [],
        "no_modules": [], "single_trade": [],
    }

    for key, group in groups.items():
        if len(group) < convergence_threshold:
            continue

        day, sym, side = key
        trade_date = day

        # Collect modules and reasoning from all trades in cluster
        cluster_modules = []
        cluster_reasoning = []
        cluster_traders = []
        prices = []
        for t in group:
            modules = []
            if t.get("modules_used"):
                try:
                    modules = _json.loads(t["modules_used"]) if isinstance(t["modules_used"], str) else t["modules_used"]
                except Exception:
                    pass
            cluster_modules.append(modules)
            cluster_reasoning.append(t.get("reasoning", "") or "")
            cluster_traders.append(profile_map.get(t["user_id"], "Unknown"))
            prices.append(float(t["price"]))

        diversity = _compute_module_diversity(cluster_modules)
        reasoning_overlap = _compute_reasoning_overlap(cluster_reasoning)

        outcome = outcome_cache.get((sym, trade_date))
        avg_price = round(sum(prices) / len(prices), 2)

        if outcome is not None:
            if side == "buy":
                cluster_return = round((outcome - avg_price) / avg_price * 100, 2) if avg_price > 0 else 0
            else:
                cluster_return = round((avg_price - outcome) / avg_price * 100, 2) if avg_price > 0 else 0
            cluster_win = cluster_return > 0
            status = "settled"
        else:
            cluster_return = None
            cluster_win = None
            status = "pending"

        detail = {
            "date": day,
            "symbol": sym,
            "side": side,
            "trader_count": len(group),
            "traders": sorted(set(cluster_traders)),
            "avg_trade_price": avg_price,
            "outcome_price": round(outcome, 2) if outcome else None,
            "return_pct": cluster_return,
            "is_win": cluster_win,
            "status": status,
            "diversity_class": diversity["classification"],
            "module_diversity_score": diversity["score"],
            "reasoning_overlap": reasoning_overlap,
            "shared_modules": diversity["shared_modules"],
            "all_modules": diversity["all_modules"],
        }
        cluster_details.append(detail)

        if status == "settled":
            diversity_buckets[diversity["classification"]].append(detail)

    # Aggregate diversity buckets
    diversity_analysis = {}
    for cls, bucket in diversity_buckets.items():
        settled = [d for d in bucket if d["return_pct"] is not None]
        if settled:
            wins = sum(1 for d in settled if d["is_win"])
            diversity_analysis[cls] = {
                "count": len(settled),
                "win_rate": round(wins / len(settled) * 100, 1),
                "avg_return_pct": round(sum(d["return_pct"] for d in settled) / len(settled), 2),
            }
        else:
            diversity_analysis[cls] = {"count": 0, "win_rate": 0, "avg_return_pct": 0}

    # Generate insight
    diverse_wr = diversity_analysis.get("diverse", {}).get("win_rate", 0)
    sr_wr = diversity_analysis.get("signal_ranker_driven", {}).get("win_rate", 0)
    homo_wr = diversity_analysis.get("homogeneous", {}).get("win_rate", 0)
    if diverse_wr and sr_wr and diverse_wr != sr_wr:
        delta = round(diverse_wr - sr_wr, 1)
        if delta > 0:
            insight = f"Diverse-reasoning convergence outperforms signal-ranker-driven by {delta}pp win rate"
        else:
            insight = f"Signal-ranker-driven convergence outperforms diverse-reasoning by {abs(delta)}pp win rate"
    elif not diversity_analysis.get("diverse", {}).get("count") and not diversity_analysis.get("signal_ranker_driven", {}).get("count"):
        insight = "Not enough settled convergence clusters to compare diversity impact"
    else:
        insight = "No significant difference between diversity categories yet"
    diversity_analysis["insight"] = insight

    # --- Step 7: Weekly trend ---
    weekly: dict[str, dict] = {}
    for r in conv_results + indep_results:
        d = date.fromisoformat(r["trade_date"])
        week_start = (d - timedelta(days=d.weekday())).isoformat()
        if week_start not in weekly:
            weekly[week_start] = {"conv_wins": 0, "conv_total": 0, "indep_wins": 0, "indep_total": 0}
        w = weekly[week_start]
        is_conv = r in conv_results
        if is_conv:
            w["conv_total"] += 1
            if r["is_win"]:
                w["conv_wins"] += 1
        else:
            w["indep_total"] += 1
            if r["is_win"]:
                w["indep_wins"] += 1

    weekly_trend = []
    for week, w in sorted(weekly.items()):
        weekly_trend.append({
            "week": week,
            "convergence_win_rate": round(w["conv_wins"] / w["conv_total"] * 100, 1) if w["conv_total"] else None,
            "independent_win_rate": round(w["indep_wins"] / w["indep_total"] * 100, 1) if w["indep_total"] else None,
            "convergence_count": w["conv_total"],
            "independent_count": w["indep_total"],
        })

    return {
        "window_days": days,
        "outcome_horizon_days": outcome_horizon,
        "convergence_threshold": convergence_threshold,
        "total_trades_analyzed": len(conv_results) + len(indep_results),
        "settled_trades": len(conv_results) + len(indep_results),
        "pending_trades": pending_count,
        "convergence": conv_agg,
        "independent": indep_agg,
        "convergence_edge": {
            "win_rate_delta": wr_delta,
            "avg_return_delta": ret_delta,
            "verdict": verdict,
        },
        "diversity_analysis": diversity_analysis,
        "clusters": sorted(cluster_details, key=lambda x: x["date"], reverse=True),
        "weekly_trend": weekly_trend,
    }


async def get_trade_reasoning(
    days: int = 7,
    trader_id: str | None = None,
    symbol: str | None = None,
) -> dict:
    """Viewer-friendly breakdown of AI trade reasoning.

    Groups trades by date, shows each AI's reasoning and modules used,
    and flags convergence (multiple AIs making the same call on the same
    symbol on the same day) so users can spot herd behavior vs independent
    thinking.
    """
    db = get_supabase_admin()
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    # Fetch AI profiles
    profiles_resp = (
        db.table("profiles")
        .select("id, display_name, ai_model, is_ai")
        .eq("is_ai", True)
        .execute()
    )
    profile_map = {
        p["id"]: {
            "display_name": _clean_display_name(p.get("display_name", "")),
            "model": _model_label(p.get("ai_model", "")),
        }
        for p in (profiles_resp.data or [])
    }
    ai_ids = list(profile_map.keys())

    # Fetch trades. The old .limit(2000) never worked — PostgREST caps a
    # single response at 1000 rows, so page instead.
    query = (
        db.table("transactions")
        .select("user_id, symbol, asset_type, side, quantity, price, total, reasoning, modules_used, created_at")
        .gte("created_at", f"{cutoff}T00:00:00")
        .order("created_at", desc=True)
    )
    if trader_id:
        query = query.eq("user_id", trader_id)
    else:
        query = query.in_("user_id", ai_ids)
    if symbol:
        query = query.eq("symbol", symbol.upper())

    trades = _fetch_all_rows(query, max_rows=2000)

    # Group by date
    import json as _json
    by_date: dict[str, list] = {}
    for t in trades:
        day = t["created_at"][:10]
        profile = profile_map.get(t["user_id"], {})

        modules = []
        if t.get("modules_used"):
            try:
                modules = _json.loads(t["modules_used"]) if isinstance(t["modules_used"], str) else t["modules_used"]
            except Exception:
                pass

        entry = {
            "trader": profile.get("display_name", "Unknown"),
            "model": profile.get("model", ""),
            "symbol": t["symbol"],
            "asset_type": t.get("asset_type", ""),
            "side": t["side"],
            "quantity": t["quantity"],
            "price": t["price"],
            "total": t.get("total", 0),
            "reasoning": t.get("reasoning", ""),
            "modules_used": modules,
            "time": t["created_at"][11:19] if len(t["created_at"]) > 11 else "",
        }
        by_date.setdefault(day, []).append(entry)

    # Detect convergence: multiple AIs making the same side call on the same
    # symbol on the same day
    convergence_flags = []
    for day, day_trades in by_date.items():
        # Group by (symbol, side)
        sym_side: dict[tuple, list] = {}
        for t in day_trades:
            key = (t["symbol"], t["side"])
            sym_side.setdefault(key, []).append(t["trader"])
        for (sym, side), traders_list in sym_side.items():
            if len(traders_list) >= 3:
                convergence_flags.append({
                    "date": day,
                    "symbol": sym,
                    "side": side,
                    "traders": traders_list,
                    "count": len(traders_list),
                    "warning": (
                        f"{len(traders_list)} AIs all {side.upper()}ing {sym} on the same day — "
                        f"possible herd behavior"
                    ),
                })

    # Per-trader summary: most common modules, trade count
    trader_summaries = {}
    for t in trades:
        profile = profile_map.get(t["user_id"], {})
        name = profile.get("display_name", "Unknown")
        if name not in trader_summaries:
            trader_summaries[name] = {"model": profile.get("model", ""), "trades": 0, "module_counts": {}}
        trader_summaries[name]["trades"] += 1
        modules = []
        if t.get("modules_used"):
            try:
                modules = _json.loads(t["modules_used"]) if isinstance(t["modules_used"], str) else t["modules_used"]
            except Exception:
                pass
        for m in modules:
            trader_summaries[name]["module_counts"][m] = trader_summaries[name]["module_counts"].get(m, 0) + 1

    # Format top modules per trader
    for name, summary in trader_summaries.items():
        mc = summary.pop("module_counts")
        summary["top_modules"] = sorted(mc.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "days": days,
        "total_trades": len(trades),
        "dates": {
            day: sorted(entries, key=lambda x: x["time"])
            for day, entries in sorted(by_date.items(), reverse=True)
        },
        "convergence_alerts": sorted(convergence_flags, key=lambda x: x["date"], reverse=True),
        "trader_summaries": trader_summaries,
    }


def _std(values: list[float]) -> float:
    """Standard deviation of a list of floats."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


# ---------------------------------------------------------------------------
# Trade discipline scoring
# ---------------------------------------------------------------------------
# Measures whether each AI personality follows their stated strategy.
# Each rule returns a score 0-100 and a short description.

# Personality-specific discipline rules
DISCIPLINE_RULES: dict[str, list[dict]] = {
    "vanilla": [
        {"id": "cash_reserve", "label": "Cash Reserve (10-20%)", "target_min": 10, "target_max": 20},
        {"id": "sector_cap", "label": "No Sector >40%", "max_sector_pct": 40},
        {"id": "diversification", "label": "Diversified (5+ positions)", "min_positions": 5},
        {"id": "module_alignment", "label": "Uses Fundamentals+Technicals", "required_modules": ["fundamentals", "technicals"]},
    ],
    "steady_eddie": [
        {"id": "crypto_limit", "label": "Crypto <5%", "max_crypto_pct": 5},
        {"id": "cash_reserve", "label": "Cash Reserve (10%+)", "target_min": 10, "target_max": 100},
        {"id": "low_turnover", "label": "Low Turnover (<5 trades/day avg)", "max_daily_trades": 5},
        {"id": "module_alignment", "label": "Uses Fundamentals", "required_modules": ["fundamentals"]},
    ],
    "yolo_bot": [
        {"id": "low_cash", "label": "Fully Invested (<10% cash)", "target_min": 0, "target_max": 10},
        {"id": "concentrated", "label": "Concentrated (3-5 names)", "min_positions": 2, "max_positions": 8},
        {"id": "high_turnover", "label": "Active Trading (3+ trades/day avg)", "min_daily_trades": 3},
        {"id": "module_alignment", "label": "Uses Momentum+Technicals", "required_modules": ["momentum", "technicals"]},
    ],
    "contrarian_carl": [
        {"id": "cash_reserve", "label": "Dry Powder (15-25% cash)", "target_min": 15, "target_max": 25},
        {"id": "diversification", "label": "6-10 positions", "min_positions": 6, "max_positions": 12},
        {"id": "buys_dips", "label": "Buys Oversold Assets", "check": "buys_low_rsi"},
        {"id": "module_alignment", "label": "Uses Sentiment+Fundamentals", "required_modules": ["sentiment", "fundamentals"]},
    ],
    "crypto_chad": [
        {"id": "crypto_heavy", "label": "60-80% Crypto", "min_crypto_pct": 60, "max_crypto_pct": 80},
        {"id": "has_tech", "label": "Tech Stock Hedges", "check": "has_tech_stocks"},
        {"id": "module_alignment", "label": "Uses Momentum+Technicals", "required_modules": ["momentum", "technicals"]},
    ],
    # V2 swing variant: patient, tiered crypto (BTC/ETH 40-50% + utility 15-25%),
    # 20-30% tech, 10-25% dry powder, 9-12 trades/month.
    "crypto_chad_swing": [
        {"id": "crypto_heavy", "label": "55-80% Crypto", "min_crypto_pct": 55, "max_crypto_pct": 80},
        {"id": "cash_reserve", "label": "Dry Powder (10-25%)", "target_min": 10, "target_max": 25},
        {"id": "low_turnover", "label": "Patient (≤2 trades/day avg)", "max_daily_trades": 2},
        {"id": "module_alignment", "label": "Uses BTC On-Chain+Expert Opinion", "required_modules": ["btc_onchain", "expert_opinion"]},
    ],
    # V2 patient deep-value contrarian: S&P 500 only, 6-10 names, 15-25% cash,
    # 8-12 trades/month.
    "contrarian_carl_patient": [
        {"id": "cash_reserve", "label": "Dry Powder (15-25% cash)", "target_min": 15, "target_max": 25},
        {"id": "diversification", "label": "6-10 positions", "min_positions": 6, "max_positions": 10},
        {"id": "low_turnover", "label": "Patient (≤2 trades/day avg)", "max_daily_trades": 2},
        {"id": "module_alignment", "label": "Uses Fundamentals+Sentiment", "required_modules": ["fundamentals", "sentiment"]},
    ],
}


async def compute_discipline_score(trader_id: str) -> dict:
    """Score how well an AI trader follows their personality's strategy.

    Returns per-rule scores (0-100) and an overall discipline grade.
    """
    db = get_supabase_admin()

    # Get profile
    profile = db.table("profiles").select(
        "id, display_name, ai_model, cash_balance"
    ).eq("id", trader_id).single().execute()
    if not profile.data:
        return {"error": "Trader not found"}

    display_name = profile.data["display_name"]
    cash = float(profile.data["cash_balance"])

    # Determine personality
    from app.services.ai_trader import PERSONALITIES
    personality_key = None
    for pkey, pinfo in PERSONALITIES.items():
        if pinfo["name"] in display_name:
            personality_key = pkey
            break
    if not personality_key or personality_key not in DISCIPLINE_RULES:
        return {"error": f"Unknown personality for {display_name}"}

    # Get positions
    positions = db.table("positions").select("*").eq("user_id", trader_id).execute()
    pos_list = positions.data or []

    # Get recent transactions (last 14 days)
    cutoff = (date.today() - timedelta(days=14)).isoformat()
    tx_resp = (
        db.table("transactions")
        .select("id, symbol, asset_type, side, quantity, price, total, modules_used, created_at")
        .eq("user_id", trader_id)
        .gte("created_at", f"{cutoff}T00:00:00")
        .order("created_at", desc=True)
        .execute()
    )
    transactions = tx_resp.data or []

    # Compute derived data
    # Portfolio value
    invested_value = 0.0
    crypto_value = 0.0
    tech_value = 0.0
    sector_values: dict[str, float] = {}
    for pos in pos_list:
        qty = float(pos["quantity"])
        price_est = float(pos["avg_cost_basis"])
        value = qty * price_est
        invested_value += value
        if pos["asset_type"] == "crypto":
            crypto_value += value
        else:
            sector = STOCK_SECTORS.get(pos["symbol"], "Other")
            sector_values[sector] = sector_values.get(sector, 0) + value
            if sector == "Technology":
                tech_value += value

    total_value = cash + invested_value
    cash_pct = (cash / total_value * 100) if total_value > 0 else 100
    crypto_pct = (crypto_value / total_value * 100) if total_value > 0 else 0
    num_positions = len(pos_list)
    max_sector_pct = max((v / total_value * 100 for v in sector_values.values()), default=0) if total_value > 0 else 0

    # Trade frequency
    trade_days = set()
    for tx in transactions:
        trade_days.add(tx["created_at"][:10])
    num_trade_days = max(len(trade_days), 1)
    avg_daily_trades = len(transactions) / num_trade_days

    # Module usage from recent trades
    module_counts: dict[str, int] = {}
    for tx in transactions:
        mods = tx.get("modules_used") or ""
        if isinstance(mods, str):
            for m in mods.replace("[", "").replace("]", "").replace('"', "").split(","):
                m = m.strip()
                if m:
                    module_counts[m] = module_counts.get(m, 0) + 1

    # Evaluate each rule
    rules = DISCIPLINE_RULES[personality_key]
    results = []
    for rule in rules:
        rule_id = rule["id"]
        score = 0
        detail = ""

        if rule_id == "cash_reserve" or rule_id == "low_cash":
            target_min = rule.get("target_min", 0)
            target_max = rule.get("target_max", 100)
            if target_min <= cash_pct <= target_max:
                score = 100
                detail = f"Cash {cash_pct:.1f}% (target {target_min}-{target_max}%)"
            else:
                # Partial credit based on distance from target range
                if cash_pct < target_min:
                    distance = target_min - cash_pct
                else:
                    distance = cash_pct - target_max
                score = max(0, int(100 - distance * 5))  # lose 5 pts per % off target
                detail = f"Cash {cash_pct:.1f}% (target {target_min}-{target_max}%)"

        elif rule_id == "sector_cap":
            max_allowed = rule["max_sector_pct"]
            if max_sector_pct <= max_allowed:
                score = 100
                detail = f"Max sector {max_sector_pct:.1f}% (limit {max_allowed}%)"
            else:
                score = max(0, int(100 - (max_sector_pct - max_allowed) * 5))
                detail = f"Max sector {max_sector_pct:.1f}% EXCEEDS {max_allowed}% limit"

        elif rule_id == "diversification" or rule_id == "concentrated":
            min_pos = rule.get("min_positions", 0)
            max_pos = rule.get("max_positions", 999)
            if min_pos <= num_positions <= max_pos:
                score = 100
                detail = f"{num_positions} positions (target {min_pos}-{max_pos})"
            elif num_positions < min_pos:
                score = max(0, int(num_positions / min_pos * 100))
                detail = f"{num_positions} positions (need {min_pos}+)"
            else:
                score = max(0, int(100 - (num_positions - max_pos) * 15))
                detail = f"{num_positions} positions (max {max_pos})"

        elif rule_id == "crypto_limit":
            max_pct = rule["max_crypto_pct"]
            if crypto_pct <= max_pct:
                score = 100
                detail = f"Crypto {crypto_pct:.1f}% (limit {max_pct}%)"
            else:
                score = max(0, int(100 - (crypto_pct - max_pct) * 5))
                detail = f"Crypto {crypto_pct:.1f}% EXCEEDS {max_pct}% limit"

        elif rule_id == "crypto_heavy":
            min_pct = rule.get("min_crypto_pct", 60)
            max_pct = rule.get("max_crypto_pct", 80)
            if min_pct <= crypto_pct <= max_pct:
                score = 100
                detail = f"Crypto {crypto_pct:.1f}% (target {min_pct}-{max_pct}%)"
            elif crypto_pct < min_pct:
                score = max(0, int(crypto_pct / min_pct * 100))
                detail = f"Crypto {crypto_pct:.1f}% (need {min_pct}%+)"
            else:
                score = max(0, int(100 - (crypto_pct - max_pct) * 3))
                detail = f"Crypto {crypto_pct:.1f}% (target max {max_pct}%)"

        elif rule_id == "low_turnover":
            max_trades = rule["max_daily_trades"]
            if avg_daily_trades <= max_trades:
                score = 100
            else:
                score = max(0, int(100 - (avg_daily_trades - max_trades) * 20))
            detail = f"{avg_daily_trades:.1f} trades/day (max {max_trades})"

        elif rule_id == "high_turnover":
            min_trades = rule["min_daily_trades"]
            if avg_daily_trades >= min_trades:
                score = 100
            else:
                score = max(0, int(avg_daily_trades / min_trades * 100))
            detail = f"{avg_daily_trades:.1f} trades/day (min {min_trades})"

        elif rule_id == "module_alignment":
            required = rule["required_modules"]
            if not module_counts:
                score = 50  # no data yet
                detail = "No recent trades to evaluate"
            else:
                total_module_uses = sum(module_counts.values())
                required_uses = sum(module_counts.get(m, 0) for m in required)
                if total_module_uses > 0:
                    pct = required_uses / total_module_uses * 100
                    score = min(100, int(pct * 2))  # 50%+ usage = 100
                    detail = f"{', '.join(required)}: {pct:.0f}% of module usage"
                else:
                    score = 50
                    detail = "No module data"

        elif rule_id == "buys_dips":
            # Check if buy trades mention oversold/low RSI in reasoning
            buys = [tx for tx in transactions if tx.get("side") == "buy"]
            if not buys:
                score = 50
                detail = "No recent buys to evaluate"
            else:
                dip_keywords = ["oversold", "rsi", "dip", "pullback", "fear", "panic", "undervalued"]
                dip_buys = sum(
                    1 for tx in buys
                    if any(kw in (tx.get("reasoning") or "").lower() for kw in dip_keywords)
                )
                pct = dip_buys / len(buys) * 100
                score = min(100, int(pct * 1.5))
                detail = f"{dip_buys}/{len(buys)} buys mention dip/oversold signals"

        elif rule_id == "has_tech":
            if tech_value > 0:
                tech_pct = tech_value / total_value * 100 if total_value > 0 else 0
                score = min(100, int(tech_pct * 10))  # 10%+ = 100
                detail = f"Tech stocks: {tech_pct:.1f}% of portfolio"
            else:
                score = 0
                detail = "No tech stock hedges"

        results.append({
            "rule": rule["label"],
            "score": score,
            "detail": detail,
        })

    # Overall grade
    if results:
        avg_score = sum(r["score"] for r in results) / len(results)
    else:
        avg_score = 0

    if avg_score >= 80:
        grade = "A"
    elif avg_score >= 60:
        grade = "B"
    elif avg_score >= 40:
        grade = "C"
    elif avg_score >= 20:
        grade = "D"
    else:
        grade = "F"

    return {
        "trader_id": trader_id,
        "display_name": display_name,
        "personality": personality_key,
        "overall_score": round(avg_score, 1),
        "grade": grade,
        "rules": results,
        "meta": {
            "cash_pct": round(cash_pct, 1),
            "crypto_pct": round(crypto_pct, 1),
            "num_positions": num_positions,
            "avg_daily_trades": round(avg_daily_trades, 1),
            "total_value": round(total_value, 2),
            "transactions_analyzed": len(transactions),
        },
    }


async def get_all_discipline_scores() -> dict:
    """Get discipline scores for all AI traders."""
    db = get_supabase_admin()
    profiles = (
        db.table("profiles")
        .select("id, display_name")
        .eq("is_ai", True)
        .execute()
    )
    if not profiles.data:
        return {"traders": []}

    results = []
    for p in profiles.data:
        score = await compute_discipline_score(p["id"])
        if "error" not in score:
            results.append(score)

    # Sort by overall score descending
    results.sort(key=lambda x: x["overall_score"], reverse=True)

    return {
        "traders": results,
        "avg_discipline": round(
            sum(r["overall_score"] for r in results) / max(len(results), 1), 1
        ),
    }
