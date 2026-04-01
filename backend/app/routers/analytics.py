from fastapi import APIRouter, HTTPException, Query

from app.services.analytics import (
    get_trader_analytics, get_ai_comparison, get_model_deep_dive,
    get_module_attribution,
    get_reflection_trends, get_trade_reasoning, _model_label, _clean_display_name,
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


@router.get("/model-deep-dive")
async def model_deep_dive(days: int = Query(7, ge=3, le=90)):
    """Fair model comparison over a recent window, eliminating duration bias.

    Computes return, win rate, and trade quality for each model over the
    last N days using snapshots — so all models are measured over the
    same calendar period regardless of when they started trading."""
    return await get_model_deep_dive(days=days)
