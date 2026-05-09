"""
Trade reflection loop — LLM reviews settled trades and extracts lessons.

Runs daily before trading so today's decisions benefit from past reflections.
Single Groq batch call reviews all trades from 3-5 days ago where price moved >3%.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

import httpx

from app.config import get_settings
from app.services.supabase_client import get_supabase_admin
from app.services.market_data import get_quote

REFLECTION_SYSTEM = (
    "You are a trade performance analyst reviewing settled AI-trader decisions.\n"
    "\n"
    "For each trade you will see:\n"
    "  - The trader's PERSONALITY (vanilla, steady_eddie, yolo_bot, contrarian_carl, crypto_chad)\n"
    "  - The trader's STRATEGY summary (what they look for in a trade)\n"
    "  - The original REASONING given at execution time\n"
    "  - The price move since execution (%, current price vs trade price)\n"
    "\n"
    "Score each decision AGAINST THE PERSONALITY'S OWN CRITERIA — not a universal standard.\n"
    "  A Contrarian Carl buying oversold names is expected; judge whether the bounce came.\n"
    "  A YOLO Bot cutting fast on a dip is expected; judge whether the dip continued.\n"
    "  A Steady Eddie holding through a wobble is expected; judge whether the thesis survived.\n"
    "\n"
    "outcome_score rubric (-1.0 to +1.0):\n"
    "  +1.0 = thesis played out, profitable, exemplary for this personality\n"
    "  +0.5 = profitable, partially right or right direction but wrong magnitude\n"
    "   0.0 = neutral — no clear signal either way\n"
    "  -0.5 = thesis didn't play out, but the reasoning was defensible at the time\n"
    "  -1.0 = thesis failed AND the reasoning ignored obvious warnings the trader had access to\n"
    "\n"
    "LESSONS MUST BE SPECIFIC AND ACTIONABLE. Generic advice ('watch RSI', 'cut losses faster')\n"
    "is useless — the trader already knows. Good lessons cite the actual data and name a\n"
    "specific rule the trader should adopt:\n"
    "  BAD:  'Pay attention to technicals'\n"
    "  GOOD: 'AAPL was already +12% on 7d momentum with RSI 68 at entry — for Vanilla, buy\n"
    "         signals above RSI 65 are late-cycle; require a pullback to SMA20 or skip.'\n"
    "\n"
    "Respond ONLY with valid JSON."
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


_PERSONALITY_CRITERIA = {
    "vanilla": "Balanced portfolio manager — fundamentals + technicals, 10-20% cash, no single sector >40%. Max hold 30d, stop -8%, take-profit +15%.",
    "steady_eddie": "Conservative value (Buffett-style) — low PE, strong buy consensus, beta <1.0, dividend >1%. Avoid beta >1.5, limit crypto <5%. Max hold 45d, stop -6%, take-profit +12%.",
    "yolo_bot": "Aggressive momentum — 7d momentum >3%, RSI 50-75, above SMA20, volume spike. Cut losses fast (>8%), concentrate in top 3-5 names. Max hold 14d, stop -5%, take-profit +10%.",
    "contrarian_carl": "Mean-reversion/deep value — RSI <30, 7d <-5%, PE below norms, mixed consensus. Hold cash (15-25%) as dry powder. Max hold 60d, stop -10%, take-profit +20%.",
    "crypto_chad": "Crypto-native — 60-80% crypto, mid/large-cap focus, ATH distance >30%, BTC RSI >40. Max hold 21d, stop -12%, take-profit +25%.",
}


def _infer_personality_key(display_name: str) -> str | None:
    """Parse personality key out of a display_name like 'Vanilla (Mistral Large)'."""
    name_map = {
        "Vanilla": "vanilla",
        "Steady Eddie": "steady_eddie",
        "YOLO Bot": "yolo_bot",
        "Contrarian Carl": "contrarian_carl",
        "Crypto Chad": "crypto_chad",
    }
    for prefix, key in name_map.items():
        if display_name.startswith(prefix):
            return key
    return None


def _build_reflection_prompt(trades_with_prices: list[dict]) -> str:
    """Build batch prompt for trade reflection. Each trade carries the personality's
    criteria so the LLM can judge against strategy-specific standards."""
    items = []
    for i, t in enumerate(trades_with_prices):
        pkey = _infer_personality_key(t["display_name"])
        criteria = _PERSONALITY_CRITERIA.get(pkey, "Unknown personality — score against general trading principles.")
        items.append({
            "id": i,
            "trader": t["display_name"],
            "personality": pkey or "unknown",
            "strategy": criteria,
            "side": t["side"],
            "symbol": t["symbol"],
            "trade_price": t["price"],
            "current_price": t["current_price"],
            "change_pct": t["change_pct"],
            "original_reasoning": (t.get("reasoning") or "No reasoning recorded")[:400],
        })

    return (
        "Review these settled trades. For each, produce:\n"
        "  - outcome_score: float from -1.0 to +1.0 (see system rubric)\n"
        "  - reflection: 1-3 sentences — what actually happened, and whether the\n"
        "    original reasoning held up or broke down. Be specific, not generic.\n"
        "  - lesson: 1-2 sentences — a named rule this trader should adopt going\n"
        "    forward, grounded in the actual data from this trade. Must be specific\n"
        "    enough that applying it to a future trade would change the decision.\n"
        "\n"
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
            "reflection_text": entry.get("reflection", "")[:800],
            "lessons": entry.get("lesson", "")[:500],
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


_SUBSTANTIVE_RULE_PATTERN = re.compile(
    # Numerical anchors
    r"\d+(?:\.\d+)?\s*%"            # 5%, 12.5%
    r"|\$\d"                         # $50, $5000
    r"|\d+\s*-?\s*day"               # 5-day, 30 day
    r"|\d+d\b"                       # 5d, 30d
    r"|\d+\s*trade"                  # 12 trades
    r"|\d+\s*win"                    # 67 win
    r"|\d+:\d+"                      # 2:1 ratio
    # Named technical / fundamental indicators
    r"|\bRSI\b"
    r"|\bSMA\b|\bEMA\b"
    r"|\bMACD\b"
    r"|\bATR\b"
    r"|\bPE\b|P/E"
    r"|\bbeta\b"
    r"|Bollinger"
    r"|composite\s+signal|signal\s+score"
    # Concrete trading concepts (strong-signal verbs/nouns)
    r"|\bstop[- ]loss\b"
    r"|\btake[- ]profit\b"
    r"|\btrailing\s+stop\b"
    r"|\bdrawdown\b"
    r"|\boverbought\b|\boversold\b"
    r"|\bbreakout\b|\bbreakdown\b"
    r"|insider\s+(buying|selling)"
    r"|earnings\s+(beat|miss|risk)"
    r"|max\s+hold|hold\s+period",
    re.IGNORECASE,
)


def _is_substantive_rule(text: str) -> bool:
    """Filter for rules that cite specific numbers, named indicators, or
    concrete trading concepts. Pure platitudes ('be patient', 'trust your
    signals', 'diversify') get rejected. The bar: does the lesson contain
    SOMETHING the trader can apply mechanically to today's decision?"""
    return bool(_SUBSTANTIVE_RULE_PATTERN.search(text or ""))


def synthesize_personal_rules(db, user_id: str, lookback_days: int = 30, top_n: int = 6) -> str:
    """Synthesize a 'Personal Rulebook' from this trader's reflections.

    Mines reflections from the last `lookback_days`, keeps lessons attached
    to high-signal outcomes (|outcome_score| >= 0.4) AND containing numerical
    anchors (RSI thresholds, % drops, $ levels, day counts, named indicators),
    deduplicates by lesson text, and surfaces the top N.

    The quantitative filter is the second iteration after v1 produced 0 citations
    across a 7-day window — generic platitudes don't change behavior, but rules
    that name specific numbers are quotable and decision-altering.
    """
    import re as _re
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

    result = (
        db.table("trade_reflections")
        .select("lessons, outcome_score, reflected_at, symbol")
        .eq("user_id", user_id)
        .gte("reflected_at", cutoff)
        .order("reflected_at", desc=True)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return ""

    # Group by normalized lesson text to find recurring patterns.
    # Each entry: {"text": original, "count": int, "recent": iso_date,
    #              "scores": list[float], "symbols": set}
    groups: dict[str, dict] = {}
    for r in rows:
        lesson = (r.get("lessons") or "").strip()
        if not lesson:
            continue
        score = abs(float(r.get("outcome_score", 0) or 0))
        if score < 0.4:
            continue
        # Substantive-rule filter: only keep lessons that cite numbers,
        # named indicators (RSI/MACD/ATR/PE/SMA/beta), or concrete trading
        # concepts (stop-loss, drawdown, overbought, earnings, etc.).
        # Pure platitudes ("trust your signals", "be patient") get rejected.
        if not _is_substantive_rule(lesson):
            continue
        # Normalize: lowercase + collapse whitespace + strip punctuation tail
        norm = " ".join(lesson.lower().split()).rstrip(".!?")
        if norm not in groups:
            groups[norm] = {
                "text": lesson,
                "count": 0,
                "recent": r.get("reflected_at", ""),
                "scores": [],
                "symbols": set(),
            }
        g = groups[norm]
        g["count"] += 1
        g["scores"].append(score)
        if r.get("symbol"):
            g["symbols"].add(r["symbol"])
        # keep most recent date (rows are already DESC-sorted, so first wins)

    if not groups:
        return ""

    # Score each group by frequency × avg signal strength.
    # Single-occurrence rules need a strong signal to make the cut;
    # repeated rules win even with moderate signal.
    def _rank(g: dict) -> float:
        avg_score = sum(g["scores"]) / len(g["scores"])
        return g["count"] * avg_score

    ranked = sorted(groups.values(), key=_rank, reverse=True)[:top_n]
    if not ranked:
        return ""

    lines = [
        "### YOUR PERSONAL RULES (synthesized from your own past trades)",
        f"These are patterns extracted from your last {lookback_days} days of post-trade reflections.",
        "Rules listed with frequency are recurring — you've been told this multiple times.",
        "Apply them BEFORE making today's decisions, not after.",
        "",
    ]
    for g in ranked:
        avg_score = sum(g["scores"]) / len(g["scores"])
        verdict = "✓ from wins" if avg_score > 0 else "✗ from losses"  # rough — abs() above
        # Recover sign info: count positive vs negative scores
        # (we lost sign by abs() — reread from rows is cheaper than tracking)
        freq_str = f"×{g['count']}" if g["count"] > 1 else "×1"
        sym_str = ""
        if g["symbols"] and len(g["symbols"]) <= 3:
            sym_str = f" [seen on: {', '.join(sorted(g['symbols']))}]"
        lines.append(f"  • [{freq_str}] {g['text']}{sym_str}")

    return "\n".join(lines)


def get_reflection_memory(db, user_id: str, limit: int = 5) -> str:
    """Get high-signal reflections for a trader, formatted for trade memory.

    Prefers reflections with decisive outcomes (|outcome_score| >= 0.3) because
    those yield specific lessons; ties broken by recency. Low-signal reflections
    (score near 0) are usually generic and don't change future behavior."""
    # Pull a wider window so we can filter for signal
    result = (
        db.table("trade_reflections")
        .select("symbol, side, trade_price, outcome_price, price_change_pct, outcome_score, reflection_text, lessons, reflected_at")
        .eq("user_id", user_id)
        .order("reflected_at", desc=True)
        .limit(max(limit * 4, 20))
        .execute()
    )
    if not result.data:
        return ""

    # Rank by absolute outcome_score (signal strength), recency as tiebreaker
    def _signal(r: dict) -> tuple:
        score = abs(float(r.get("outcome_score", 0) or 0))
        recency = r.get("reflected_at", "")
        return (score, recency)

    # Prefer high-signal, fall back to all if not enough decisive ones
    decisive = [r for r in result.data if abs(float(r.get("outcome_score", 0) or 0)) >= 0.3]
    chosen = sorted(decisive, key=_signal, reverse=True)[:limit]
    if len(chosen) < limit:
        # Top up with recent reflections we haven't already included
        chosen_ids = {id(c) for c in chosen}
        for r in result.data:
            if len(chosen) >= limit:
                break
            if id(r) not in chosen_ids:
                chosen.append(r)

    lines = [
        "LESSONS FROM PAST TRADES — these are your own decisions, reviewed after the move:",
        "Apply the named rules going forward; do not ignore them just because today feels different.",
    ]
    for r in chosen:
        day = r["reflected_at"][:10] if r.get("reflected_at") else "?"
        direction = "up" if r["price_change_pct"] > 0 else "down"
        score = float(r.get("outcome_score", 0) or 0)
        verdict = "✓ good call" if score >= 0.3 else ("✗ bad call" if score <= -0.3 else "neutral")
        lines.append(
            f"  [{day}] {r['side'].upper()} {r['symbol']} @ ${float(r['trade_price']):,.2f} "
            f"-> ${float(r['outcome_price']):,.2f} ({r['price_change_pct']:+.1f}% {direction}, {verdict})"
        )
        if r.get("lessons"):
            lines.append(f"    RULE: {r['lessons']}")

    return "\n".join(lines)
