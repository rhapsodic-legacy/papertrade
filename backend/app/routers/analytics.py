from fastapi import APIRouter, HTTPException, Query

from app.services.analytics import get_trader_analytics, get_ai_comparison, _model_label, _clean_display_name
from app.services.backtest import get_benchmark_comparison, get_enhancement_comparison
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
