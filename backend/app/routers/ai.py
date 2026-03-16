import asyncio

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.services.ai_trader import setup_ai_accounts, run_ai_trading, _get_ai_portfolio, PERSONALITIES
from app.services.ai_commentary import generate_commentary, get_commentary, get_commentary_dates
from app.services.supabase_client import get_supabase_admin

router = APIRouter()


@router.post("/setup")
async def setup_ai_traders():
    """One-time: create 10 AI trader accounts. Idempotent."""
    results = await setup_ai_accounts()
    created = sum(1 for r in results if r["status"] == "created")
    existing = sum(1 for r in results if r["status"] == "exists")
    errors = sum(1 for r in results if r["status"].startswith("error"))
    return {
        "message": f"AI traders: {created} created, {existing} already existed, {errors} errors",
        "details": results,
    }


@router.post("/trade/trigger")
async def trigger_ai_trading(background_tasks: BackgroundTasks):
    """Daily cron: run all AI traders against today's market brief.
    Returns immediately; trading runs in the background."""
    background_tasks.add_task(asyncio.to_thread, _run_trading_sync)
    return {"message": "AI trading triggered — running in background"}


@router.post("/commentary/trigger")
async def trigger_commentary(background_tasks: BackgroundTasks):
    """Daily cron: generate commentary for all AI traders.
    Returns immediately; generation runs in the background."""
    background_tasks.add_task(asyncio.to_thread, _run_commentary_sync)
    return {"message": "AI commentary generation triggered — running in background"}


@router.get("/commentary")
async def list_commentary(
    date: str | None = Query(None, description="Filter by date (YYYY-MM-DD)"),
    limit: int = Query(10, ge=1, le=50),
):
    """Get AI commentary entries. No auth required."""
    entries = await get_commentary(commentary_date=date, limit=limit)
    return {"entries": entries}


@router.get("/commentary/dates")
async def list_commentary_dates(limit: int = Query(30, ge=1, le=90)):
    """Get available commentary dates."""
    dates = await get_commentary_dates(limit=limit)
    return {"dates": dates}


@router.get("/traders")
async def list_ai_traders():
    """List all AI trader profiles. No auth required."""
    db = get_supabase_admin()
    resp = (
        db.table("profiles")
        .select("id, display_name, ai_model, is_ai")
        .eq("is_ai", True)
        .execute()
    )
    traders = []
    for p in resp.data:
        personality_key = None
        for pkey, pinfo in PERSONALITIES.items():
            if pinfo["name"] in p["display_name"]:
                personality_key = pkey
                break
        traders.append({
            "id": p["id"],
            "display_name": p["display_name"],
            "ai_model": p["ai_model"],
            "personality": personality_key,
        })
    return {"traders": traders}


@router.get("/traders/{trader_id}")
async def get_ai_trader_profile(trader_id: str):
    """Get full profile for a specific AI trader. No auth required."""
    db = get_supabase_admin()

    # Verify this is an AI trader
    profile_resp = (
        db.table("profiles")
        .select("id, display_name, ai_model, is_ai, cash_balance")
        .eq("id", trader_id)
        .eq("is_ai", True)
        .execute()
    )
    if not profile_resp.data:
        raise HTTPException(status_code=404, detail="AI trader not found")

    profile = profile_resp.data[0]

    # Determine personality
    personality_key = None
    for pkey, pinfo in PERSONALITIES.items():
        if pinfo["name"] in profile["display_name"]:
            personality_key = pkey
            break

    # Get portfolio with live prices
    portfolio = await _get_ai_portfolio(db, trader_id)

    # Get recent trades (last 50)
    trades_resp = (
        db.table("transactions")
        .select("symbol, asset_type, side, quantity, price, total, created_at")
        .eq("user_id", trader_id)
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    )

    # Get recent commentary (last 10)
    commentary_resp = (
        db.table("ai_commentary")
        .select("commentary, trades_summary, commentary_date")
        .eq("user_id", trader_id)
        .order("commentary_date", desc=True)
        .limit(10)
        .execute()
    )

    # Get snapshots for chart (last 30 days)
    snapshots_resp = (
        db.table("portfolio_snapshots")
        .select("snapshot_date, total_value")
        .eq("user_id", trader_id)
        .order("snapshot_date", desc=False)
        .limit(30)
        .execute()
    )

    invested_value = sum(p["market_value"] for p in portfolio["positions"])
    total_value = portfolio["cash"] + invested_value

    return {
        "display_name": profile["display_name"],
        "ai_model": profile["ai_model"],
        "personality": personality_key,
        "personality_description": PERSONALITIES[personality_key]["prompt"] if personality_key else None,
        "cash_balance": portfolio["cash"],
        "invested_value": round(invested_value, 2),
        "total_value": round(total_value, 2),
        "positions": portfolio["positions"],
        "trades": trades_resp.data,
        "commentary": commentary_resp.data,
        "snapshots": snapshots_resp.data,
    }


def _run_trading_sync():
    """Wrapper to run the async trading function from a sync context."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run_ai_trading())
    finally:
        loop.close()


def _run_commentary_sync():
    """Wrapper to run the async commentary function from a sync context."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(generate_commentary())
    finally:
        loop.close()
