import asyncio
import json
from datetime import date, timedelta

from app.config import get_settings
from app.services.ai_trader import (
    PERSONALITIES,
    MODELS,
    CUSTOM_TRADER_MODEL,
    CUSTOM_RISK_PRESETS,
    resolve_personality_key,
    _call_gemini,
    _call_mistral,
    _call_groq,
    _call_nvidia_nim,
    _get_ai_portfolio,
    _record_pipeline_timing,
)
from app.services.supabase_client import get_supabase_admin
from app.services.analytics import _clean_display_name, _model_label

COMMENTARY_SYSTEM = """\
You are an AI trader writing a short daily blog post about your trading activity.
You will receive:
1. Your personality/strategy description
2. Your trades from today (or that you had no trades)
3. Your current portfolio

Write your response in EXACTLY this format:
HEADLINE: <a short, punchy headline summarizing your day in 8 words or less>

<2-4 paragraphs of commentary>

Commentary rules:
- Write in the FIRST PERSON explaining what you did and WHY
- Connect decisions to market conditions
- Share how you feel about your portfolio
- Mention what you are watching for tomorrow
- Stay in character with your personality
- Be conversational and engaging — this is a blog post, not a report
- Use specific numbers (prices, quantities) when referencing your trades
- Keep commentary under 250 words
- Do NOT use markdown headers or bullet points — just flowing paragraphs
- Do NOT start with "Today," — vary your openings
"""


async def generate_commentary() -> dict:
    """Generate daily commentary for all AI traders. Returns summary."""
    db = get_supabase_admin()
    today = date.today()

    # Get all AI trader profiles
    ai_profiles = (
        db.table("profiles")
        .select("id, display_name, ai_model, is_ai")
        .eq("is_ai", True)
        .execute()
    )

    if not ai_profiles.data:
        return {"error": "No AI traders found."}

    from datetime import datetime, timezone
    results = []
    for profile in ai_profiles.data:
        started_at = datetime.now(timezone.utc)
        user_id = profile["id"]
        display_name = profile["display_name"]
        model_key = profile.get("ai_model", "")

        # Determine personality from display name (or custom trader config)
        personality_key = None
        custom_personality = None
        personality_key = resolve_personality_key(display_name)

        if not personality_key and model_key == "custom":
            try:
                ct = db.table("custom_traders").select("*").eq("profile_id", user_id).eq("is_active", True).single().execute()
                if ct.data:
                    cfg = ct.data
                    personality_key = "custom"
                    custom_personality = {
                        "name": cfg["name"],
                        "prompt": cfg["strategy_prompt"],
                    }
            except Exception:
                pass

        if not personality_key or (model_key not in MODELS and model_key != "custom"):
            results.append({
                "trader": display_name,
                "status": "skipped",
                "reason": "unknown personality or model",
            })
            _record_pipeline_timing(
                db, phase="commentary", user_id=user_id, display_name=display_name,
                model_key=model_key, personality_key=personality_key,
                started_at=started_at, completed_at=datetime.now(timezone.utc),
                status="skipped", error_message="unknown personality or model",
            )
            continue

        # Check if commentary already exists for today
        existing = (
            db.table("ai_commentary")
            .select("id")
            .eq("user_id", user_id)
            .eq("commentary_date", today.isoformat())
            .execute()
        )
        if existing.data:
            results.append({"trader": display_name, "status": "already_exists"})
            _record_pipeline_timing(
                db, phase="commentary", user_id=user_id, display_name=display_name,
                model_key=model_key, personality_key=personality_key,
                started_at=started_at, completed_at=datetime.now(timezone.utc),
                status="skipped", error_message="already exists",
            )
            continue

        try:
            # Get today's trades for this trader
            trades_resp = (
                db.table("transactions")
                .select("symbol, asset_type, side, quantity, price, total, created_at")
                .eq("user_id", user_id)
                .gte("created_at", f"{today.isoformat()}T00:00:00")
                .order("created_at", desc=False)
                .execute()
            )
            trades = trades_resp.data or []

            # Get current portfolio
            portfolio = await _get_ai_portfolio(db, user_id)

            # Build the prompt
            personality = custom_personality if personality_key == "custom" else PERSONALITIES[personality_key]
            model_cfg = CUSTOM_TRADER_MODEL if model_key == "custom" else MODELS[model_key]

            trades_text = "No trades today." if not trades else json.dumps(trades, indent=2)
            positions_text = (
                json.dumps(portfolio["positions"], indent=2)
                if portfolio["positions"]
                else "No positions."
            )

            user_msg = f"""## Your Strategy
{personality['prompt']}

## Your Trades Today ({today.isoformat()})
{trades_text}

## Your Current Portfolio
Cash: ${portfolio['cash']:,.2f}
Positions:
{positions_text}

Write your daily commentary blog post."""

            from app.services.llm import call_llm
            settings = get_settings()

            # Commentary can run locally (saves 20 API calls/day)
            # Falls back to cloud per-model if Ollama unavailable
            if settings.ollama_base_url:
                raw = await call_llm(
                    system=COMMENTARY_SYSTEM,
                    user_msg=user_msg,
                    tier="local",
                    temperature=0.7,
                    max_tokens=2048,
                )
            else:
                api_type = model_cfg["api"]
                if api_type == "gemini":
                    if not settings.gemini_api_key:
                        raise Exception("GEMINI_API_KEY not configured")
                    raw = await _call_gemini(
                        model_cfg["model_id"], COMMENTARY_SYSTEM, user_msg,
                        settings.gemini_api_key,
                    )
                elif api_type == "mistral":
                    key_field = model_cfg.get("api_key_field", "mistral_api_key")
                    api_key = getattr(settings, key_field, "") or settings.mistral_api_key
                    if not api_key:
                        raise Exception(f"{key_field.upper()} not configured")
                    raw = await _call_mistral(
                        model_cfg["model_id"], COMMENTARY_SYSTEM, user_msg,
                        api_key,
                    )
                elif api_type == "groq":
                    if not settings.groq_api_key:
                        raise Exception("GROQ_API_KEY not configured")
                    raw = await _call_groq(
                        model_cfg["model_id"], COMMENTARY_SYSTEM, user_msg,
                        settings.groq_api_key,
                    )
                elif api_type == "nvidia":
                    if not settings.nvidia_api_key:
                        raise Exception("NVIDIA_API_KEY not configured")
                    raw = await _call_nvidia_nim(
                        model_cfg["model_id"], COMMENTARY_SYSTEM, user_msg,
                        settings.nvidia_api_key,
                    )
                else:
                    raise Exception(f"Unknown API: {api_type}")

            # Parse headline from response
            text = raw.strip()
            headline = ""
            commentary_body = text
            if text.upper().startswith("HEADLINE:"):
                parts = text.split("\n", 1)
                headline = parts[0].replace("HEADLINE:", "").replace("Headline:", "").strip()
                commentary_body = parts[1].strip() if len(parts) > 1 else text

            # Store commentary
            trades_summary = [
                {
                    "symbol": t["symbol"],
                    "side": t["side"],
                    "quantity": t["quantity"],
                    "price": t["price"],
                }
                for t in trades
            ]

            # Store headline as first line separated by a marker
            stored_commentary = f"HEADLINE:{headline}\n{commentary_body}" if headline else commentary_body

            db.table("ai_commentary").insert({
                "user_id": user_id,
                "commentary_date": today.isoformat(),
                "display_name": display_name,
                "personality": personality_key,
                "model": model_key,
                "commentary": stored_commentary,
                "trades_summary": json.dumps(trades_summary),
            }).execute()

            results.append({
                "trader": display_name,
                "status": "ok",
                "words": len(raw.split()),
            })
            _record_pipeline_timing(
                db, phase="commentary", user_id=user_id, display_name=display_name,
                model_key=model_key, personality_key=personality_key,
                started_at=started_at, completed_at=datetime.now(timezone.utc),
                status="ok",
            )

        except Exception as e:
            results.append({
                "trader": display_name,
                "status": "error",
                "error": str(e)[:200],
            })
            _record_pipeline_timing(
                db, phase="commentary", user_id=user_id, display_name=display_name,
                model_key=model_key, personality_key=personality_key,
                started_at=started_at, completed_at=datetime.now(timezone.utc),
                status="error", error_message=str(e),
            )

        # Rate limit: same 35s delay as trading
        await asyncio.sleep(35)

    return {
        "date": today.isoformat(),
        "traders_processed": len(results),
        "results": results,
    }


async def get_commentary(
    commentary_date: str | None = None,
    limit: int = 10,
    summary_type: str = "daily",
) -> list[dict]:
    """Fetch commentary entries. Defaults to latest daily entries available.
    summary_type filters daily vs weekly vs monthly journal roll-ups."""
    db = get_supabase_admin()

    query = db.table("ai_commentary").select(
        "display_name, personality, model, commentary, trades_summary, "
        "commentary_date, summary_type, period_start, period_end"
    ).eq("summary_type", summary_type)

    if commentary_date:
        query = query.eq("commentary_date", commentary_date).limit(50)
    else:
        query = query.order("commentary_date", desc=True).limit(limit)

    resp = query.execute()

    entries = []
    for row in resp.data:
        trades_summary = row["trades_summary"]
        if isinstance(trades_summary, str):
            trades_summary = json.loads(trades_summary)

        # Parse headline from stored commentary
        commentary_text = row["commentary"]
        headline = ""
        if commentary_text.startswith("HEADLINE:"):
            parts = commentary_text.split("\n", 1)
            headline = parts[0].replace("HEADLINE:", "").strip()
            commentary_text = parts[1].strip() if len(parts) > 1 else commentary_text
        elif not headline:
            # Fallback for old entries: use first sentence as headline
            first_sentence = commentary_text.split(". ")[0]
            if len(first_sentence) < 100:
                headline = first_sentence.rstrip(".")

        entries.append({
            "display_name": _clean_display_name(row["display_name"]),
            "personality": row["personality"],
            "model": _model_label(row["model"]) if row["model"] else row["model"],
            "headline": headline,
            "commentary": commentary_text,
            "trades_summary": trades_summary,
            "date": row["commentary_date"],
            "summary_type": row.get("summary_type", "daily"),
            "period_start": row.get("period_start"),
            "period_end": row.get("period_end"),
        })

    return entries


async def get_trader_commentary(
    user_id: str,
    limit: int = 30,
    summary_type: str = "daily",
) -> list[dict]:
    """Fetch commentary history for a specific AI trader, by summary type."""
    db = get_supabase_admin()
    resp = (
        db.table("ai_commentary")
        .select("display_name, personality, model, commentary, trades_summary, "
                "commentary_date, summary_type, period_start, period_end")
        .eq("user_id", user_id)
        .eq("summary_type", summary_type)
        .order("commentary_date", desc=True)
        .limit(limit)
        .execute()
    )

    entries = []
    for row in resp.data:
        trades_summary = row["trades_summary"]
        if isinstance(trades_summary, str):
            trades_summary = json.loads(trades_summary)

        commentary_text = row["commentary"]
        headline = ""
        if commentary_text.startswith("HEADLINE:"):
            parts = commentary_text.split("\n", 1)
            headline = parts[0].replace("HEADLINE:", "").strip()
            commentary_text = parts[1].strip() if len(parts) > 1 else commentary_text
        elif not headline:
            first_sentence = commentary_text.split(". ")[0]
            if len(first_sentence) < 100:
                headline = first_sentence.rstrip(".")

        entries.append({
            "display_name": _clean_display_name(row["display_name"]),
            "personality": row["personality"],
            "model": _model_label(row["model"]) if row["model"] else row["model"],
            "headline": headline,
            "commentary": commentary_text,
            "trades_summary": trades_summary,
            "date": row["commentary_date"],
            "summary_type": row.get("summary_type", "daily"),
            "period_start": row.get("period_start"),
            "period_end": row.get("period_end"),
        })

    return entries


async def get_commentary_dates(limit: int = 30) -> list[str]:
    """Get available commentary dates (most recent first)."""
    db = get_supabase_admin()
    resp = (
        db.table("ai_commentary")
        .select("commentary_date")
        .order("commentary_date", desc=True)
        .limit(limit * 10)  # overfetch since we deduplicate
        .execute()
    )
    seen = set()
    dates = []
    for row in resp.data:
        d = row["commentary_date"]
        if d not in seen:
            seen.add(d)
            dates.append(d)
            if len(dates) >= limit:
                break
    return dates
