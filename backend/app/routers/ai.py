import asyncio

from fastapi import APIRouter, BackgroundTasks, Query

from app.services.ai_trader import setup_ai_accounts, run_ai_trading
from app.services.ai_commentary import generate_commentary, get_commentary, get_commentary_dates

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
