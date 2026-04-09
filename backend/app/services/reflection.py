"""
Trade reflection loop — LLM reviews settled trades and extracts lessons.

Runs daily before trading so today's decisions benefit from past reflections.
Single Groq batch call reviews all trades from 3-5 days ago where price moved >3%.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import httpx

from app.config import get_settings
from app.services.supabase_client import get_supabase_admin
from app.services.market_data import get_quote

REFLECTION_SYSTEM = (
    "You are a trade performance analyst reviewing settled trades for AI trading "
    "personalities. For each trade, assess whether the decision was good or bad given "
    "what happened, and extract a concise lesson. Respond ONLY with valid JSON."
)


def _get_settled_trades(
    db, days_min: int = 3, days_max: int = 5, threshold: float = 3.0,
) -> list[dict]:
    """Find trades from 3-5 days ago that moved significantly and haven't been reflected on."""
    today = date.today()
    start = (today - timedelta(days=days_max)).isoformat()
    end = (today - timedelta(days=days_min)).isoformat()

    # Get trades in the window
    trades_resp = (
        db.table("transactions")
        .select("id, user_id, symbol, asset_type, side, price, quantity, reasoning, created_at")
        .gte("created_at", f"{start}T00:00:00")
        .lte("created_at", f"{end}T23:59:59")
        .execute()
    )
    if not trades_resp.data:
        return []

    # Get already-reflected trade IDs
    trade_ids = [t["id"] for t in trades_resp.data]
    reflected_resp = (
        db.table("trade_reflections")
        .select("trade_id")
        .in_("trade_id", trade_ids)
        .execute()
    )
    reflected_ids = {r["trade_id"] for r in reflected_resp.data}

    # Filter to unreflected trades
    unreflected = [t for t in trades_resp.data if t["id"] not in reflected_ids]
    if not unreflected:
        return []

    # Map user_id to display_name for personality context
    user_ids = list({t["user_id"] for t in unreflected})
    profiles_resp = (
        db.table("profiles")
        .select("id, display_name")
        .in_("id", user_ids)
        .eq("is_ai", True)
        .execute()
    )
    name_map = {p["id"]: p["display_name"] for p in profiles_resp.data}

    return [
        {
            "trade_id": t["id"],
            "user_id": t["user_id"],
            "display_name": name_map.get(t["user_id"], "Unknown"),
            "symbol": t["symbol"],
            "asset_type": t.get("asset_type", "stock"),
            "side": t["side"],
            "price": float(t["price"]),
            "reasoning": t.get("reasoning", ""),
            "created_at": t["created_at"],
        }
        for t in unreflected
        if t["user_id"] in name_map  # Only AI traders
    ]


def _build_reflection_prompt(trades_with_prices: list[dict]) -> str:
    """Build batch prompt for trade reflection."""
    items = []
    for i, t in enumerate(trades_with_prices):
        items.append({
            "id": i,
            "trader": t["display_name"],
            "side": t["side"],
            "symbol": t["symbol"],
            "trade_price": t["price"],
            "current_price": t["current_price"],
            "change_pct": t["change_pct"],
            "original_reasoning": (t.get("reasoning") or "No reasoning recorded")[:300],
        })

    return (
        "Review these settled trades. For each, provide:\n"
        "- outcome_score: float from -1.0 (terrible decision) to +1.0 (great decision)\n"
        "- reflection: 1-2 sentence assessment of what happened\n"
        "- lesson: 1 sentence actionable takeaway for future trades\n\n"
        f"Trades:\n{json.dumps(items, indent=2)}\n\n"
        'Respond with: {"reflections": [{"id": 0, "outcome_score": 0.5, '
        '"reflection": "...", "lesson": "..."}, ...]}'
    )


def _parse_reflections(raw: str, trades: list[dict]) -> list[dict]:
    """Parse LLM response into reflection dicts."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    data = json.loads(text)
    refs = data.get("reflections", data if isinstance(data, list) else [])

    parsed = []
    for entry in refs:
        idx = entry.get("id")
        if idx is None or idx >= len(trades):
            continue
        t = trades[idx]
        score = max(-1.0, min(1.0, float(entry.get("outcome_score", 0))))
        parsed.append({
            "trade_id": t["trade_id"],
            "user_id": t["user_id"],
            "symbol": t["symbol"],
            "side": t["side"],
            "trade_price": t["price"],
            "outcome_price": t["current_price"],
            "price_change_pct": t["change_pct"],
            "outcome_score": score,
            "reflection_text": entry.get("reflection", "")[:500],
            "lessons": entry.get("lesson", "")[:300],
        })
    return parsed


def _persist_reflections(reflections: list[dict]) -> None:
    """Batch insert reflections into Supabase."""
    if not reflections:
        return
    db = get_supabase_admin()
    rows = [
        {
            "trade_id": r["trade_id"],
            "user_id": r["user_id"],
            "symbol": r["symbol"],
            "side": r["side"],
            "trade_price": r["trade_price"],
            "outcome_price": r["outcome_price"],
            "price_change_pct": r["price_change_pct"],
            "outcome_score": r["outcome_score"],
            "reflection_text": r["reflection_text"],
            "lessons": r["lessons"],
        }
        for r in reflections
    ]
    db.table("trade_reflections").insert(rows).execute()


async def run_reflections() -> dict:
    """Main entry point: review settled trades and generate reflections."""
    settings = get_settings()
    if not settings.mistral_api_key:
        return {"status": "skipped", "reason": "No Mistral API key"}

    db = get_supabase_admin()
    trades = _get_settled_trades(db)
    if not trades:
        print("[REFLECTION] No settled trades to reflect on")
        return {"status": "ok", "reflected_count": 0}

    # Fetch current prices for each trade symbol
    prices_cache: dict[str, float] = {}
    for t in trades:
        sym = t["symbol"]
        if sym not in prices_cache:
            quote = await get_quote(sym, t["asset_type"])
            if quote:
                prices_cache[sym] = quote["price"]

    # Enrich trades with current prices and filter by threshold
    enriched = []
    for t in trades:
        current = prices_cache.get(t["symbol"])
        if current is None:
            continue
        change_pct = ((current / t["price"]) - 1) * 100 if t["price"] > 0 else 0
        if abs(change_pct) < 3.0:
            continue
        t["current_price"] = current
        t["change_pct"] = round(change_pct, 2)
        enriched.append(t)

    if not enriched:
        print("[REFLECTION] No trades with significant price movement")
        return {"status": "ok", "reflected_count": 0}

    # LLM call (local Gemma if available, falls back to Mistral)
    try:
        from app.services.llm import call_llm

        prompt = _build_reflection_prompt(enriched)
        raw = await call_llm(
            system=REFLECTION_SYSTEM,
            user_msg=prompt,
            tier="local",
            temperature=0.3,
            max_tokens=4096,
        )

        reflections = _parse_reflections(raw, enriched)
        _persist_reflections(reflections)
        print(f"[REFLECTION] Generated {len(reflections)} reflections from {len(enriched)} trades")

        return {
            "status": "ok",
            "reflected_count": len(reflections),
            "trades_reviewed": len(enriched),
        }

    except Exception as e:
        print(f"[REFLECTION] Failed: {e}")
        return {"status": "error", "reason": str(e)[:200]}


def get_reflection_memory(db, user_id: str, limit: int = 5) -> str:
    """Get recent reflections for a trader, formatted for trade memory."""
    result = (
        db.table("trade_reflections")
        .select("symbol, side, trade_price, outcome_price, price_change_pct, outcome_score, reflection_text, lessons, reflected_at")
        .eq("user_id", user_id)
        .order("reflected_at", desc=True)
        .limit(limit)
        .execute()
    )
    if not result.data:
        return ""

    lines = ["LESSONS FROM PAST TRADES (learn from these):"]
    for r in result.data:
        day = r["reflected_at"][:10] if r.get("reflected_at") else "?"
        direction = "up" if r["price_change_pct"] > 0 else "down"
        lines.append(
            f"  [{day}] {r['side'].upper()} {r['symbol']} @ ${float(r['trade_price']):,.2f} "
            f"-> ${float(r['outcome_price']):,.2f} ({r['price_change_pct']:+.1f}% {direction})"
        )
        if r.get("lessons"):
            lines.append(f"    LESSON: {r['lessons']}")

    return "\n".join(lines)
