"""Backtesting & benchmark comparison for AI traders.

Compares AI trader performance against:
1. SPY buy-and-hold benchmark (same starting capital)
2. Pre vs post enhancement periods
3. Per-personality performance across market regimes
"""

from datetime import date, timedelta

from app.services.supabase_client import get_supabase_admin
from app.services.market_data import get_stock_candles, STOCK_SECTORS
from app.services.ai_trader import PERSONALITIES

STARTING_BALANCE = 100_000.0


async def get_benchmark_comparison(days: int = 90) -> dict:
    """Compare all AI traders against SPY buy-and-hold over a period."""
    db = get_supabase_admin()
    today = date.today()
    start_date = today - timedelta(days=days)

    # Get SPY price history for benchmark
    spy_candles = await get_stock_candles("SPY", days=days)
    if not spy_candles:
        return {"error": "Could not fetch SPY data for benchmark"}

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
    snap_resp = (
        db.table("portfolio_snapshots")
        .select("user_id, snapshot_date, total_value")
        .in_("user_id", trader_ids)
        .gte("snapshot_date", start_date.isoformat())
        .lte("snapshot_date", today.isoformat())
        .order("snapshot_date", desc=False)
        .execute()
    )

    # Group snapshots by user
    snap_by_user: dict[str, list] = {}
    for s in snap_resp.data:
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
        personality = None
        for pkey, pinfo in PERSONALITIES.items():
            if pinfo["name"] in profile["display_name"]:
                personality = pkey
                break

        series = []
        for s in snaps:
            ret = (float(s["total_value"]) - first_value) / first_value * 100
            series.append({
                "date": s["snapshot_date"],
                "return_pct": round(ret, 2),
            })

        traders.append({
            "id": uid,
            "display_name": profile["display_name"],
            "model": profile["ai_model"],
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
    snap_resp = (
        db.table("portfolio_snapshots")
        .select("user_id, snapshot_date, total_value")
        .in_("user_id", trader_ids)
        .order("snapshot_date", desc=False)
        .execute()
    )

    snap_by_user: dict[str, list] = {}
    for s in snap_resp.data:
        snap_by_user.setdefault(s["user_id"], []).append(s)

    traders = []
    for profile in profiles_resp.data:
        uid = profile["id"]
        snaps = snap_by_user.get(uid, [])
        if len(snaps) < 3:
            continue

        pre_snaps = [s for s in snaps if s["snapshot_date"] < enhancement_date]
        post_snaps = [s for s in snaps if s["snapshot_date"] >= enhancement_date]

        personality = None
        for pkey, pinfo in PERSONALITIES.items():
            if pinfo["name"] in profile["display_name"]:
                personality = pkey
                break

        pre_metrics = _compute_period_metrics(pre_snaps)
        post_metrics = _compute_period_metrics(post_snaps)

        traders.append({
            "display_name": profile["display_name"],
            "model": profile["ai_model"],
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
