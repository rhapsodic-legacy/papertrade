"""Gemma-powered preprocessing pipeline.

Runs once per daily brief to compress and enrich raw data before traders see it.
Uses local Ollama (Gemma 4 e2b) — free, unlimited, no API costs.
Falls back gracefully: if Ollama is unavailable, traders get raw data as before.

Current preprocessors:
  1. Headline clustering — groups 15-25 headlines into 3-6 themed clusters
  2. Analyst consensus — condenses per-symbol recs into narrative summaries
  3. Insider flow — aggregates insider buy/sell patterns
"""

from __future__ import annotations

import json

from app.services.llm import call_llm, is_ollama_available


# ---------------------------------------------------------------------------
# 1. Headline clustering
# ---------------------------------------------------------------------------

CLUSTER_SYSTEM = (
    "You are a financial news editor. Group headlines into themed clusters. "
    "Each cluster should have a theme label and list the most important headlines. "
    "Respond ONLY with valid JSON, no markdown fences."
)


async def cluster_headlines(
    news: list[dict], company_news: dict[str, list[dict]]
) -> list[dict] | None:
    """Cluster scored headlines into 3-6 themes via Gemma.

    Returns list of clusters like:
        [{"theme": "Fed Rate Outlook", "sentiment": 0.3,
          "headlines": ["Fed holds rates...", "Powell signals..."],
          "symbols": ["SPY"], "count": 4}]

    Returns None if Ollama is unavailable (traders get raw headlines).
    """
    if not await is_ollama_available():
        print("[PREPROCESS] Ollama not available — skipping headline clustering")
        return None

    # Collect all headlines with scores
    all_headlines = []
    for n in news:
        all_headlines.append({
            "headline": n.get("headline", ""),
            "score": n.get("score"),
            "symbol": None,
        })
    for sym, articles in company_news.items():
        for a in articles:
            all_headlines.append({
                "headline": a.get("headline", ""),
                "score": a.get("score"),
                "symbol": sym,
            })

    if len(all_headlines) < 3:
        return None

    # Build prompt
    h_lines = []
    for i, h in enumerate(all_headlines):
        score_str = f" [{h['score']:+.2f}]" if h["score"] is not None else ""
        sym_str = f" ({h['symbol']})" if h["symbol"] else ""
        h_lines.append(f"{i+1}.{score_str}{sym_str} {h['headline']}")

    prompt = (
        f"Here are {len(all_headlines)} financial headlines from today:\n\n"
        + "\n".join(h_lines)
        + "\n\nGroup these into 3-6 themed clusters. For each cluster provide:\n"
        '- "theme": short label (e.g. "Tech Earnings Beat", "Fed Hawkish Signals")\n'
        '- "sentiment": average sentiment score (-1 to +1) across headlines in the cluster\n'
        '- "headlines": the 2-3 most important headlines (verbatim from above)\n'
        '- "symbols": any stock/crypto tickers mentioned or relevant\n'
        '- "count": total number of headlines in this cluster\n\n'
        "Respond with a JSON array of cluster objects. Prioritize market-moving themes."
    )

    try:
        raw = await call_llm(
            system=CLUSTER_SYSTEM,
            user_msg=prompt,
            tier="local_only",
            temperature=0.2,
            max_tokens=8192,  # Gemma 4 is a thinking model — needs room for reasoning + output
        )
        clusters = _parse_clusters(raw)
        if clusters:
            total = sum(c["count"] for c in clusters)
            print(f"[PREPROCESS] Clustered {total} headlines into {len(clusters)} themes")
        return clusters
    except Exception as e:
        print(f"[PREPROCESS] Headline clustering failed: {e}")
        return None


def _parse_clusters(raw: str) -> list[dict] | None:
    """Parse Gemma's cluster JSON response."""
    text = raw.strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON array in the text
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                print(f"[PREPROCESS] Could not parse clusters JSON")
                return None
        else:
            return None

    if not isinstance(data, list):
        return None

    clusters = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cluster = {
            "theme": str(item.get("theme", "Other")),
            "sentiment": float(item.get("sentiment", 0)),
            "headlines": item.get("headlines", []),
            "symbols": item.get("symbols", []),
            "count": int(item.get("count", len(item.get("headlines", [])))),
        }
        # Clamp sentiment
        cluster["sentiment"] = max(-1.0, min(1.0, cluster["sentiment"]))
        clusters.append(cluster)

    return clusters if clusters else None


# ---------------------------------------------------------------------------
# 2. Analyst consensus grouping
# ---------------------------------------------------------------------------

CONSENSUS_SYSTEM = (
    "You are a financial analyst. Summarize analyst recommendation data into "
    "concise narratives. Respond ONLY with valid JSON, no markdown fences."
)


async def summarize_analyst_consensus(
    analyst_recs: dict[str, dict],
) -> dict[str, str] | None:
    """Condense per-symbol analyst recs into 1-line narratives via Gemma.

    Returns dict like {"AAPL": "Strong Buy consensus (12 analysts), PT $220 avg",
                       "TSLA": "Mixed — 8 Buy, 6 Hold, 4 Sell, PT range $150-$300"}

    Returns None if Ollama unavailable.
    """
    if not await is_ollama_available():
        return None

    if not analyst_recs:
        return None

    prompt_lines = []
    for sym, rec in analyst_recs.items():
        prompt_lines.append(f"{sym}: {json.dumps(rec)}")

    prompt = (
        "Summarize each stock's analyst consensus into a single concise line.\n"
        "Focus on: consensus direction, number of analysts, key price targets.\n\n"
        + "\n".join(prompt_lines)
        + '\n\nRespond with JSON object: {"SYMBOL": "one-line summary", ...}'
    )

    try:
        raw = await call_llm(
            system=CONSENSUS_SYSTEM,
            user_msg=prompt,
            tier="local_only",
            temperature=0.2,
            max_tokens=8192,
        )
        return _parse_json_dict(raw)
    except Exception as e:
        print(f"[PREPROCESS] Analyst consensus failed: {e}")
        return None


# ---------------------------------------------------------------------------
# 3. Insider flow aggregation
# ---------------------------------------------------------------------------

INSIDER_SYSTEM = (
    "You are a financial analyst specializing in insider trading patterns. "
    "Summarize insider transaction data into actionable patterns. "
    "Respond ONLY with valid JSON, no markdown fences."
)


async def summarize_insider_flow(
    insider_transactions: dict[str, list[dict]],
) -> dict[str, str] | None:
    """Aggregate insider buy/sell patterns into 1-line narratives via Gemma.

    Returns dict like {"AAPL": "Net insider buying: CEO bought $2M, CFO bought $500K",
                       "TSLA": "Heavy selling: 3 insiders sold $5M total this week"}

    Returns None if Ollama unavailable.
    """
    if not await is_ollama_available():
        return None

    if not insider_transactions:
        return None

    prompt_lines = []
    for sym, txns in insider_transactions.items():
        if txns:
            prompt_lines.append(f"{sym}: {json.dumps(txns[:5])}")  # limit per symbol

    if not prompt_lines:
        return None

    prompt = (
        "Summarize each stock's insider trading activity into a single concise line.\n"
        "Focus on: net direction (buying vs selling), notable names/titles, total value.\n\n"
        + "\n".join(prompt_lines)
        + '\n\nRespond with JSON object: {"SYMBOL": "one-line summary", ...}'
    )

    try:
        raw = await call_llm(
            system=INSIDER_SYSTEM,
            user_msg=prompt,
            tier="local_only",
            temperature=0.2,
            max_tokens=8192,
        )
        return _parse_json_dict(raw)
    except Exception as e:
        print(f"[PREPROCESS] Insider flow summary failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Run all preprocessors
# ---------------------------------------------------------------------------

async def run_preprocessing(brief: dict) -> dict:
    """Run all Gemma preprocessors and inject results into the brief.

    Modifies the brief dict in-place, adding:
      - headline_clusters: list[dict] | None
      - analyst_consensus: dict[str, str] | None
      - insider_summary: dict[str, str] | None

    If Ollama is unavailable, all fields are None and traders use raw data.
    """
    import asyncio

    news = brief.get("news", [])
    company_news = brief.get("company_news", {})
    analyst_recs = brief.get("analyst_recommendations", {})
    insider_txns = brief.get("insider_transactions", {})

    # Run all preprocessors in parallel (each checks Ollama independently)
    clusters, consensus, insider = await asyncio.gather(
        cluster_headlines(news, company_news),
        summarize_analyst_consensus(analyst_recs),
        summarize_insider_flow(insider_txns),
    )

    brief["headline_clusters"] = clusters
    brief["analyst_consensus"] = consensus
    brief["insider_summary"] = insider

    active = sum(1 for x in (clusters, consensus, insider) if x is not None)
    print(f"[PREPROCESS] Completed: {active}/3 preprocessors produced data")

    return brief


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_json_dict(raw: str) -> dict[str, str] | None:
    """Parse a JSON dict from Gemma's response."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
        else:
            return None

    if not isinstance(data, dict):
        return None
    return {str(k): str(v) for k, v in data.items()} if data else None
