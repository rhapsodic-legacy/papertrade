from fastapi import APIRouter

from app.services.ai_trader import setup_ai_accounts, run_ai_trading

router = APIRouter()


@router.post("/setup")
async def setup_ai_traders():
    """One-time: create 15 AI trader accounts. Idempotent."""
    results = await setup_ai_accounts()
    created = sum(1 for r in results if r["status"] == "created")
    existing = sum(1 for r in results if r["status"] == "exists")
    errors = sum(1 for r in results if r["status"].startswith("error"))
    return {
        "message": f"AI traders: {created} created, {existing} already existed, {errors} errors",
        "details": results,
    }


@router.post("/trade/trigger")
async def trigger_ai_trading():
    """Daily cron: run all AI traders against today's market brief."""
    result = await run_ai_trading()
    return result
