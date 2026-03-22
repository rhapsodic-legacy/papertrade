import asyncio

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.services.ai_trader import setup_ai_accounts, run_ai_trading, _get_ai_portfolio, PERSONALITIES
from app.services.ai_commentary import generate_commentary, get_commentary, get_commentary_dates, get_trader_commentary
from app.services.analytics import _model_label, _clean_display_name
from app.services.rag_toolkit import get_personality_toolkit_info
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


@router.post("/fix-display-names")
async def fix_display_names():
    """One-time: rename 'Llama' to 'GPT' in all DB display_name fields."""
    db = get_supabase_admin()
    fixed = {"profiles": 0, "ai_commentary": 0}

    # Fix profiles table
    profiles = db.table("profiles").select("id, display_name").like("display_name", "%Llama%").execute()
    for p in profiles.data:
        new_name = _clean_display_name(p["display_name"])
        db.table("profiles").update({"display_name": new_name}).eq("id", p["id"]).execute()
        fixed["profiles"] += 1

    # Fix ai_commentary table
    commentary = db.table("ai_commentary").select("id, display_name").like("display_name", "%Llama%").execute()
    for c in commentary.data:
        new_name = _clean_display_name(c["display_name"])
        db.table("ai_commentary").update({"display_name": new_name}).eq("id", c["id"]).execute()
        fixed["ai_commentary"] += 1

    return {"message": "Display names fixed", "updated": fixed}


@router.post("/trade/trigger")
async def trigger_ai_trading(
    background_tasks: BackgroundTasks,
    session: str = Query("close", description="Trading session: morning, midday, or close"),
):
    """Cron: run all AI traders against today's market brief.
    Session determines trade focus (morning=position, midday=adjust, close=risk mgmt).
    Returns immediately; trading runs in the background."""
    if session not in ("morning", "midday", "close"):
        session = "close"
    background_tasks.add_task(asyncio.to_thread, _run_trading_sync, session)
    return {"message": f"AI trading triggered ({session} session) — running in background"}


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


@router.get("/trades/feed")
async def ai_trade_feed(
    personality: str | None = Query(None, description="Filter by personality key"),
    model: str | None = Query(None, description="Filter by AI model"),
    symbol: str | None = Query(None, description="Filter by symbol"),
    limit: int = Query(50, ge=1, le=200),
):
    """Recent AI trades with reasoning, for the Learn from AI page. No auth required."""
    db = get_supabase_admin()

    # Get all AI trader profiles
    profiles_resp = (
        db.table("profiles")
        .select("id, display_name, ai_model, is_ai")
        .eq("is_ai", True)
        .execute()
    )

    # Build profile lookup with personality
    profile_map = {}
    for p in profiles_resp.data:
        personality_key = None
        for pkey, pinfo in PERSONALITIES.items():
            if pinfo["name"] in p["display_name"]:
                personality_key = pkey
                break
        profile_map[p["id"]] = {
            "display_name": _clean_display_name(p["display_name"]),
            "ai_model": p["ai_model"],
            "personality": personality_key,
        }

    # Filter trader IDs by personality/model if requested
    trader_ids = list(profile_map.keys())
    if personality:
        trader_ids = [
            uid for uid, info in profile_map.items()
            if info["personality"] == personality
        ]
    if model:
        trader_ids = [
            uid for uid in trader_ids
            if profile_map[uid]["ai_model"] and model.lower() in profile_map[uid]["ai_model"].lower()
        ]

    if not trader_ids:
        return {"trades": []}

    # Fetch recent transactions with reasoning
    query = (
        db.table("transactions")
        .select("user_id, symbol, asset_type, side, quantity, price, total, created_at, reasoning")
        .in_("user_id", trader_ids)
        .not_.is_("reasoning", "null")
        .order("created_at", desc=True)
        .limit(limit)
    )
    if symbol:
        query = query.eq("symbol", symbol.upper())

    trades_resp = query.execute()

    # Enrich with trader info
    trades = []
    for t in trades_resp.data:
        info = profile_map.get(t["user_id"], {})
        trades.append({
            "trader_name": info.get("display_name", "Unknown"),
            "personality": info.get("personality"),
            "model": _model_label(info.get("ai_model", "")),
            "symbol": t["symbol"],
            "asset_type": t["asset_type"],
            "side": t["side"],
            "quantity": float(t["quantity"]),
            "price": float(t["price"]),
            "total": float(t["total"]),
            "reasoning": t["reasoning"],
            "created_at": t["created_at"],
        })

    return {"trades": trades}


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
            "display_name": _clean_display_name(p["display_name"]),
            "ai_model": _model_label(p["ai_model"]),
            "personality": personality_key,
        })
    return {"traders": traders}


@router.get("/traders/{trader_id}/commentary")
async def get_trader_commentary_history(
    trader_id: str,
    limit: int = Query(30, ge=1, le=90),
):
    """Get full commentary history for a specific AI trader."""
    entries = await get_trader_commentary(user_id=trader_id, limit=limit)
    return {"entries": entries}


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
        .select("symbol, asset_type, side, quantity, price, total, created_at, reasoning")
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

    toolkit_config = PERSONALITIES[personality_key].get("toolkit", []) if personality_key else []

    return {
        "display_name": _clean_display_name(profile["display_name"]),
        "ai_model": _model_label(profile["ai_model"]),
        "personality": personality_key,
        "personality_description": PERSONALITIES[personality_key]["prompt"] if personality_key else None,
        "toolkit": get_personality_toolkit_info(personality_key, toolkit_config) if personality_key else [],
        "cash_balance": portfolio["cash"],
        "invested_value": round(invested_value, 2),
        "total_value": round(total_value, 2),
        "positions": portfolio["positions"],
        "trades": trades_resp.data,
        "commentary": commentary_resp.data,
        "snapshots": snapshots_resp.data,
    }


def _run_trading_sync(session: str = "close"):
    """Wrapper to run the async trading function from a sync context."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run_ai_trading(session=session))
    finally:
        loop.close()


def _run_commentary_sync():
    """Wrapper to run the async commentary function from a sync context."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(generate_commentary())
    finally:
        loop.close()
