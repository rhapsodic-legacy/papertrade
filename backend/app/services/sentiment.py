"""
Headline sentiment scoring via Groq (Llama 3.3 70B).

Batch-scores all daily headlines in a single API call, persists scores
to headline_sentiments table, and returns aggregates for the market brief.
"""

from __future__ import annotations

import json
from datetime import date

import httpx

from app.config import get_settings
from app.services.supabase_client import get_supabase_admin

VALID_CATEGORIES = {
    "earnings", "fed", "macro", "geopolitical", "sector", "regulatory",
    "analyst", "ipo", "merger", "crypto", "commodities", "labor",
    "housing", "other",
}

SCORING_SYSTEM = (
    "You are a financial news sentiment analyst. Score each headline on "
    "market sentiment and categorize it. Respond ONLY with valid JSON."
)


def _build_scoring_prompt(headlines: list[dict]) -> str:
    """Build the user prompt for batch headline scoring."""
    items = json.dumps(
        [
            {"id": i, "headline": h["headline"], "summary": h.get("summary", "")}
            for i, h in enumerate(headlines)
        ],
        indent=2,
    )
    return (
        "Score these financial news headlines. For each, provide:\n"
        "- score: float from -1.0 (very bearish) to +1.0 (very bullish), 0 = neutral\n"
        "- confidence: float from 0.0 to 1.0\n"
        "- categories: array of tags from "
        "[earnings, fed, macro, geopolitical, sector, regulatory, analyst, "
        "ipo, merger, crypto, commodities, labor, housing, other]\n\n"
        f"Headlines:\n{items}\n\n"
        'Respond with: {"scores": [{"id": 0, "score": 0.3, "confidence": 0.85, '
        '"categories": ["fed", "macro"]}, ...]}'
    )


def _parse_scores(raw: str, headlines: list[dict]) -> list[dict]:
    """Parse LLM JSON response into scored headline dicts."""
    # Strip markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    data = json.loads(text)
    scores_list = data.get("scores", data if isinstance(data, list) else [])

    scored = []
    for entry in scores_list:
        idx = entry.get("id")
        if idx is None or idx >= len(headlines):
            continue
        h = headlines[idx]

        score = max(-1.0, min(1.0, float(entry.get("score", 0))))
        confidence = max(0.0, min(1.0, float(entry.get("confidence", 0.5))))
        raw_cats = entry.get("categories", [])
        categories = [c for c in raw_cats if c in VALID_CATEGORIES] or ["other"]

        scored.append({
            "headline": h["headline"],
            "summary": h.get("summary", ""),
            "source": h.get("source", ""),
            "symbol": h.get("symbol"),
            "news_type": h.get("news_type", "general"),
            "score": score,
            "confidence": confidence,
            "categories": categories,
        })
    return scored


def _persist_scores(scores: list[dict], scored_date: date) -> None:
    """Batch insert scored headlines into Supabase."""
    if not scores:
        return
    db = get_supabase_admin()
    rows = [
        {
            "scored_date": scored_date.isoformat(),
            "symbol": s["symbol"],
            "headline": s["headline"],
            "summary": s["summary"],
            "source": s["source"],
            "sentiment_score": s["score"],
            "confidence": s["confidence"],
            "categories": s["categories"],
            "news_type": s["news_type"],
        }
        for s in scores
    ]
    db.table("headline_sentiments").insert(rows).execute()


def _compute_aggregates(scores: list[dict]) -> dict:
    """Compute market average, per-symbol averages, and category counts."""
    if not scores:
        return {}

    all_scores = [s["score"] for s in scores]
    all_conf = [s["confidence"] for s in scores]
    market_sentiment = sum(all_scores) / len(all_scores)
    market_confidence = sum(all_conf) / len(all_conf)

    # Per-symbol aggregates
    by_symbol: dict[str, dict] = {}
    for s in scores:
        sym = s.get("symbol")
        if not sym:
            continue
        if sym not in by_symbol:
            by_symbol[sym] = {"total_score": 0.0, "count": 0}
        by_symbol[sym]["total_score"] += s["score"]
        by_symbol[sym]["count"] += 1

    symbol_aggs = {
        sym: {
            "score": round(d["total_score"] / d["count"], 3),
            "headline_count": d["count"],
        }
        for sym, d in by_symbol.items()
    }

    # Category counts
    cat_counts: dict[str, int] = {}
    for s in scores:
        for c in s["categories"]:
            cat_counts[c] = cat_counts.get(c, 0) + 1

    return {
        "market_sentiment": round(market_sentiment, 3),
        "market_confidence": round(market_confidence, 3),
        "by_symbol": symbol_aggs,
        "scored_headline_count": len(scores),
        "categories_summary": dict(sorted(cat_counts.items(), key=lambda x: -x[1])),
    }


async def score_headlines(
    news: list[dict], company_news: dict[str, list[dict]]
) -> tuple[list[dict], dict]:
    """Score all headlines via a single Groq call.

    Returns (scored_list, aggregates_dict). On failure returns ([], {}).
    """
    settings = get_settings()
    if not settings.groq_api_key:
        print("[SENTIMENT] No Groq API key — skipping scoring")
        return [], {}

    # Combine general + company headlines into one list
    headlines: list[dict] = []
    for n in news:
        headlines.append({
            "headline": n.get("headline", ""),
            "summary": n.get("summary", ""),
            "source": n.get("source", ""),
            "symbol": None,
            "news_type": "general",
        })
    for symbol, articles in company_news.items():
        for a in articles:
            headlines.append({
                "headline": a.get("headline", ""),
                "summary": a.get("summary", ""),
                "source": a.get("source", ""),
                "symbol": symbol,
                "news_type": "company",
            })

    if not headlines:
        return [], {}

    try:
        # Single Groq call with low temperature for consistent scoring
        prompt = _build_scoring_prompt(headlines)
        url = "https://api.groq.com/openai/v1/chat/completions"
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": SCORING_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.groq_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code != 200:
                print(f"[SENTIMENT] Groq error {resp.status_code}: {resp.text[:300]}")
                return [], {}
            raw = resp.json()["choices"][0]["message"]["content"]

        scored = _parse_scores(raw, headlines)
        print(f"[SENTIMENT] Scored {len(scored)}/{len(headlines)} headlines")

        # Persist to database
        today = date.today()
        _persist_scores(scored, today)

        # Inject scores back into the original news dicts
        score_map = {s["headline"]: s for s in scored}
        for n in news:
            match = score_map.get(n.get("headline", ""))
            if match:
                n["score"] = match["score"]
                n["confidence"] = match["confidence"]
                n["categories"] = match["categories"]
        for symbol, articles in company_news.items():
            for a in articles:
                match = score_map.get(a.get("headline", ""))
                if match:
                    a["score"] = match["score"]
                    a["confidence"] = match["confidence"]
                    a["categories"] = match["categories"]

        aggregates = _compute_aggregates(scored)
        return scored, aggregates

    except Exception as e:
        print(f"[SENTIMENT] Scoring failed: {e}")
        return [], {}


NARRATIVE_SYSTEM = (
    "You are a neutral market analyst writing a factual briefing. "
    "Your job is to explain WHAT is happening and the historical cause-effect relationships, "
    "NOT to recommend any action. Never say 'buy', 'sell', 'consider', 'avoid', or 'opportunity'. "
    "Never frame events as positive or negative for a portfolio. "
    "State facts and causal chains only. Let the reader draw their own conclusions. "
    "Write 3-5 concise bullet points. No fluff, no opinions, no recommendations."
)


async def generate_market_narrative(
    scored_headlines: list[dict],
    crypto_trending: list[dict] | None = None,
    market_regime: dict | None = None,
) -> str:
    """Generate a causal narrative explaining WHY today's headlines matter.

    Uses a single Groq call to produce 3-5 bullet points connecting news
    to expected market impact. Returns empty string on failure.
    """
    settings = get_settings()
    if not settings.groq_api_key or not scored_headlines:
        return ""

    # Build context: top headlines sorted by absolute impact
    top = sorted(scored_headlines, key=lambda h: abs(h.get("score", 0)), reverse=True)[:15]
    headlines_text = "\n".join(
        f"- [{h['score']:+.2f}] {h['headline']}"
        + (f" ({h['symbol']})" if h.get("symbol") else "")
        for h in top
    )

    # Add market context
    context_parts = []
    if market_regime:
        trend = market_regime.get("market_trend", "unknown")
        context_parts.append(f"Market regime: {trend}")
        rate = market_regime.get("rate_signal")
        if rate:
            context_parts.append(f"Rate signal: {rate}")
        haven = market_regime.get("safe_haven_demand")
        if haven:
            context_parts.append(f"Safe haven demand: {haven}")

    if crypto_trending:
        names = ", ".join(t.get("name", t.get("symbol", "?")) for t in crypto_trending[:5])
        context_parts.append(f"Crypto trending: {names}")

    context_str = "\n".join(context_parts) if context_parts else "No additional context."

    prompt = (
        f"Today's scored headlines (score: -1 bearish to +1 bullish):\n{headlines_text}\n\n"
        f"Current conditions:\n{context_str}\n\n"
        "Write 3-5 FACTUAL bullet points covering:\n"
        "1. What are the key themes in today's news?\n"
        "2. What cause-effect relationships exist? (e.g. 'Rate cuts have historically "
        "correlated with growth stock outperformance' NOT 'buy growth stocks')\n"
        "3. Any cross-market linkages (e.g. 'USD weakness historically correlates with "
        "crypto strength')\n\n"
        "RULES:\n"
        "- State facts and historical patterns ONLY\n"
        "- NEVER recommend actions (no 'buy', 'sell', 'consider', 'opportunity', 'benefits')\n"
        "- NEVER say an event is 'good for' or 'bad for' any asset\n"
        "- Use neutral language: 'X historically correlates with Y' not 'X will cause Y'\n"
        "- Format: bullet points starting with '-'. Reference specific tickers where relevant."
    )

    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": NARRATIVE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 1024,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.groq_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code != 200:
                print(f"[NARRATIVE] Groq error {resp.status_code}: {resp.text[:300]}")
                return ""
            narrative = resp.json()["choices"][0]["message"]["content"].strip()
            print(f"[NARRATIVE] Generated market narrative ({len(narrative)} chars)")
            return narrative
    except Exception as e:
        print(f"[NARRATIVE] Failed: {e}")
        return ""


async def get_sentiment_history(
    symbol: str | None = None, days: int = 30
) -> list[dict]:
    """Query daily sentiment trend from headline_sentiments table."""
    db = get_supabase_admin()
    query = db.table("headline_sentiments").select(
        "scored_date, sentiment_score, symbol"
    )

    if symbol:
        query = query.eq("symbol", symbol)

    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    query = query.gte("scored_date", cutoff).order("scored_date", desc=True)
    result = query.execute()

    # Aggregate by date
    daily: dict[str, dict] = {}
    for row in result.data:
        d = row["scored_date"]
        if d not in daily:
            daily[d] = {"total": 0.0, "count": 0}
        daily[d]["total"] += row["sentiment_score"]
        daily[d]["count"] += 1

    return [
        {
            "date": d,
            "avg_score": round(info["total"] / info["count"], 3),
            "headline_count": info["count"],
        }
        for d, info in sorted(daily.items(), reverse=True)
    ]
