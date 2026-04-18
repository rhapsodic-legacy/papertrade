from fastapi import APIRouter, HTTPException, Query

from app.services.ai_trader import setup_ai_accounts, run_ai_trading, _get_ai_portfolio, PERSONALITIES
from app.services.ai_commentary import generate_commentary, get_commentary, get_commentary_dates, get_trader_commentary
from app.services.analytics import _model_label, _clean_display_name
from app.services.rag_toolkit import get_personality_toolkit_info, RAG_MODULES
from app.services.supabase_client import get_supabase_admin

router = APIRouter()


def _enrich_modules(modules_json: str | None) -> list[dict]:
    """Parse modules_used JSON string and attach module metadata."""
    if not modules_json:
        return []
    import json
    try:
        modules = json.loads(modules_json)
    except (json.JSONDecodeError, TypeError):
        return []
    return [
        {
            "module": m,
            "label": RAG_MODULES[m]["label"],
            "colour": RAG_MODULES[m]["color"],
        }
        for m in modules
        if m in RAG_MODULES
    ]


@router.post("/setup")
async def setup_ai_traders():
    """One-time: create 10 AI trader accounts. Idempotent."""
    results = await setup_ai_accounts()
    created = sum(1 for r in results if r["status"] == "created")
    existing = sum(1 for r in results if "exists" in r["status"])
    renamed = sum(1 for r in results if "renamed" in r["status"])
    errors = sum(1 for r in results if r["status"].startswith("error"))
    return {
        "message": f"AI traders: {created} created, {existing} already existed ({renamed} renamed), {errors} errors",
        "details": results,
    }


@router.post("/fix-display-names")
async def fix_display_names():
    """One-time: rename legacy model names to current labels in all DB display_name fields."""
    db = get_supabase_admin()
    fixed = {"profiles": 0, "ai_commentary": 0}

    # Fix profiles table — match legacy names
    for pattern in ["%Llama%", "%GPT%", "%Groq%"]:
        profiles = db.table("profiles").select("id, display_name").like("display_name", pattern).execute()
        for p in profiles.data:
            new_name = _clean_display_name(p["display_name"])
            if new_name != p["display_name"]:
                db.table("profiles").update({"display_name": new_name}).eq("id", p["id"]).execute()
                fixed["profiles"] += 1

    # Fix ai_commentary table
    for pattern in ["%Llama%", "%GPT%", "%Groq%"]:
        commentary = db.table("ai_commentary").select("id, display_name").like("display_name", pattern).execute()
        for c in commentary.data:
            new_name = _clean_display_name(c["display_name"])
            if new_name != c["display_name"]:
                db.table("ai_commentary").update({"display_name": new_name}).eq("id", c["id"]).execute()
                fixed["ai_commentary"] += 1

    return {"message": "Display names fixed", "updated": fixed}


@router.post("/pipeline/trigger")
async def trigger_full_pipeline(
    session: str = Query("close", description="Trading session: morning, midday, or close"),
    steps: str = Query("all", description="Comma-separated steps to run: brief,reflections,trading,commentary or 'all'"),
):
    """Daily pipeline: brief → reflections → trading → commentary.

    Use steps parameter to run a subset (e.g. steps=brief,reflections for
    phase 1, then steps=trading,commentary for phase 2 after local Gemma
    preprocessing enriches the brief).

    Runs synchronously within the request so Cloud Run keeps the instance
    alive for the full duration."""
    import logging
    from app.services.market_brief import compile_market_brief
    from app.services.reflection import run_reflections

    logger = logging.getLogger(__name__)

    if session not in ("morning", "midday", "close"):
        session = "close"

    run_steps = {"brief", "reflections", "trading", "commentary"} if steps == "all" else {s.strip() for s in steps.split(",")}

    results = {"session": session, "steps": {}, "requested": sorted(run_steps)}
    print(f"[PIPELINE] Starting pipeline (session={session}, steps={sorted(run_steps)})")

    if "brief" in run_steps:
        print("[PIPELINE] Step 1/4: Compiling market brief...")
        try:
            await compile_market_brief()
            results["steps"]["brief"] = "ok"
            print("[PIPELINE] Market brief complete")
        except Exception as e:
            logger.error("Pipeline brief failed: %s", e, exc_info=True)
            results["steps"]["brief"] = f"error: {e}"
            print(f"[PIPELINE ERROR] Brief failed: {e}")

    if "reflections" in run_steps:
        print("[PIPELINE] Step 2/4: Running trade reflections...")
        try:
            result = await run_reflections()
            results["steps"]["reflections"] = f"ok: {result}"
            print(f"[PIPELINE] Reflections complete: {result}")
        except Exception as e:
            logger.error("Pipeline reflections failed: %s", e, exc_info=True)
            results["steps"]["reflections"] = f"error: {e}"
            print(f"[PIPELINE ERROR] Reflections failed: {e}")

    if "trading" in run_steps:
        print(f"[PIPELINE] Step 3/4: Running AI trading ({session})...")
        try:
            await run_ai_trading(session=session)
            results["steps"]["trading"] = "ok"
            print("[PIPELINE] Trading complete")
        except Exception as e:
            logger.error("Pipeline trading failed: %s", e, exc_info=True)
            results["steps"]["trading"] = f"error: {e}"
            print(f"[PIPELINE ERROR] Trading failed: {e}")

    if "commentary" in run_steps:
        print("[PIPELINE] Step 4/4: Generating commentary...")
        try:
            await generate_commentary()
            results["steps"]["commentary"] = "ok"
            print("[PIPELINE] Commentary complete")
        except Exception as e:
            logger.error("Pipeline commentary failed: %s", e, exc_info=True)
            results["steps"]["commentary"] = f"error: {e}"
            print(f"[PIPELINE ERROR] Commentary failed: {e}")

    print("[PIPELINE] Pipeline finished")
    return {"message": "Pipeline complete", "results": results}


@router.post("/trade/trigger")
async def trigger_ai_trading(
    session: str = Query("close", description="Trading session: morning, midday, or close"),
):
    """Run all AI traders against today's market brief.
    Session determines trade focus (morning=position, midday=adjust, close=risk mgmt).
    Runs synchronously within the request (Cloud Run keeps instance alive)."""
    if session not in ("morning", "midday", "close"):
        session = "close"
    result = await run_ai_trading(session=session)
    return {"message": f"AI trading complete ({session} session)", "result": result}


@router.post("/reflection/trigger")
async def trigger_reflections():
    """Review settled trades and generate reflection lessons.
    Run before trading so today's decisions benefit from past reflections."""
    from app.services.reflection import run_reflections
    result = await run_reflections()
    return {"message": "Trade reflection complete", "result": result}


@router.post("/commentary/trigger")
async def trigger_commentary():
    """Generate commentary for all AI traders."""
    result = await generate_commentary()
    return {"message": "AI commentary generation complete", "result": result}


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
        .select("user_id, symbol, asset_type, side, quantity, price, total, created_at, reasoning, modules_used")
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
            "modules_used": _enrich_modules(t.get("modules_used")),
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

    # Determine personality (built-in or custom)
    personality_key = None
    custom_config = None
    for pkey, pinfo in PERSONALITIES.items():
        if pinfo["name"] in profile["display_name"]:
            personality_key = pkey
            break

    if not personality_key and profile.get("ai_model") == "custom":
        try:
            ct = db.table("custom_traders").select("*").eq("profile_id", trader_id).eq("is_active", True).single().execute()
            if ct.data:
                personality_key = "custom"
                custom_config = ct.data
        except Exception:
            pass

    # Get portfolio with live prices
    portfolio = await _get_ai_portfolio(db, trader_id)

    # Get recent trades (last 50)
    trades_resp = (
        db.table("transactions")
        .select("symbol, asset_type, side, quantity, price, total, created_at, reasoning, modules_used")
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

    if personality_key == "custom" and custom_config:
        toolkit_config = [{"module": m, "weight": 10 - i} for i, m in enumerate(custom_config.get("toolkit_modules", []))]
        personality_desc = custom_config.get("strategy_prompt", "")
    elif personality_key and personality_key in PERSONALITIES:
        toolkit_config = PERSONALITIES[personality_key].get("toolkit", [])
        personality_desc = PERSONALITIES[personality_key]["prompt"]
    else:
        toolkit_config = []
        personality_desc = None

    return {
        "display_name": _clean_display_name(profile["display_name"]),
        "ai_model": _model_label(profile["ai_model"]),
        "personality": personality_key,
        "personality_description": personality_desc,
        "toolkit": get_personality_toolkit_info(personality_key, toolkit_config) if personality_key else [],
        "is_custom": personality_key == "custom",
        "cash_balance": portfolio["cash"],
        "invested_value": round(invested_value, 2),
        "total_value": round(total_value, 2),
        "positions": portfolio["positions"],
        "trades": [
            {**t, "modules_used": _enrich_modules(t.get("modules_used"))}
            for t in trades_resp.data
        ],
        "commentary": commentary_resp.data,
        "snapshots": snapshots_resp.data,
    }


@router.get("/diagnostics")
async def pipeline_diagnostics():
    """Show today's trade activity grouped by AI model — quick health check."""
    from datetime import date

    db = get_supabase_admin()
    today = date.today().isoformat()

    # All AI profiles
    profiles_resp = (
        db.table("profiles")
        .select("id, display_name, ai_model, is_ai")
        .eq("is_ai", True)
        .execute()
    )
    profiles_by_id = {p["id"]: p for p in (profiles_resp.data or [])}

    # Today's trades by AI traders
    trades_resp = (
        db.table("transactions")
        .select("user_id, symbol, side, quantity, price, created_at")
        .in_("user_id", list(profiles_by_id.keys()))
        .gte("created_at", f"{today}T00:00:00")
        .order("created_at", desc=False)
        .execute()
    )

    # Group by model
    by_model: dict[str, list] = {}
    for t in (trades_resp.data or []):
        profile = profiles_by_id.get(t["user_id"], {})
        model = profile.get("ai_model", "unknown")
        display = _clean_display_name(profile.get("display_name", "?"))
        by_model.setdefault(model, []).append({
            "trader": display,
            "symbol": t["symbol"],
            "side": t["side"],
            "qty": t["quantity"],
            "price": t["price"],
            "time": t["created_at"],
        })

    # Summary per model
    summary = {}
    for model, trades in by_model.items():
        traders_active = len(set(t["trader"] for t in trades))
        summary[model] = {
            "trades_today": len(trades),
            "active_traders": traders_active,
            "trades": trades,
        }

    # List models with zero trades
    all_models = set(p.get("ai_model", "unknown") for p in profiles_resp.data or [])
    for m in all_models:
        if m not in summary:
            summary[m] = {"trades_today": 0, "active_traders": 0, "trades": []}

    return {
        "date": today,
        "total_ai_profiles": len(profiles_by_id),
        "total_trades_today": len(trades_resp.data or []),
        "by_model": summary,
    }


@router.get("/diagnostics/ping")
async def ping_providers():
    """Send a tiny request to each LLM provider and report status."""
    import httpx
    from app.config import get_settings

    settings = get_settings()
    results = {}

    # Groq
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.groq_api_key}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": "Say OK"}],
                    "max_tokens": 5,
                },
            )
            if resp.status_code == 200:
                results["groq"] = {"status": "ok", "response": resp.json()["choices"][0]["message"]["content"][:50]}
            else:
                results["groq"] = {"status": "error", "code": resp.status_code, "body": resp.text[:300]}
    except Exception as e:
        results["groq"] = {"status": "exception", "error": str(e)[:200]}

    # Mistral
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.mistral_api_key}", "Content-Type": "application/json"},
                json={
                    "model": "mistral-large-latest",
                    "messages": [{"role": "user", "content": "Say OK"}],
                    "max_tokens": 5,
                },
            )
            if resp.status_code == 200:
                results["mistral"] = {"status": "ok", "response": resp.json()["choices"][0]["message"]["content"][:50]}
            else:
                results["mistral"] = {"status": "error", "code": resp.status_code, "body": resp.text[:300]}
    except Exception as e:
        results["mistral"] = {"status": "exception", "error": str(e)[:200]}

    # Mistral Key 2
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.mistral_api_key_2}", "Content-Type": "application/json"},
                json={
                    "model": "mistral-large-latest",
                    "messages": [{"role": "user", "content": "Say OK"}],
                    "max_tokens": 5,
                },
            )
            if resp.status_code == 200:
                results["mistral_2"] = {"status": "ok", "response": resp.json()["choices"][0]["message"]["content"][:50]}
            else:
                results["mistral_2"] = {"status": "error", "code": resp.status_code, "body": resp.text[:300]}
    except Exception as e:
        results["mistral_2"] = {"status": "exception", "error": str(e)[:200]}

    # Gemini Flash (quick check)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={settings.gemini_api_key}",
                json={"contents": [{"parts": [{"text": "Say OK"}]}], "generationConfig": {"maxOutputTokens": 5}},
            )
            if resp.status_code == 200:
                results["gemini"] = {"status": "ok"}
            else:
                body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:300]
                results["gemini"] = {"status": "error", "code": resp.status_code, "body": body}
    except Exception as e:
        results["gemini"] = {"status": "exception", "error": str(e)[:200]}

    return results


