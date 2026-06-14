"""Backtesting & benchmark comparison for AI traders.

Compares AI trader performance against:
1. SPY buy-and-hold benchmark (same starting capital)
2. Pre vs post enhancement periods
3. Per-personality performance across market regimes
"""

from datetime import date, timedelta

from app.services.supabase_client import get_supabase_admin, fetch_all_rows
from app.services.market_data import get_stock_candles, STOCK_SECTORS
from app.services.ai_trader import PERSONALITIES, resolve_personality_key
from app.services.analytics import _model_label, _clean_display_name

STARTING_BALANCE = 100_000.0


async def get_benchmark_comparison(days: int = 90) -> dict:
    """Compare all AI traders against SPY buy-and-hold over a period."""
    db = get_supabase_admin()
    today = date.today()
    start_date = today - timedelta(days=days)

    # Get SPY price history for benchmark (try requested period, fall back to 30 days)
    spy_candles = await get_stock_candles("SPY", days=days)
    if not spy_candles and days > 30:
        spy_candles = await get_stock_candles("SPY", days=30)
    if not spy_candles:
        return {"error": "Could not fetch SPY data from Finnhub. This may be a temporary API issue — try again in a few minutes."}

    # Calculate SPY buy-and-hold return
    spy_start = spy_candles[0]["close"]
    spy_end = spy_candles[-1]["close"]
    spy_return_pct = (spy_end - spy_start) / spy_start * 100

    # Build SPY daily return series
    spy_series = []
    for candle in spy_candles:
        ret = (candle["close"] - spy_start) / spy_start * 100
        spy_series.append({
            "date": date.fromtimestamp(candle["time"]).isoformat(),
            "return_pct": round(ret, 2),
        })

    # Get all AI trader profiles
    profiles_resp = (
        db.table("profiles")
        .select("id, display_name, ai_model, is_ai")
        .eq("is_ai", True)
        .execute()
    )
    if not profiles_resp.data:
        return {"error": "No AI traders found"}

    trader_ids = [p["id"] for p in profiles_resp.data]

    # Fetch all snapshots in date range
    snap_rows = fetch_all_rows(
        db.table("portfolio_snapshots")
        .select("user_id, snapshot_date, total_value")
        .in_("user_id", trader_ids)
        .gte("snapshot_date", start_date.isoformat())
        .lte("snapshot_date", today.isoformat())
        .order("snapshot_date", desc=False)
    )

    # Group snapshots by user
    snap_by_user: dict[str, list] = {}
    for s in snap_rows:
        snap_by_user.setdefault(s["user_id"], []).append(s)

    # Compute each trader's return series
    traders = []
    for profile in profiles_resp.data:
        uid = profile["id"]
        snaps = snap_by_user.get(uid, [])
        if len(snaps) < 2:
            continue

        first_value = float(snaps[0]["total_value"])
        if first_value == 0:
            continue
        last_value = float(snaps[-1]["total_value"])
        trader_return = (last_value - first_value) / first_value * 100

        # Determine personality
        personality = resolve_personality_key(profile["display_name"])

        series = []
        for s in snaps:
            ret = (float(s["total_value"]) - first_value) / first_value * 100
            series.append({
                "date": s["snapshot_date"],
                "return_pct": round(ret, 2),
            })

        traders.append({
            "id": uid,
            "display_name": _clean_display_name(profile["display_name"]),
            "model": _model_label(profile["ai_model"]),
            "personality": personality,
            "total_return_pct": round(trader_return, 2),
            "beats_spy": trader_return > spy_return_pct,
            "alpha": round(trader_return - spy_return_pct, 2),
            "series": series,
        })

    traders.sort(key=lambda t: t["total_return_pct"], reverse=True)

    # Summary stats
    beating_spy = sum(1 for t in traders if t["beats_spy"])
    avg_alpha = (
        sum(t["alpha"] for t in traders) / len(traders) if traders else 0
    )

    return {
        "period_days": days,
        "start_date": start_date.isoformat(),
        "end_date": today.isoformat(),
        "benchmark": {
            "symbol": "SPY",
            "return_pct": round(spy_return_pct, 2),
            "start_price": round(spy_start, 2),
            "end_price": round(spy_end, 2),
            "series": spy_series,
        },
        "traders": traders,
        "summary": {
            "total_traders": len(traders),
            "beating_spy": beating_spy,
            "losing_to_spy": len(traders) - beating_spy,
            "avg_alpha": round(avg_alpha, 2),
            "best_trader": traders[0]["display_name"] if traders else None,
            "worst_trader": traders[-1]["display_name"] if traders else None,
        },
    }


async def get_enhancement_comparison() -> dict:
    """Compare AI trader performance before vs after the latest enhancement.

    Uses the deployment date of the enriched signals (2026-03-20) as the
    dividing line. Computes daily return rates for each period.
    """
    db = get_supabase_admin()
    enhancement_date = "2026-03-20"  # Date enriched signals were deployed
    today = date.today()

    # Get all AI trader profiles
    profiles_resp = (
        db.table("profiles")
        .select("id, display_name, ai_model, is_ai")
        .eq("is_ai", True)
        .execute()
    )
    if not profiles_resp.data:
        return {"error": "No AI traders found"}

    trader_ids = [p["id"] for p in profiles_resp.data]

    # Fetch ALL snapshots
    snap_rows = fetch_all_rows(
        db.table("portfolio_snapshots")
        .select("user_id, snapshot_date, total_value")
        .in_("user_id", trader_ids)
        .order("snapshot_date", desc=False)
    )

    snap_by_user: dict[str, list] = {}
    for s in snap_rows:
        snap_by_user.setdefault(s["user_id"], []).append(s)

    traders = []
    for profile in profiles_resp.data:
        uid = profile["id"]
        snaps = snap_by_user.get(uid, [])
        if len(snaps) < 3:
            continue

        pre_snaps = [s for s in snaps if s["snapshot_date"] < enhancement_date]
        post_snaps = [s for s in snaps if s["snapshot_date"] >= enhancement_date]

        personality = resolve_personality_key(profile["display_name"])

        pre_metrics = _compute_period_metrics(pre_snaps)
        post_metrics = _compute_period_metrics(post_snaps)

        traders.append({
            "display_name": _clean_display_name(profile["display_name"]),
            "model": _model_label(profile["ai_model"]),
            "personality": personality,
            "pre_enhancement": pre_metrics,
            "post_enhancement": post_metrics,
            "improved": (post_metrics["daily_return_avg"] > pre_metrics["daily_return_avg"])
                        if pre_metrics["days"] > 0 and post_metrics["days"] > 0
                        else None,
        })

    improved = sum(1 for t in traders if t.get("improved") is True)
    total_with_data = sum(1 for t in traders if t.get("improved") is not None)

    return {
        "enhancement_date": enhancement_date,
        "traders": traders,
        "summary": {
            "total_traders": len(traders),
            "with_both_periods": total_with_data,
            "improved": improved,
            "not_improved": total_with_data - improved,
        },
    }


async def get_regime_analysis(days: int = 90) -> dict:
    """Detect market regimes from SPY data, then compute per-trader
    win rate and return within each regime.

    Regimes (rolling 10-day SPY return + volatility):
    - BULL: SPY 10d return > +2%
    - BEAR: SPY 10d return < -2%
    - HIGH_VOL: 10d volatility > 1.5% daily but return between -2% and +2%
    - SIDEWAYS: everything else
    """
    import math
    from datetime import datetime

    db = get_supabase_admin()

    # Get SPY candles for regime classification
    spy_candles = await get_stock_candles("SPY", days=days)
    if not spy_candles or len(spy_candles) < 15:
        return {"error": "Insufficient SPY data for regime detection"}

    # Build date -> regime map using rolling 10-day windows
    spy_by_date: dict[str, float] = {}
    for c in spy_candles:
        d = date.fromtimestamp(c["time"]).isoformat()
        spy_by_date[d] = c["close"]

    spy_dates = sorted(spy_by_date.keys())
    spy_closes = [spy_by_date[d] for d in spy_dates]

    regime_map: dict[str, str] = {}
    for i in range(10, len(spy_closes)):
        window = spy_closes[i - 10 : i + 1]
        ret_10d = (window[-1] - window[0]) / window[0] * 100
        daily_rets = [(window[j] / window[j - 1]) - 1 for j in range(1, len(window))]
        vol = math.sqrt(sum(r ** 2 for r in daily_rets) / len(daily_rets)) * 100

        if ret_10d > 2:
            regime = "BULL"
        elif ret_10d < -2:
            regime = "BEAR"
        elif vol > 1.5:
            regime = "HIGH_VOL"
        else:
            regime = "SIDEWAYS"

        regime_map[spy_dates[i]] = regime

    if not regime_map:
        return {"error": "Could not classify regimes"}

    # Regime summary
    regime_counts = {}
    for r in regime_map.values():
        regime_counts[r] = regime_counts.get(r, 0) + 1

    # Get all AI traders and their trades in this period
    profiles_resp = (
        db.table("profiles")
        .select("id, display_name, ai_model, is_ai")
        .eq("is_ai", True)
        .execute()
    )
    if not profiles_resp.data:
        return {"error": "No AI traders found"}

    trader_ids = [p["id"] for p in profiles_resp.data]
    start_date = min(regime_map.keys())

    tx_rows = fetch_all_rows(
        db.table("transactions")
        .select("user_id, symbol, side, quantity, price, total, created_at")
        .in_("user_id", trader_ids)
        .gte("created_at", f"{start_date}T00:00:00")
        .order("created_at", desc=False)
    )

    # Replay trades and tag each sell's P&L with the regime on trade date
    positions: dict[str, dict[str, dict]] = {}
    regime_pnl: dict[str, dict[str, list[float]]] = {}  # user_id -> regime -> [pnl]

    for tx in tx_rows:
        uid = tx["user_id"]
        sym = tx["symbol"]
        qty = float(tx["quantity"])
        price = float(tx["price"])
        trade_date = tx["created_at"][:10]

        if uid not in positions:
            positions[uid] = {}
        if uid not in regime_pnl:
            regime_pnl[uid] = {}

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
                regime = regime_map.get(trade_date, "UNKNOWN")
                regime_pnl[uid].setdefault(regime, []).append(pnl)
                pos["qty"] -= qty
                if pos["qty"] <= 0.001:
                    pos["qty"] = 0
                    pos["cost_basis"] = 0

    # Build per-trader regime performance
    traders = []
    for profile in profiles_resp.data:
        uid = profile["id"]
        by_regime = regime_pnl.get(uid, {})
        if not by_regime:
            continue

        personality = resolve_personality_key(profile["display_name"])

        regime_stats = {}
        for regime, pnls in by_regime.items():
            if regime == "UNKNOWN":
                continue
            wins = [p for p in pnls if p > 0]
            regime_stats[regime] = {
                "trades": len(pnls),
                "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
                "total_pnl": round(sum(pnls), 2),
                "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0,
            }

        traders.append({
            "display_name": _clean_display_name(profile["display_name"]),
            "model": _model_label(profile["ai_model"]),
            "personality": personality,
            "by_regime": regime_stats,
        })

    # Aggregate by personality across regimes
    personality_regime: dict[str, dict[str, list[float]]] = {}
    for uid, by_regime in regime_pnl.items():
        profile = next((p for p in profiles_resp.data if p["id"] == uid), None)
        if not profile:
            continue
        personality = resolve_personality_key(profile["display_name"])
        if not personality:
            continue
        for regime, pnls in by_regime.items():
            if regime == "UNKNOWN":
                continue
            personality_regime.setdefault(personality, {}).setdefault(regime, []).extend(pnls)

    personality_summary = {}
    for pers, by_regime in personality_regime.items():
        regime_stats = {}
        for regime, pnls in by_regime.items():
            wins = [p for p in pnls if p > 0]
            regime_stats[regime] = {
                "trades": len(pnls),
                "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
                "total_pnl": round(sum(pnls), 2),
            }
        personality_summary[pers] = regime_stats

    return {
        "period_days": days,
        "regimes": regime_counts,
        "current_regime": regime_map.get(spy_dates[-1], "UNKNOWN") if spy_dates else "UNKNOWN",
        "traders": traders,
        "by_personality": personality_summary,
    }


async def get_period_comparison(
    period_a_start: str,
    period_a_end: str,
    period_b_start: str,
    period_b_end: str,
) -> dict:
    """Compare AI trader performance across two arbitrary date ranges.

    Useful for measuring impact of any pipeline change by comparing
    the period before vs after deployment.
    """
    db = get_supabase_admin()

    profiles_resp = (
        db.table("profiles")
        .select("id, display_name, ai_model, is_ai")
        .eq("is_ai", True)
        .execute()
    )
    if not profiles_resp.data:
        return {"error": "No AI traders found"}

    trader_ids = [p["id"] for p in profiles_resp.data]

    snap_rows = fetch_all_rows(
        db.table("portfolio_snapshots")
        .select("user_id, snapshot_date, total_value")
        .in_("user_id", trader_ids)
        .order("snapshot_date", desc=False)
    )

    snap_by_user: dict[str, list] = {}
    for s in snap_rows:
        snap_by_user.setdefault(s["user_id"], []).append(s)

    traders = []
    for profile in profiles_resp.data:
        uid = profile["id"]
        snaps = snap_by_user.get(uid, [])
        if len(snaps) < 3:
            continue

        a_snaps = [s for s in snaps if period_a_start <= s["snapshot_date"] <= period_a_end]
        b_snaps = [s for s in snaps if period_b_start <= s["snapshot_date"] <= period_b_end]

        personality = resolve_personality_key(profile["display_name"])

        a_metrics = _compute_period_metrics(a_snaps)
        b_metrics = _compute_period_metrics(b_snaps)

        improved = None
        if a_metrics["days"] > 1 and b_metrics["days"] > 1:
            improved = b_metrics["daily_return_avg"] > a_metrics["daily_return_avg"]

        traders.append({
            "display_name": _clean_display_name(profile["display_name"]),
            "model": _model_label(profile["ai_model"]),
            "personality": personality,
            "period_a": a_metrics,
            "period_b": b_metrics,
            "improved": improved,
        })

    improved_count = sum(1 for t in traders if t.get("improved") is True)
    total_with_data = sum(1 for t in traders if t.get("improved") is not None)

    # Aggregate averages per period
    a_returns = [t["period_a"]["daily_return_avg"] for t in traders if t["period_a"]["days"] > 1]
    b_returns = [t["period_b"]["daily_return_avg"] for t in traders if t["period_b"]["days"] > 1]

    return {
        "period_a": {"start": period_a_start, "end": period_a_end},
        "period_b": {"start": period_b_start, "end": period_b_end},
        "traders": traders,
        "summary": {
            "total_traders": len(traders),
            "with_both_periods": total_with_data,
            "improved": improved_count,
            "not_improved": total_with_data - improved_count,
            "avg_daily_return_a": round(sum(a_returns) / len(a_returns), 4) if a_returns else 0,
            "avg_daily_return_b": round(sum(b_returns) / len(b_returns), 4) if b_returns else 0,
        },
    }


def _compute_period_metrics(snapshots: list[dict]) -> dict:
    """Compute return metrics for a period of snapshots."""
    if len(snapshots) < 2:
        return {
            "days": len(snapshots),
            "total_return_pct": 0.0,
            "daily_return_avg": 0.0,
            "start_value": float(snapshots[0]["total_value"]) if snapshots else 0,
            "end_value": float(snapshots[-1]["total_value"]) if snapshots else 0,
        }

    values = [float(s["total_value"]) for s in snapshots]
    start = values[0]
    end = values[-1]

    if start == 0:
        return {"days": len(snapshots), "total_return_pct": 0.0, "daily_return_avg": 0.0,
                "start_value": 0, "end_value": end}

    total_return = (end - start) / start * 100

    daily_returns = []
    for i in range(1, len(values)):
        if values[i - 1] > 0:
            daily_returns.append((values[i] - values[i - 1]) / values[i - 1] * 100)

    avg_daily = sum(daily_returns) / len(daily_returns) if daily_returns else 0.0

    return {
        "days": len(snapshots),
        "total_return_pct": round(total_return, 2),
        "daily_return_avg": round(avg_daily, 4),
        "start_value": round(start, 2),
        "end_value": round(end, 2),
    }
