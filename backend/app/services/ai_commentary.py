import asyncio
import json
from datetime import date, timedelta

from app.config import get_settings
from app.services.ai_trader import (
    PERSONALITIES,
    MODELS,
    _call_gemini,
    _call_mistral,
    _call_cerebras,
    _get_ai_portfolio,
)
from app.services.supabase_client import get_supabase_admin

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

    results = []
    for profile in ai_profiles.data:
        user_id = profile["id"]
        display_name = profile["display_name"]
        model_key = profile.get("ai_model", "")

        # Determine personality from display name
        personality_key = None
        for pkey, pinfo in PERSONALITIES.items():
            if pinfo["name"] in display_name:
                personality_key = pkey
                break

        if not personality_key or model_key not in MODELS:
            results.append({
                "trader": display_name,
                "status": "skipped",
                "reason": "unknown personality or model",
            })
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
            personality = PERSONALITIES[personality_key]
            model_cfg = MODELS[model_key]

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

            settings = get_settings()
            api_type = model_cfg["api"]

            if api_type == "gemini":
                if not settings.gemini_api_key:
                    raise Exception("GEMINI_API_KEY not configured")
                raw = await _call_gemini(
                    model_cfg["model_id"], COMMENTARY_SYSTEM, user_msg,
                    settings.gemini_api_key,
                )
            elif api_type == "mistral":
                if not settings.mistral_api_key:
                    raise Exception("MISTRAL_API_KEY not configured")
                raw = await _call_mistral(
                    model_cfg["model_id"], COMMENTARY_SYSTEM, user_msg,
                    settings.mistral_api_key,
                )
            elif api_type == "cerebras":
                if not settings.cerebras_api_key:
                    raise Exception("CEREBRAS_API_KEY not configured")
                raw = await _call_cerebras(
                    model_cfg["model_id"], COMMENTARY_SYSTEM, user_msg,
                    settings.cerebras_api_key,
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

        except Exception as e:
            results.append({
                "trader": display_name,
                "status": "error",
                "error": str(e)[:200],
            })

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
) -> list[dict]:
    """Fetch commentary entries. Defaults to latest date available."""
    db = get_supabase_admin()

    query = db.table("ai_commentary").select(
        "display_name, personality, model, commentary, trades_summary, commentary_date"
    )

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
            "display_name": row["display_name"],
            "personality": row["personality"],
            "model": row["model"],
            "headline": headline,
            "commentary": commentary_text,
            "trades_summary": trades_summary,
            "date": row["commentary_date"],
        })

    return entries


async def get_trader_commentary(
    user_id: str,
    limit: int = 30,
) -> list[dict]:
    """Fetch commentary history for a specific AI trader."""
    db = get_supabase_admin()
    resp = (
        db.table("ai_commentary")
        .select("display_name, personality, model, commentary, trades_summary, commentary_date")
        .eq("user_id", user_id)
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
            "display_name": row["display_name"],
            "personality": row["personality"],
            "model": row["model"],
            "headline": headline,
            "commentary": commentary_text,
            "trades_summary": trades_summary,
            "date": row["commentary_date"],
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
