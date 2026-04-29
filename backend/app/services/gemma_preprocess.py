"""Gemma-powered preprocessing pipeline.

Runs once per daily brief to compress and enrich raw data before traders see it.
Uses local Ollama (Gemma 4 e2b) — free, unlimited, no API costs.
Falls back gracefully: if Ollama is unavailable, traders get raw data as before.

Current preprocessors:
  1. Headline clustering — groups 15-25 headlines into 3-6 themed clusters
  2. Analyst consensus — condenses per-symbol recs into narrative summaries
  3. Insider flow — aggregates insider buy/sell patterns
  4. Movers narrative — explains WHY top gainers/losers moved (cross-refs news + technicals + fundamentals)
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
            max_tokens=16384,  # Gemma 4 thinking model: needs ~8k for <think> + ~4k for output
        )
        clusters = _parse_clusters(raw)
        if clusters:
            total = sum(c["count"] for c in clusters)
            print(f"[PREPROCESS] Clustered {total} headlines into {len(clusters)} themes")
        else:
            print(f"[PREPROCESS] Cluster parse returned None — raw first 300 chars: {raw[:300]}")
        return clusters
    except Exception as e:
        print(f"[PREPROCESS] Headline clustering failed: {e}")
        return None


def _parse_clusters(raw: str) -> list[dict] | None:
    """Parse Gemma's cluster JSON response.

    Handles Gemma 4 thinking model output which may include <think>...</think>
    blocks, markdown fences, and preamble text before the JSON array.
    """
    text = _strip_llm_wrapper(raw)

    # Try direct parse first
    data = _try_parse_json(text)

    # If that failed, try to find a JSON array — but be smart about it.
    # Gemma's thinking block can contain [ ] so we try multiple [ positions.
    if data is None:
        candidates = _find_json_arrays(text)
        for candidate in candidates:
            data = _try_parse_json(candidate)
            if isinstance(data, list) and data:
                break

    if not isinstance(data, list):
        print(f"[PREPROCESS] Could not parse clusters JSON (raw length: {len(raw)})")
        return None

    clusters = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            cluster = {
                "theme": str(item.get("theme", "Other")),
                "sentiment": float(item.get("sentiment", 0)),
                "headlines": item.get("headlines", []),
                "symbols": item.get("symbols", []),
                "count": int(item.get("count", len(item.get("headlines", [])))),
            }
            cluster["sentiment"] = max(-1.0, min(1.0, cluster["sentiment"]))
            clusters.append(cluster)
        except (ValueError, TypeError):
            continue

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
# 4. Movers narrative — explain WHY top gainers/losers moved
# ---------------------------------------------------------------------------

MOVERS_SYSTEM = (
    "You are a financial analyst. Explain why stocks moved today using the "
    "provided data (news headlines, technicals, fundamentals). "
    "Be specific — cite the catalyst (earnings beat, FDA approval, sector rotation, etc). "
    "Respond ONLY with valid JSON, no markdown fences."
)


async def narrate_movers(
    top_gainers: list[dict],
    top_losers: list[dict],
    company_news: dict[str, list[dict]],
    stock_technicals: dict[str, dict],
    fundamentals: dict[str, dict],
) -> dict[str, str] | None:
    """Explain why today's top movers moved, cross-referencing available data.

    Returns dict like {"AAPL": "Up 4.2% — beat Q2 earnings estimates, RSI 58 (room to run),
                        analyst PT raised to $220",
                       "TSLA": "Down 3.1% — missed delivery estimates, RSI 72 (overbought),
                        insider selling $5M this week"}

    Returns None if Ollama unavailable.
    """
    if not await is_ollama_available():
        return None

    movers = (top_gainers or [])[:5] + (top_losers or [])[:5]
    if not movers:
        return None

    prompt_lines = []
    for m in movers:
        sym = m.get("symbol", "")
        chg = m.get("change_pct", 0)
        price = m.get("price", 0)

        context_parts = [f"Price ${price:.2f}, change {chg:+.1f}%"]

        # Add news context
        news = company_news.get(sym, [])
        if news:
            headlines = [n.get("headline", "") for n in news[:3]]
            context_parts.append(f"News: {'; '.join(headlines)}")

        # Add technical context
        tech = stock_technicals.get(sym, {})
        if tech:
            tech_bits = []
            if tech.get("rsi_14") is not None:
                tech_bits.append(f"RSI {tech['rsi_14']:.0f}")
            if tech.get("sma_20_signal"):
                tech_bits.append(f"SMA20: {tech['sma_20_signal']}")
            if tech.get("atr_14"):
                tech_bits.append(f"ATR ${tech['atr_14']:.2f}")
            if tech_bits:
                context_parts.append(f"Technicals: {', '.join(tech_bits)}")

        # Add fundamental context
        fund = fundamentals.get(sym, {})
        if fund:
            fund_bits = []
            if fund.get("pe_ratio"):
                fund_bits.append(f"PE {fund['pe_ratio']:.1f}")
            if fund.get("beta"):
                fund_bits.append(f"Beta {fund['beta']:.2f}")
            if fund_bits:
                context_parts.append(f"Fundamentals: {', '.join(fund_bits)}")

        prompt_lines.append(f"{sym}: {' | '.join(context_parts)}")

    prompt = (
        "Here are today's top movers with their available data:\n\n"
        + "\n".join(prompt_lines)
        + "\n\nFor each symbol, write a 1-2 sentence explanation of WHY it moved today. "
        "Cross-reference the news, technicals, and fundamentals to identify the catalyst. "
        "If no clear catalyst exists, say so and note the technical setup.\n\n"
        'Respond with JSON object: {"SYMBOL": "narrative explanation", ...}'
    )

    try:
        raw = await call_llm(
            system=MOVERS_SYSTEM,
            user_msg=prompt,
            tier="local_only",
            temperature=0.2,
            max_tokens=8192,
        )
        result = _parse_json_dict(raw)
        if result:
            print(f"[PREPROCESS] Narrated {len(result)} movers")
        return result
    except Exception as e:
        print(f"[PREPROCESS] Movers narrative failed: {e}")
        return None


# ---------------------------------------------------------------------------
# 5. Analyst article summarization
# ---------------------------------------------------------------------------

ANALYST_SUMMARY_SYSTEM = (
    "You are a financial research analyst. Summarize the article and extract "
    "actionable trading signals. Respond ONLY with valid JSON, no markdown fences."
)


async def summarize_analyst_article(article: dict) -> dict | None:
    """Summarize a single analyst article via Gemma.

    Returns dict like:
        {"summary": "...", "tickers": ["BTC", "ETH"], "sentiment": 0.7,
         "analyst_call": "BULLISH ETH post-Dencun", "confidence": 0.8}

    Returns None if Ollama is unavailable.
    """
    if not await is_ollama_available():
        return None

    title = article.get("title", "")
    content = article.get("content_text", "")[:3000]  # Cap input length
    category = article.get("category", "macro")

    prompt = (
        f"Article title: {title}\n"
        f"Category: {category}\n"
        f"Content:\n{content}\n\n"
        "Analyze this article and respond with a JSON object:\n"
        '- "summary": 2-3 sentence summary of the key argument or thesis\n'
        '- "tickers": array of stock/crypto ticker symbols mentioned or relevant (e.g. ["AAPL", "BTC"]). Empty array if none.\n'
        '- "sentiment": number from -1.0 (very bearish) to +1.0 (very bullish)\n'
        '- "analyst_call": one-line actionable call (e.g. "BULLISH tech sector — earnings beats underpriced")\n'
        '- "confidence": how confident is this call, 0.0 to 1.0 (0.3 = speculative, 0.8 = high conviction)\n'
    )

    try:
        raw = await call_llm(
            system=ANALYST_SUMMARY_SYSTEM,
            user_msg=prompt,
            tier="local_only",
            temperature=0.2,
            max_tokens=4096,
        )
        result = _parse_json_dict(raw)
        if not result:
            return None

        # Normalize fields
        summary_data = {
            "summary": result.get("summary", ""),
            "tickers": result.get("tickers", []),
            "sentiment": max(-1.0, min(1.0, float(result.get("sentiment", 0)))),
            "analyst_call": result.get("analyst_call", ""),
            "confidence": max(0.0, min(1.0, float(result.get("confidence", 0.5)))),
        }
        # Ensure tickers is a list of strings
        if isinstance(summary_data["tickers"], str):
            summary_data["tickers"] = [summary_data["tickers"]]
        summary_data["tickers"] = [str(t).upper() for t in summary_data["tickers"] if t]

        return summary_data
    except Exception as e:
        print(f"[PREPROCESS] Analyst article summarization failed: {e}")
        return None


ANALYST_DIGEST_SYSTEM = (
    "You are a financial research editor. Compress multiple analyst summaries "
    "into a concise digest that highlights consensus, conflicts, and high-conviction calls. "
    "Respond ONLY with plain text, no markdown fences or JSON."
)


async def compress_analyst_digest(summaries: list[dict]) -> str | None:
    """Compress multiple article summaries into a ~500-word Expert Opinion Digest.

    Groups by theme, flags consensus AND conflicts between analysts.
    Returns the digest text, or None if Ollama unavailable.
    """
    if not await is_ollama_available():
        return None

    if not summaries:
        return None

    # Build input from summaries
    lines = []
    for i, s in enumerate(summaries, 1):
        source = s.get("source_key", "unknown")
        call = s.get("analyst_call", "")
        sent = s.get("sentiment", 0)
        tickers = ", ".join(s.get("tickers", []))
        summary = s.get("summary", "")
        conf = s.get("confidence", 0.5)
        lines.append(
            f"{i}. [{source}] (sentiment: {sent:+.1f}, confidence: {conf:.1f})"
            f"{f' [{tickers}]' if tickers else ''}\n"
            f"   Call: {call}\n"
            f"   Summary: {summary}"
        )

    prompt = (
        f"Here are {len(summaries)} analyst opinions from the past 72 hours:\n\n"
        + "\n\n".join(lines)
        + "\n\nProduce a digest in EXACTLY this structure:\n\n"
        "TICKER CALLS:\n"
        "For each ticker mentioned in the summaries above, write ONE line in this format:\n"
        "  TICKER — DIRECTION (source1, source2): one-sentence rationale, confidence X.X\n"
        "DIRECTION must be BUY / SELL / HOLD / WATCH / NEUTRAL / CAUTION.\n"
        "If analysts disagree, list both: 'AAPL — BUY (wolfstreet) / SELL (mishtalk): split view, confidence 0.5'\n"
        "If NO tickers appear in any summary, write exactly: 'No ticker-specific calls in this digest.'\n\n"
        "THEMES:\n"
        "2-3 short paragraphs covering macro/sector themes that didn't fit ticker calls. "
        "Cite analysts inline (e.g. 'Wolf Street argues...'). Be specific.\n\n"
        "CONFLICTS:\n"
        "Where do analysts disagree? 1-3 bullet points.\n\n"
        "HIGH-CONVICTION CALLS (confidence >= 0.7):\n"
        "List the highest-confidence calls regardless of whether they're ticker-specific.\n\n"
        "Be specific — name tickers verbatim, cite sources, quantify sentiment. "
        "Avoid generic advice. This digest will be read by AI traders making BUY/SELL "
        "decisions today and they need to be able to QUOTE specific calls in their reasoning."
    )

    try:
        raw = await call_llm(
            system=ANALYST_DIGEST_SYSTEM,
            user_msg=prompt,
            tier="local_only",
            temperature=0.3,
            max_tokens=8192,
        )
        # Strip any thinking tokens
        text = _strip_llm_wrapper(raw).strip()
        if len(text) < 50:
            print(f"[PREPROCESS] Analyst digest too short ({len(text)} chars)")
            return None
        print(f"[PREPROCESS] Analyst digest: {len(text)} chars from {len(summaries)} articles")
        return text
    except Exception as e:
        print(f"[PREPROCESS] Analyst digest compression failed: {e}")
        return None


async def run_analyst_summarization() -> tuple[list[dict], str | None]:
    """Summarize unsummarized articles and compress into a digest.

    Returns (summaries, digest_text). Both may be empty/None if no articles or Ollama down.
    """
    from app.services.analyst_scraper import (
        get_unsummarized_articles,
        update_article_summary,
        get_recent_digested_articles,
    )

    if not await is_ollama_available():
        print("[PREPROCESS] Ollama not available — skipping analyst summarization")
        return [], None

    # Step 1: Summarize new articles (sequential — single Ollama GPU)
    unsummarized = await get_unsummarized_articles()
    if unsummarized:
        print(f"[PREPROCESS] Summarizing {len(unsummarized)} analyst articles...")
        for article in unsummarized:
            summary_data = await summarize_analyst_article(article)
            if summary_data:
                await update_article_summary(article["id"], summary_data)

    # Step 2: Fetch all recent summarized articles and compress into digest
    recent = await get_recent_digested_articles()
    digest = None
    if recent:
        digest = await compress_analyst_digest(recent)

    return recent, digest


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
    top_gainers = brief.get("top_gainers", [])
    top_losers = brief.get("top_losers", [])
    stock_technicals = brief.get("stock_technicals", {})
    fundamentals = brief.get("fundamentals", {})

    # Run all preprocessors in parallel (each checks Ollama independently)
    clusters, consensus, insider, movers = await asyncio.gather(
        cluster_headlines(news, company_news),
        summarize_analyst_consensus(analyst_recs),
        summarize_insider_flow(insider_txns),
        narrate_movers(top_gainers, top_losers, company_news, stock_technicals, fundamentals),
    )

    brief["headline_clusters"] = clusters
    brief["analyst_consensus"] = consensus
    brief["insider_summary"] = insider
    brief["movers_narrative"] = movers

    active = sum(1 for x in (clusters, consensus, insider, movers) if x is not None)
    print(f"[PREPROCESS] Completed: {active}/4 preprocessors produced data")

    return brief


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_llm_wrapper(raw: str) -> str:
    """Strip thinking tokens, markdown fences, and whitespace from LLM output."""
    import re
    text = raw.strip()
    # Strip <think>...</think> blocks (Gemma 4 thinking model)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text


def _try_parse_json(text: str):
    """Try to parse JSON, return None on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _find_json_arrays(text: str) -> list[str]:
    """Find candidate JSON array substrings, trying multiple [ positions.

    Returns candidates from longest to shortest (most likely to be complete).
    """
    candidates = []
    last_bracket = text.rfind("]")
    if last_bracket < 0:
        return candidates

    # Try each [ position, paired with the last ]
    pos = 0
    while True:
        start = text.find("[", pos)
        if start < 0 or start >= last_bracket:
            break
        candidates.append(text[start:last_bracket + 1])
        pos = start + 1

    # Longest first (earlier [ = more content = more likely to be the real array)
    return candidates


def _parse_json_dict(raw: str) -> dict[str, str] | None:
    """Parse a JSON dict from Gemma's response."""
    text = _strip_llm_wrapper(raw)

    data = _try_parse_json(text)
    if data is None:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            data = _try_parse_json(text[start:end + 1])

    if not isinstance(data, dict):
        return None
    return {str(k): str(v) for k, v in data.items()} if data else None
