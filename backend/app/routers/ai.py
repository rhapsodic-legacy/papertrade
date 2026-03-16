import asyncio

from fastapi import APIRouter, BackgroundTasks

from app.services.ai_trader import setup_ai_accounts, run_ai_trading

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


def _run_trading_sync():
    """Wrapper to run the async trading function from a sync context."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run_ai_trading())
    finally:
        loop.close()
