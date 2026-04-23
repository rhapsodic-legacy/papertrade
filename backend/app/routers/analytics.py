from fastapi import APIRouter, HTTPException, Query

from app.services.analytics import (
    get_trader_analytics, get_ai_comparison, get_model_deep_dive,
    get_module_attribution, get_convergence_quality,
    get_reflection_trends, get_trade_reasoning, _model_label, _clean_display_name,
    compute_discipline_score, get_all_discipline_scores,
)
from app.services.backtest import (
    get_benchmark_comparison, get_enhancement_comparison,
    get_period_comparison, get_regime_analysis,
)
from app.services.supabase_client import get_supabase_admin

router = APIRouter()


@router.get("/trader/{trader_id}")
async def trader_analytics(trader_id: str):
    """Full performance analytics for a single trader."""
    db = get_supabase_admin()
    profile = (
        db.table("profiles")
        .select("id, display_name, ai_model, is_ai")
        .eq("id", trader_id)
        .execute()
    )
    if not profile.data:
        raise HTTPException(status_code=404, detail="Trader not found")

    analytics = await get_trader_analytics(trader_id)
    trader_data = profile.data[0]
    trader_data["display_name"] = _clean_display_name(trader_data.get("display_name", ""))
    trader_data["ai_model"] = _model_label(trader_data.get("ai_model", ""))
    return {
        "trader": trader_data,
        "analytics": analytics,
    }


@router.get("/comparison")
async def ai_comparison():
    """Compare all AI traders: by model, by personality, and individual."""
    return await get_ai_comparison()


@router.get("/benchmark")
async def benchmark(days: int = Query(90, ge=7, le=365)):
    """Compare AI traders against SPY buy-and-hold benchmark."""
    return await get_benchmark_comparison(days=days)


@router.get("/enhancement")
async def enhancement():
    """Compare AI trader performance before vs after signal enhancements."""
    return await get_enhancement_comparison()


@router.get("/pipeline-timings")
async def pipeline_timings(days: int = Query(7, ge=1, le=60)):
    """Per-trader pipeline timing data with trend aggregates.
    Used to watch for Cloud Run timeout risk as the fleet grows."""
    from datetime import date, timedelta
    db = get_supabase_admin()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    resp = (
        db.table("pipeline_timings")
        .select("run_date, phase, trader_name, model_key, personality_key, duration_seconds, trades_executed, status")
        .gte("run_date", cutoff)
        .order("run_date", desc=True)
        .execute()
    )
    rows = resp.data or []

    # Aggregate by run_date + phase
    by_day: dict = {}
    for r in rows:
        key = (r["run_date"], r["phase"])
        if key not in by_day:
            by_day[key] = {"count": 0, "ok": 0, "error": 0, "skipped": 0, "total_seconds": 0.0, "max_seconds": 0.0}
        agg = by_day[key]
        agg["count"] += 1
        agg[r["status"]] = agg.get(r["status"], 0) + 1
        dur = float(r.get("duration_seconds") or 0)
        agg["total_seconds"] += dur
        if dur > agg["max_seconds"]:
            agg["max_seconds"] = dur

    phase_trend = [
        {
            "run_date": day,
            "phase": phase,
            "trader_count": agg["count"],
            "ok": agg.get("ok", 0),
            "error": agg.get("error", 0),
            "skipped": agg.get("skipped", 0),
            "total_seconds": round(agg["total_seconds"], 2),
            "avg_seconds": round(agg["total_seconds"] / agg["count"], 2) if agg["count"] else 0,
            "max_seconds": round(agg["max_seconds"], 2),
        }
        for (day, phase), agg in sorted(by_day.items(), reverse=True)
    ]

    # Slowest individual runs (top 10)
    slowest = sorted(rows, key=lambda r: float(r.get("duration_seconds") or 0), reverse=True)[:10]

    return {
        "days": days,
        "row_count": len(rows),
        "phase_trend": phase_trend,
        "slowest": slowest,
    }


@router.get("/modules")
async def module_attribution(
    trader_id: str | None = Query(None, description="Scope to a single trader"),
):
    """Which toolkit modules correlate with winning trades?
    Shows win rate and P&L broken down by module for both buy and sell decisions."""
    return await get_module_attribution(trader_id=trader_id)


@router.get("/compare-periods")
async def compare_periods(
    a_start: str = Query(..., description="Period A start date (YYYY-MM-DD)"),
    a_end: str = Query(..., description="Period A end date (YYYY-MM-DD)"),
    b_start: str = Query(..., description="Period B start date (YYYY-MM-DD)"),
    b_end: str = Query(..., description="Period B end date (YYYY-MM-DD)"),
):
    """Compare AI trader performance across two arbitrary date ranges.
    Use to measure impact of any pipeline change."""
    return await get_period_comparison(a_start, a_end, b_start, b_end)


@router.get("/reflections")
async def reflection_trends(
    trader_id: str | None = Query(None, description="Scope to a single trader"),
):
    """Track reflection outcome scores over time. Shows whether AI traders
    are learning from past mistakes — weekly trends and per-trader improvement."""
    return await get_reflection_trends(trader_id=trader_id)


@router.get("/regimes")
async def regime_analysis(days: int = Query(90, ge=30, le=365)):
    """Detect market regimes (bull/bear/sideways/high vol) from SPY,
    then show each trader's win rate and P&L within each regime."""
    return await get_regime_analysis(days=days)


@router.get("/reasoning")
async def trade_reasoning(
    days: int = Query(7, ge=1, le=90, description="How many days back to look"),
    trader_id: str | None = Query(None, description="Filter to a single trader"),
    symbol: str | None = Query(None, description="Filter to a single symbol"),
):
    """AI trade reasoning viewer. Shows every AI trade with full reasoning,
    modules used, grouped by date. Flags convergence (3+ AIs making the same
    call on the same symbol) as potential herd behavior."""
    return await get_trade_reasoning(days=days, trader_id=trader_id, symbol=symbol)


@router.get("/convergence-quality")
async def convergence_quality_endpoint(
    days: int = Query(30, ge=7, le=180),
    outcome_horizon: int = Query(5, ge=3, le=14),
    threshold: int = Query(3, ge=2, le=10),
):
    """Measure whether AI trade convergence (3+ AIs buying the same stock)
    reflects smart consensus or herding. Compares convergence vs independent
    trade outcomes, analyzes module diversity within clusters, and tracks
    weekly trends."""
    return await get_convergence_quality(
        days=days, outcome_horizon=outcome_horizon,
        convergence_threshold=threshold,
    )


@router.get("/discipline")
async def discipline_scores():
    """Trade discipline scores for all AI traders — do they follow their strategies?"""
    return await get_all_discipline_scores()


@router.get("/discipline/{trader_id}")
async def trader_discipline(trader_id: str):
    """Discipline score for a single AI trader."""
    result = await compute_discipline_score(trader_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/model-deep-dive")
async def model_deep_dive(days: int = Query(7, ge=3, le=90)):
    """Fair model comparison over a recent window, eliminating duration bias.

    Computes return, win rate, and trade quality for each model over the
    last N days using snapshots — so all models are measured over the
    same calendar period regardless of when they started trading."""
    return await get_model_deep_dive(days=days)
