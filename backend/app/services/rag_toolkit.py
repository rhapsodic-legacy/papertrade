"""Modular RAG toolkit for AI traders.

Each personality selects a subset of data modules (weighted by priority).
The toolkit assembler builds a tailored prompt containing only the
modules that personality cares about, ordered by weight so the LLM
pays the most attention to the highest-priority data.
"""

from __future__ import annotations

import json

from app.services.market_data import TOP_STOCKS, STOCK_SECTORS, CRYPTO_MAP


# ---------------------------------------------------------------------------
# Module registry
# ---------------------------------------------------------------------------

RAG_MODULES: dict[str, dict] = {
    "core": {
        "label": "Core Portfolio",
        "description": "Current holdings, cash, risk alerts, and supported assets",
        "always_included": True,
        "icon": "shield",
        "color": "gray",
    },
    "technicals": {
        "label": "Technical Analysis",
        "description": "RSI, SMA, EMA, MACD, Bollinger Bands, ATR, and composite signal scores",
        "always_included": False,
        "icon": "chart-line",
        "color": "blue",
    },
    "patterns": {
        "label": "Pattern Recognition",
        "description": "Candlestick patterns, golden/death cross, support/resistance, volume anomalies",
        "always_included": False,
        "icon": "eye",
        "color": "purple",
    },
    "fundamentals": {
        "label": "Fundamentals",
        "description": "PE ratio, market cap, beta, dividend yield, 52-week range, analyst consensus, earnings calendar",
        "always_included": False,
        "icon": "building",
        "color": "green",
    },
    "sentiment": {
        "label": "News & Sentiment",
        "description": "Market headlines, company news for top movers, and day-over-day regime shifts",
        "always_included": False,
        "icon": "newspaper",
        "color": "amber",
    },
    "momentum": {
        "label": "Momentum & Flow",
        "description": "Top gainers/losers, 7d/30d returns, relative volume spikes",
        "always_included": False,
        "icon": "trending-up",
        "color": "red",
    },
    "macro": {
        "label": "Macro & Sectors",
        "description": "Market regime (SPY/QQQ/TLT/GLD/IWM), sector rotation signals",
        "always_included": False,
        "icon": "globe",
        "color": "teal",
    },
    "optimizer": {
        "label": "Portfolio Optimizer",
        "description": "Position correlations, concentration warnings, and allocation suggestions",
        "always_included": False,
        "icon": "calculator",
        "color": "indigo",
    },
    "signal_ranker": {
        "label": "Signal Ranker",
        "description": "Composite scoring that synthesizes technicals, fundamentals, sentiment, and momentum into ranked asset scores with conflict analysis",
        "always_included": False,
        "icon": "bar-chart",
        "color": "orange",
    },
    "trade_context": {
        "label": "Trade Context",
        "description": "Your historical track record: win rates by sector, asset type, and holding period from your own past trades",
        "always_included": False,
        "icon": "history",
        "color": "cyan",
    },
    "dynamic_risk": {
        "label": "Dynamic Risk",
        "description": "Drawdown-aware position sizing that scales exposure based on your equity curve and recent performance",
        "always_included": False,
        "icon": "shield-alert",
        "color": "pink",
    },
    "options_flow": {
        "label": "Options Flow",
        "description": "VIX (CBOE Volatility Index) — the options market's real-time fear gauge derived from S&P 500 option prices",
        "always_included": False,
        "icon": "layers",
        "color": "violet",
    },
    "yield_curve": {
        "label": "Yield Curve",
        "description": "Treasury yield spreads and Fed Funds rate — the most-watched recession and rate expectation indicators",
        "always_included": False,
        "icon": "git-branch",
        "color": "emerald",
    },
    "expert_opinion": {
        "label": "Expert Opinion",
        "description": "Daily digest from independent analysts — consensus, conflicts, high-conviction calls",
        "always_included": False,
        "icon": "brain",
        "color": "rose",
    },
    "btc_onchain": {
        "label": "BTC On-Chain & Derivatives",
        "description": "Bitcoin network and futures-market metrics — MVRV-Z, NUPL, Puell Multiple, hash rate, funding rates, long/short positioning",
        "always_included": False,
        "icon": "link",
        "color": "amber",
    },
    "fleet_conviction": {
        "label": "Fleet Conviction",
        "description": "What the 20-trader AI fleet is collectively buying and selling — aggregate flow score and breadth per symbol. Each personality interprets fleet consensus differently (corroboration vs fade signal).",
        "always_included": False,
        "icon": "users",
        "color": "indigo",
    },
    "cross_asset": {
        "label": "Cross-Asset Macro",
        "description": "DXY (US Dollar Index), gold, 10Y real yields, breakeven inflation, and WTI crude — the four macro channels that drive risk-asset valuations.",
        "always_included": False,
        "icon": "globe",
        "color": "cyan",
    },
}


# ---------------------------------------------------------------------------
# Module keyword detection (fallback when LLM omits modules_used)
# ---------------------------------------------------------------------------

MODULE_KEYWORDS: dict[str, list[str]] = {
    "technicals": ["rsi", "sma", "ema", "macd", "bollinger", "atr", "overbought", "oversold", "technical"],
    "patterns": ["pattern", "golden cross", "death cross", "support", "resistance", "candlestick", "crossover"],
    "fundamentals": ["pe ratio", "pe ", "earnings", "dividend", "market cap", "analyst", "valuation", "fundamental"],
    "sentiment": ["news", "sentiment", "headline", "contrarian"],
    "momentum": ["momentum", "gainer", "loser", "volume spike", "relative volume"],
    "macro": ["regime", "sector rotation", "spy", "safe haven", "small cap", "rate"],
    "optimizer": ["correlation", "concentration", "rebalance", "allocation", "optimizer", "diversif"],
    "signal_ranker": ["composite", "ranked", "data synthesis", "score", "signal rank", "conflict"],
    "trade_context": ["track record", "win rate", "historical", "past trades", "my history", "streak"],
    "dynamic_risk": ["drawdown", "equity curve", "size multiplier", "defensive", "capital preservation"],
    "options_flow": ["vix", "volatility index", "fear", "complacen", "options flow", "hedging", "cboe", "market stress"],
    "yield_curve": ["yield curve", "treasury", "2y", "10y", "spread", "inverted", "recession", "fed funds", "rate cut", "rate hike"],
    "expert_opinion": ["analyst opinion", "expert", "digest", "consensus view", "independent analyst", "wolf street", "bankless", "messari", "calculated risk"],
    "btc_onchain": ["mvrv", "nupl", "puell", "realized price", "hash rate", "active addresses", "funding rate", "long/short", "long short ratio", "on-chain", "miner capitulation", "contrarian buy zone"],
    "fleet_conviction": ["fleet", "peer fleet", "consensus pick", "fleet flow", "fade the consensus", "the herd", "the fleet is", "fleet conviction", "controversial pick", "consensus accumulation", "consensus distribution"],
    "cross_asset": ["dxy", "dollar index", "real yield", "tips yield", "breakeven", "10y real", "gold price", "wti", "crude oil", "dollar strength", "dollar weakness", "macro headwind", "macro tailwind", "risk regime"],
}


def detect_modules_from_text(text: str, active_modules: set[str] | None = None) -> list[str]:
    """Scan reasoning text for module-related keywords. Returns detected module keys."""
    if not text:
        return []
    lower = text.lower()
    detected = []
    for module, keywords in MODULE_KEYWORDS.items():
        if active_modules and module not in active_modules:
            continue
        if any(kw in lower for kw in keywords):
            detected.append(module)
    return detected


# ---------------------------------------------------------------------------
# Per-module formatters
# ---------------------------------------------------------------------------

def _format_core(
    portfolio: dict,
    personality_key: str,
    risk_params: dict,
    risk_analysis: str,
    brief: dict,
) -> str:
    """Always-included section: portfolio state, risk rules, and supported assets."""
    supported_crypto = [{"symbol": s, "name": c["name"]} for s, c in CRYPTO_MAP.items()]

    risk_rules_text = ""
    if risk_params:
        risk_rules_text = (
            "\n## Your Risk Rules (ENFORCED)\n"
            f"- Stop-loss: sell any position down {risk_params.get('stop_loss_pct', -10)}% or more\n"
            f"- Take-profit: sell any position up +{risk_params.get('take_profit_pct', 20)}% or more\n"
            f"- Max position size: {risk_params.get('max_position_pct', 15)}% of portfolio\n"
            f"- Max hold period: {risk_params.get('max_hold_days', 30)} days for stale positions (<3% move)\n"
            "- If you have 3+ positions, include at least 1 sell in your trades today\n"
        )

    total_value = portfolio["cash"] + sum(p["market_value"] for p in portfolio["positions"])

    return (
        f"{risk_rules_text}\n"
        f"## Your Current Portfolio\n"
        f"Cash: ${portfolio['cash']:,.2f}\n"
        f"Total Value: ${total_value:,.2f}\n"
        f"Positions:\n"
        f"{json.dumps(portfolio['positions'], indent=2) if portfolio['positions'] else 'None — you have no positions yet.'}\n\n"
        f"## Portfolio Risk Analysis\n"
        f"{risk_analysis}\n\n"
        f"### Supported Stocks (by sector)\n"
        f"{_format_stocks_by_sector()}\n\n"
        f"### Supported Crypto\n"
        f"{json.dumps(supported_crypto, indent=2)}"
    )


def _format_technicals(brief: dict) -> str:
    """RSI, SMA, EMA, MACD, Bollinger, ATR, composite signal for stocks and crypto."""
    sections = []

    # Stock technicals
    technicals = brief.get("stock_technicals", {})
    if technicals:
        tech_lines = []
        for sym, t in list(technicals.items())[:20]:
            parts = []
            sig = t.get("signal", {})
            if sig.get("label"):
                parts.append(f"Signal: {sig['label']} ({sig['score']:+d})")
            if "rsi_14" in t:
                rsi = t["rsi_14"]
                label = "OVERBOUGHT" if rsi > 70 else "OVERSOLD" if rsi < 30 else ""
                parts.append(f"RSI {rsi}{' ' + label if label else ''}")
            if "vs_sma_20" in t:
                direction = "above" if t["vs_sma_20"] > 0 else "below"
                parts.append(f"{direction} SMA20 by {abs(t['vs_sma_20']):.1f}%")
            if "vs_sma_50" in t:
                direction = "above" if t["vs_sma_50"] > 0 else "below"
                parts.append(f"{direction} SMA50 by {abs(t['vs_sma_50']):.1f}%")
            macd = t.get("macd", {})
            if macd.get("histogram") is not None:
                hist = macd["histogram"]
                macd_label = "BULLISH" if hist > 0 else "BEARISH"
                parts.append(f"MACD {macd_label} (hist {hist:+.2f})")
            bb = t.get("bollinger_bands", {})
            if bb.get("pct_b") is not None:
                pct_b = bb["pct_b"]
                bb_label = "near upper band" if pct_b > 0.8 else "near lower band" if pct_b < 0.2 else "mid band"
                squeeze = ", SQUEEZE" if bb.get("bandwidth", 99) < 5 else ""
                parts.append(f"BB {bb_label} ({pct_b:.0%}){squeeze}")
            if "atr_14" in t:
                parts.append(f"ATR ${t['atr_14']:.2f}")
            if "7d_return" in t:
                parts.append(f"7d {t['7d_return']:+.1f}%")
            if "30d_return" in t:
                parts.append(f"30d {t['30d_return']:+.1f}%")
            if "relative_volume" in t:
                rv = t["relative_volume"]
                vol_label = "HIGH VOLUME" if rv > 1.5 else "LOW VOLUME" if rv < 0.5 else ""
                parts.append(f"RelVol {rv:.1f}x{' ' + vol_label if vol_label else ''}")
            if parts:
                tech_lines.append(f"  {sym}: {', '.join(parts)}")
        if tech_lines:
            sections.append("### Stock Technical Indicators\n" + "\n".join(tech_lines))

    # Crypto technicals
    crypto_tech = brief.get("crypto_technicals", {})
    if crypto_tech:
        ctech_lines = []
        for sym, t in list(crypto_tech.items())[:15]:
            parts = []
            sig = t.get("signal", {})
            if sig.get("label"):
                parts.append(f"Signal: {sig['label']} ({sig['score']:+d})")
            if "rsi_14" in t:
                rsi = t["rsi_14"]
                label = "OVERBOUGHT" if rsi > 70 else "OVERSOLD" if rsi < 30 else ""
                parts.append(f"RSI {rsi}{' ' + label if label else ''}")
            if "vs_sma_20" in t:
                direction = "above" if t["vs_sma_20"] > 0 else "below"
                parts.append(f"{direction} SMA20 by {abs(t['vs_sma_20']):.1f}%")
            if "vs_sma_50" in t:
                direction = "above" if t["vs_sma_50"] > 0 else "below"
                parts.append(f"{direction} SMA50 by {abs(t['vs_sma_50']):.1f}%")
            macd = t.get("macd", {})
            if macd.get("histogram") is not None:
                hist = macd["histogram"]
                macd_label = "BULLISH" if hist > 0 else "BEARISH"
                parts.append(f"MACD {macd_label} (hist {hist:+.2f})")
            bb = t.get("bollinger_bands", {})
            if bb.get("pct_b") is not None:
                pct_b = bb["pct_b"]
                bb_label = "near upper" if pct_b > 0.8 else "near lower" if pct_b < 0.2 else "mid"
                parts.append(f"BB {bb_label} ({pct_b:.0%})")
            if "7d_return" in t:
                parts.append(f"7d {t['7d_return']:+.1f}%")
            if "30d_return" in t:
                parts.append(f"30d {t['30d_return']:+.1f}%")
            if parts:
                ctech_lines.append(f"  {sym}: {', '.join(parts)}")
        if ctech_lines:
            sections.append("### Crypto Technical Indicators\n" + "\n".join(ctech_lines))

    return "\n\n".join(sections)


def _format_patterns(pattern_results: dict[str, dict]) -> str:
    """Candlestick patterns, crossover signals, support/resistance, volume anomalies."""
    if not pattern_results:
        return ""

    pattern_lines = []
    for sym, analysis in pattern_results.items():
        parts = []
        for p in analysis.get("candlestick_patterns", []):
            parts.append(f"{p['pattern']} ({p['signal']})")
        for s in analysis.get("crossover_signals", []):
            parts.append(f"{s['signal']} ({s['direction']})")
        levels = analysis.get("support_resistance", {})
        if levels.get("support"):
            parts.append(f"Support: ${', $'.join(str(s) for s in levels['support'][:2])}")
        if levels.get("resistance"):
            parts.append(f"Resistance: ${', $'.join(str(r) for r in levels['resistance'][:2])}")
        vol = analysis.get("volume_analysis")
        if vol and vol.get("anomaly"):
            parts.append(f"{vol['anomaly']}: {vol['meaning']}")
        agg = analysis.get("aggregate_signal")
        if agg and agg != "NEUTRAL":
            parts.insert(0, f"Pattern Signal: {agg}")
        if parts:
            pattern_lines.append(f"  {sym}: {', '.join(parts)}")

    if not pattern_lines:
        return ""

    return (
        "### PATTERN RECOGNITION (chart patterns, crossovers, support/resistance)\n"
        + "\n".join(pattern_lines)
    )


def _format_fundamentals(brief: dict) -> str:
    """PE, beta, dividend yield, 52w range, market cap, analyst consensus, earnings."""
    sections = []

    # Stock fundamentals
    fundamentals = brief.get("fundamentals", {})
    volatility = brief.get("stock_volatility", {})
    if fundamentals:
        fund_lines = []
        for sym, f in list(fundamentals.items())[:20]:
            parts = []
            sector = STOCK_SECTORS.get(sym, "?")
            parts.append(f"[{sector}]")
            if f.get("pe_ratio"):
                parts.append(f"PE {f['pe_ratio']:.1f}")
            if f.get("beta"):
                parts.append(f"Beta {f['beta']:.2f}")
            if f.get("dividend_yield"):
                parts.append(f"Div {f['dividend_yield']:.1f}%")
            if f.get("52w_high") and f.get("52w_low"):
                parts.append(f"52w ${f['52w_low']:.0f}-${f['52w_high']:.0f}")
            if f.get("market_cap_m"):
                mcap = f["market_cap_m"]
                if mcap > 1000:
                    parts.append(f"MCap ${mcap/1000:.0f}B")
                else:
                    parts.append(f"MCap ${mcap:.0f}M")
            vol = volatility.get(sym)
            if vol:
                vol_label = "HIGH" if vol > 40 else "LOW" if vol < 20 else ""
                parts.append(f"Vol {vol}%{' ' + vol_label if vol_label else ''}")
            if len(parts) > 1:
                fund_lines.append(f"  {sym}: {', '.join(parts)}")
        if fund_lines:
            sections.append("### Stock Fundamentals & Risk\n" + "\n".join(fund_lines))

    # Analyst recommendations — use Gemma consensus summaries when available
    analyst_consensus = brief.get("analyst_consensus")
    recs = brief.get("analyst_recommendations", {})
    if analyst_consensus:
        rec_lines = [f"  {sym}: {summary}" for sym, summary in analyst_consensus.items()]
        if rec_lines:
            sections.append("### Analyst Consensus (AI-summarized)\n" + "\n".join(rec_lines))
    elif recs:
        rec_lines = []
        for sym, r in list(recs.items())[:20]:
            total = r["buy"] + r["hold"] + r["sell"]
            if total > 0:
                buy_pct = round(r["buy"] / total * 100)
                signal = "STRONG BUY" if buy_pct > 70 else "MOSTLY BUY" if buy_pct > 50 else "MIXED" if r["hold"] > r["sell"] else "BEARISH"
                rec_lines.append(
                    f"  {sym}: {r['buy']} Buy / {r['hold']} Hold / {r['sell']} Sell -> {signal}"
                )
        if rec_lines:
            sections.append("### Analyst Consensus\n" + "\n".join(rec_lines))

    # Insider transactions — use Gemma summaries when available
    insider_summary = brief.get("insider_summary")
    insider = brief.get("insider_transactions", {})
    if insider_summary:
        insider_lines = [f"  {sym}: {summary}" for sym, summary in insider_summary.items()]
        if insider_lines:
            sections.append("### Insider Activity (AI-summarized)\n" + "\n".join(insider_lines))
    elif insider:
        insider_lines = []
        for sym, txns in insider.items():
            buys = [t for t in txns if t["side"] == "buy"]
            sells = [t for t in txns if t["side"] == "sell"]
            buy_total = sum(t["value"] for t in buys)
            sell_total = sum(t["value"] for t in sells)
            if buys and not sells:
                signal = "BULLISH (insiders buying)"
            elif sells and not buys:
                signal = "BEARISH (insiders selling)"
            elif buy_total > sell_total * 2:
                signal = "BULLISH (net insider buying)"
            elif sell_total > buy_total * 2:
                signal = "BEARISH (net insider selling)"
            else:
                signal = "MIXED"
            names = ", ".join(t["name"].split()[-1] for t in txns[:3])
            total_val = buy_total + sell_total
            if total_val >= 1_000_000:
                val_str = f"${total_val / 1_000_000:.1f}M"
            else:
                val_str = f"${total_val / 1_000:.0f}K"
            insider_lines.append(
                f"  {sym}: {len(buys)} buys / {len(sells)} sells ({val_str} total, {names}) -> {signal}"
            )
        if insider_lines:
            sections.append("### Insider Transactions (last 30 days)\n" + "\n".join(insider_lines))

    # Earnings calendar with urgency signals
    earnings = brief.get("earnings_calendar", [])
    if earnings:
        from datetime import date as _date, timedelta as _td
        today_str = _date.today().isoformat()
        tomorrow_str = (_date.today() + _td(days=1)).isoformat()
        earn_lines = []
        for e in earnings[:10]:
            eps_str = f" (est EPS ${e['estimate_eps']:.2f})" if e.get("estimate_eps") else ""
            e_date = e.get("date", "")
            if e_date == today_str:
                prefix = ">>> TODAY"
            elif e_date == tomorrow_str:
                prefix = ">> TOMORROW"
            else:
                prefix = f"  {e_date}"
            earn_lines.append(f"{prefix}: {e['symbol']} reports{eps_str} — expect volatility, size positions accordingly")
        sections.append("### Upcoming Earnings (next 7 days)\n" + "\n".join(earn_lines))

    return "\n\n".join(sections)


def _format_sentiment(brief: dict, invert: bool = False) -> str:
    """News headlines, company news, sentiment scores, and day-over-day context."""
    sections = []
    header_suffix = " (CONTRARIAN LENS)" if invert else ""

    # Market narrative (factual cause-effect context — same for all traders)
    narrative = brief.get("market_narrative", "")
    if narrative:
        header = (
            "### MARKET CONTEXT (factual cause-effect relationships)\n"
            "NOTE: This summary was generated by another AI model. It may contain errors, "
            "miss important context, or overweight certain narratives. Treat it as ONE input "
            "among many — not as ground truth. YOU are the decision-maker. "
            "Apply YOUR strategy's lens and cross-reference against the raw data below."
        )
        if invert:
            header += (
                "\nCONTRARIAN LENS: Where the crowd sees these patterns as directional signals, "
                "you look for the opposite. Consensus interpretations are often already priced in."
            )
        sections.append(f"{header}\n{narrative}")

    # Sentiment summary (when scores are available)
    sent = brief.get("sentiment_scores", {})
    if sent and sent.get("market_sentiment") is not None:
        market_score = sent["market_sentiment"]
        if market_score > 0.3:
            mood = "bullish"
        elif market_score > 0.1:
            mood = "moderately bullish"
        elif market_score > -0.1:
            mood = "neutral"
        elif market_score > -0.3:
            mood = "moderately bearish"
        else:
            mood = "bearish"
        summary_lines = [
            f"  Overall market sentiment: {market_score:+.2f} ({mood}, "
            f"{sent.get('scored_headline_count', 0)} headlines scored)"
        ]
        by_symbol = sent.get("by_symbol", {})
        if by_symbol:
            sym_parts = [
                f"{sym}: {info['score']:+.2f} ({info['headline_count']})"
                for sym, info in sorted(by_symbol.items(), key=lambda x: -abs(x[1]["score"]))[:5]
            ]
            summary_lines.append(f"  Per-symbol: {' | '.join(sym_parts)}")
        cats = sent.get("categories_summary", {})
        if cats:
            top_cats = [f"{k} ({v})" for k, v in list(cats.items())[:5]]
            summary_lines.append(f"  Top categories: {', '.join(top_cats)}")
        sections.append(f"### Sentiment Summary{header_suffix}\n" + "\n".join(summary_lines))

    # News: use Gemma-clustered headlines if available, else raw headlines
    clusters = brief.get("headline_clusters")
    if clusters:
        cluster_lines = []
        for c in clusters:
            sent = c.get("sentiment", 0)
            syms = ", ".join(c.get("symbols", [])) if c.get("symbols") else ""
            sym_str = f" [{syms}]" if syms else ""
            cluster_lines.append(
                f"  **{c['theme']}** ({c['count']} articles, sentiment {sent:+.2f}){sym_str}"
            )
            for h in c.get("headlines", [])[:2]:
                cluster_lines.append(f"    - {h}")
        sections.append(f"### Market News (clustered){header_suffix}\n" + "\n".join(cluster_lines))
    else:
        # Fallback: raw headlines
        news_items = brief.get("news", [])[:10]
        if news_items:
            news_lines = []
            for n in news_items:
                score = n.get("score")
                prefix = f"[{score:+.2f}] " if score is not None else ""
                if n.get("summary"):
                    news_lines.append(f"  {prefix}{n['headline']}\n    {n['summary'][:200]}")
                else:
                    news_lines.append(f"  {prefix}{n['headline']}")
            sections.append(f"### Market News{header_suffix}\n" + "\n".join(news_lines))

        # Company-specific news (raw fallback)
        company_news = brief.get("company_news", {})
        if company_news:
            news_lines = []
            for sym, articles in company_news.items():
                for a in articles:
                    score = a.get("score")
                    prefix = f"[{score:+.2f}] " if score is not None else ""
                    summary = f" — {a['summary']}" if a.get("summary") else ""
                    news_lines.append(f"  {sym}: {prefix}{a['headline']}{summary}")
            if news_lines:
                sections.append("### Company News (top movers this week)\n" + "\n".join(news_lines))

    # Crypto trending coins (what's getting attention right now)
    crypto_trending = brief.get("crypto_trending", [])
    if crypto_trending:
        ct_lines = []
        for t in crypto_trending:
            chg = t.get("price_change_24h")
            chg_str = f" {chg:+.1f}%" if chg is not None else ""
            rank = f" (Rank #{t['market_cap_rank']})" if t.get("market_cap_rank") else ""
            ct_lines.append(f"  {t['symbol']} ({t['name']}){rank}{chg_str}")
        header = "### Crypto Trending (highest search/social attention right now)"
        if invert:
            header += "\n  CONTRARIAN NOTE: Trending = crowded. When everyone is watching a coin, the easy gains are often over."
        sections.append(header + "\n" + "\n".join(ct_lines))

    # Social/retail sentiment (Yahoo trending + Crypto Fear & Greed)
    social = brief.get("social_sentiment", {})
    if social:
        social_lines = []

        # Crypto Fear & Greed Index
        fng = social.get("_crypto_fear_greed", {})
        if fng:
            score = fng.get("score", 50)
            label = fng.get("classification", "Neutral")
            signal = fng.get("signal", "NEUTRAL")
            social_lines.append(f"  Crypto Fear & Greed: {score}/100 ({label}) — {signal}")

        # Trending tickers (high retail attention)
        trending = [
            (sym, s) for sym, s in social.items()
            if sym != "_crypto_fear_greed" and s.get("trending")
        ]
        if trending:
            trending_sorted = sorted(trending, key=lambda x: x[1].get("trending_rank", 99))
            symbols_str = ", ".join(
                f"{sym} (#{s['trending_rank']})" for sym, s in trending_sorted
            )
            social_lines.append(f"  Yahoo Trending: {symbols_str}")
            social_lines.append("  HIGH_RETAIL_ATTENTION = crowded trade risk. Consider if the move is already priced in.")

        if social_lines:
            header = "### Retail Sentiment & Attention"
            if invert:
                header += "\nCONTRARIAN NOTE: When retail piles in, smart money often exits. Extreme fear = opportunity."
            sections.append(header + "\n" + "\n".join(social_lines))

    # Day-over-day shifts
    dod = brief.get("day_over_day", {})
    if dod:
        dod_lines = []
        if "regime_shift" in dod:
            dod_lines.append(f"  Market regime: {dod['regime_shift']}")
        if "spy_momentum_change" in dod:
            change = dod["spy_momentum_change"]
            direction = "accelerating" if change > 0 else "decelerating"
            dod_lines.append(f"  SPY momentum {direction} ({change:+.2f}% shift)")
        if "sentiment_shift" in dod:
            dod_lines.append(f"  {dod['sentiment_shift']}")
        if "sector_shifts" in dod:
            for shift in dod["sector_shifts"]:
                dod_lines.append(f"  {shift}")
        if dod_lines:
            sections.append("### DAY-OVER-DAY CHANGES (vs yesterday)\n" + "\n".join(dod_lines))

    result = "\n\n".join(sections)

    if invert and result:
        result += (
            "\n\nCONTRARIAN NOTE: You see the same news everyone else sees, but your edge is "
            "interpreting it OPPOSITE to the crowd. Bullish headlines = potential sell signal "
            "(everyone already bought). Bearish panic = potential buy signal (oversold)."
        )

    return result


def _format_momentum(brief: dict) -> str:
    """Top gainers/losers and momentum data from technicals."""
    sections = []

    movers_narrative = brief.get("movers_narrative", {})

    gainers = brief.get("top_gainers", [])
    if gainers:
        if movers_narrative:
            gainer_lines = []
            for g in gainers:
                sym = g.get("symbol", "")
                chg = g.get("change_pct", 0)
                narrative = movers_narrative.get(sym)
                if narrative:
                    gainer_lines.append(f"  {sym} ({chg:+.1f}%): {narrative}")
                else:
                    gainer_lines.append(f"  {sym} ({chg:+.1f}%): no catalyst identified")
            sections.append("### Top Gainers (why they moved)\n" + "\n".join(gainer_lines))
        else:
            sections.append("### Top Gainers (momentum leaders)\n" + json.dumps(gainers, indent=2))

    losers = brief.get("top_losers", [])
    if losers:
        if movers_narrative:
            loser_lines = []
            for l in losers:
                sym = l.get("symbol", "")
                chg = l.get("change_pct", 0)
                narrative = movers_narrative.get(sym)
                if narrative:
                    loser_lines.append(f"  {sym} ({chg:+.1f}%): {narrative}")
                else:
                    loser_lines.append(f"  {sym} ({chg:+.1f}%): no catalyst identified")
            sections.append("### Top Losers (why they dropped)\n" + "\n".join(loser_lines))
        else:
            sections.append("### Top Losers (potential reversals or falling knives)\n" + json.dumps(losers, indent=2))

    # Extract crypto market data (rank, volume, ATH distance, momentum) for context
    crypto_data = brief.get("crypto_market_data", {})
    if crypto_data:
        crypto_lines = []
        for sym, c in list(crypto_data.items())[:15]:
            parts = []
            if c.get("market_cap_rank"):
                parts.append(f"Rank #{c['market_cap_rank']}")
            if c.get("market_cap_b"):
                parts.append(f"MCap ${c['market_cap_b']}B")
            if c.get("volume_24h_m"):
                parts.append(f"24h Vol ${c['volume_24h_m']}M")
            if c.get("ath_drop_pct") is not None:
                pct = c["ath_drop_pct"]
                label = "NEAR ATH" if pct < 10 else "BIG DISCOUNT" if pct > 50 else ""
                parts.append(f"{pct}% below ATH{' — ' + label if label else ''}")
            if parts:
                crypto_lines.append(f"  {sym}: {', '.join(parts)}")

            # Multi timeframe momentum
            momentum_parts = []
            for period, key in [("7d", "price_change_7d"), ("14d", "price_change_14d"), ("30d", "price_change_30d")]:
                val = c.get(key)
                if val is not None:
                    momentum_parts.append(f"{period}: {val:+.1f}%")
            mcap_chg = c.get("market_cap_change_24h")
            if mcap_chg is not None:
                flow = "INFLOW" if mcap_chg > 3 else "OUTFLOW" if mcap_chg < -3 else "FLAT"
                momentum_parts.append(f"MCap 24h: {mcap_chg:+.1f}% ({flow})")
            vol_mcap = c.get("volume_to_mcap")
            if vol_mcap is not None:
                activity = "HIGH" if vol_mcap > 15 else "LOW" if vol_mcap < 3 else "NORMAL"
                momentum_parts.append(f"Vol/MCap {vol_mcap}% ({activity})")
            if momentum_parts:
                crypto_lines.append(f"    Momentum: {', '.join(momentum_parts)}")

        if crypto_lines:
            sections.append("### Crypto Market Data\n" + "\n".join(crypto_lines))

    # Crypto sector/category rotation (like stock sectors but for crypto)
    crypto_cats = brief.get("crypto_categories", [])
    if crypto_cats:
        cat_lines = []
        for cat in crypto_cats:
            chg = cat.get("change_24h", 0)
            signal = "HOT" if chg > 5 else "COLD" if chg < -5 else ""
            signal_str = f" — {signal}" if signal else ""
            cat_lines.append(
                f"  {cat['name']}: {chg:+.1f}% 24h, ${cat['market_cap_b']}B MCap{signal_str}"
            )
        sections.append("### Crypto Sector Rotation (category performance)\n" + "\n".join(cat_lines))

    return "\n\n".join(sections)


def _format_macro(brief: dict) -> str:
    """Market regime and sector rotation signals."""
    sections = []

    regime = brief.get("market_regime", {})
    if regime:
        regime_lines = []
        if "market_trend" in regime:
            spy_rsi = regime.get("spy_rsi")
            spy_7d = regime.get("spy_7d")
            spy_30d = regime.get("spy_30d")
            parts = [f"Overall Market: {regime['market_trend']}"]
            detail = []
            if spy_rsi is not None:
                detail.append(f"SPY RSI={spy_rsi}")
            if spy_7d is not None:
                detail.append(f"7d={spy_7d:+.1f}%")
            if spy_30d is not None:
                detail.append(f"30d={spy_30d:+.1f}%")
            if detail:
                parts[0] += f" ({', '.join(detail)})"
            regime_lines.append(f"  {parts[0]}")
        if "growth_vs_value" in regime:
            regime_lines.append(f"  Rotation: {regime['growth_vs_value']} (QQQ-SPY spread: {regime.get('qqq_spy_spread_7d', 0):+.1f}%)")
        if "rate_signal" in regime:
            regime_lines.append(f"  Interest Rates: {regime['rate_signal']} (TLT 7d: {regime.get('tlt_7d', 0):+.1f}%)")
        if "safe_haven_demand" in regime:
            regime_lines.append(f"  Safe Haven Demand: {regime['safe_haven_demand']} (GLD 7d: {regime.get('gld_7d', 0):+.1f}%)")
        if "small_cap_signal" in regime:
            regime_lines.append(f"  Small Cap Health: {regime['small_cap_signal']} (IWM 7d: {regime.get('iwm_7d', 0):+.1f}%)")
        if regime_lines:
            sections.append("### MARKET REGIME (read this first — it sets the context)\n" + "\n".join(regime_lines))

    sector_perf = brief.get("sector_performance", {})
    if sector_perf:
        sorted_sectors = sorted(sector_perf.items(), key=lambda x: x[1]["avg_change_pct"], reverse=True)
        sector_lines = []
        for sector, data in sorted_sectors:
            sector_lines.append(
                f"  {sector}: {data['avg_change_pct']:+.2f}% avg ({data['stocks_up']} up / {data['stocks_down']} down)"
            )
        sections.append("### SECTOR PERFORMANCE (today's rotation)\n" + "\n".join(sector_lines))

    # Crypto global market context (BTC dominance, total market cap)
    crypto_global = brief.get("crypto_global", {})
    if crypto_global:
        cg_lines = []
        if crypto_global.get("total_market_cap_t"):
            cg_lines.append(f"  Total Crypto Market Cap: ${crypto_global['total_market_cap_t']}T")
        if crypto_global.get("total_volume_24h_b"):
            cg_lines.append(f"  24h Volume: ${crypto_global['total_volume_24h_b']}B")
        btc_dom = crypto_global.get("btc_dominance")
        if btc_dom is not None:
            alt_signal = "ALT SEASON RISK" if btc_dom < 40 else "BTC DOMINANT — alts underperform" if btc_dom > 55 else "BALANCED"
            cg_lines.append(f"  BTC Dominance: {btc_dom}% ({alt_signal})")
        eth_dom = crypto_global.get("eth_dominance")
        if eth_dom is not None:
            cg_lines.append(f"  ETH Dominance: {eth_dom}%")
        mcap_chg = crypto_global.get("market_cap_change_24h")
        if mcap_chg is not None:
            flow = "INFLOW" if mcap_chg > 2 else "OUTFLOW" if mcap_chg < -2 else "FLAT"
            cg_lines.append(f"  Market Cap 24h Change: {mcap_chg:+.2f}% ({flow})")
        if cg_lines:
            sections.append("### CRYPTO MARKET OVERVIEW\n" + "\n".join(cg_lines))

    # Economic calendar (upcoming macro events)
    econ = brief.get("economic_calendar", [])
    if econ:
        cal_lines = []
        for e in econ:
            impact_label = "HIGH IMPACT" if e.get("impact", 0) >= 3 else "MEDIUM"
            prefix = ">>> TODAY: " if e.get("is_today") else f"  {e.get('date', '')}: "
            parts = [f"{prefix}{e.get('event', '')} [{impact_label}]"]
            est = e.get("estimate")
            prev = e.get("prev")
            actual = e.get("actual")
            if actual is not None:
                parts.append(f"Actual: {actual}{e.get('unit', '')}")
            if est is not None:
                parts.append(f"Est: {est}{e.get('unit', '')}")
            if prev is not None:
                parts.append(f"Prev: {prev}{e.get('unit', '')}")
            cal_lines.append(", ".join(parts))
        sections.append("### ECONOMIC CALENDAR (next 7 days)\n" + "\n".join(cal_lines))

    return "\n\n".join(sections)


def _format_optimizer(correlations: list[dict], allocation: dict, sizing: dict | None = None) -> str:
    """Correlation warnings, allocation suggestions, and position sizing."""
    sections = []

    if correlations:
        corr_lines = [f"  {c['warning']}" for c in correlations]
        sections.append(
            "### CORRELATION WARNINGS (diversification risk)\n"
            + "\n".join(corr_lines)
        )

    sugs = allocation.get("suggestions", [])
    if sugs:
        priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        sugs.sort(key=lambda s: priority_order.get(s.get("priority", "LOW"), 3))

        sug_lines = []
        for s in sugs:
            priority_tag = f"[{s['priority']}]" if s.get("priority") else ""
            action = s.get("action", "")
            sym = s.get("symbol", "")
            sym_str = f" {sym}" if sym else ""
            sug_lines.append(f"  {priority_tag} {action}{sym_str}: {s['reason']}")

        meta = []
        meta.append(f"Cash: {allocation.get('cash_pct', 0)}% (target min {allocation.get('cash_target_pct', 0)}%)")
        meta.append(f"Crypto: {allocation.get('crypto_pct', 0)}% (max {allocation.get('crypto_max_pct', 0)}%)")
        meta.append(f"Positions: {allocation.get('num_positions', 0)}")

        sections.append(
            "### PORTFOLIO OPTIMIZER SUGGESTIONS\n"
            + "  " + " | ".join(meta) + "\n"
            + "  These are computed suggestions — you may accept, modify, or reject them.\n"
            + "\n".join(sug_lines)
        )

    # Position sizing suggestions
    if sizing:
        size_lines = []
        for sym, info in sorted(sizing.items(), key=lambda x: -x[1]["suggested_pct"]):
            size_lines.append(
                f"  {sym}: ~{info['suggested_pct']}% (${info['dollar_amount']:,}) — {info['reasoning']}"
            )
        if size_lines:
            sections.append(
                "### SUGGESTED POSITION SIZES (based on signal strength and volatility)\n"
                + "\n".join(size_lines)
            )

    return "\n\n".join(sections)


def _format_stocks_by_sector() -> str:
    """Format supported stocks grouped by sector."""
    by_sector: dict[str, list[str]] = {}
    for sym, name in TOP_STOCKS.items():
        sector = STOCK_SECTORS.get(sym, "Other")
        by_sector.setdefault(sector, []).append(f"{sym} ({name})")
    lines = []
    for sector in sorted(by_sector.keys()):
        lines.append(f"  {sector}: {', '.join(by_sector[sector])}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module: Signal Ranker — composite data synthesis
# ---------------------------------------------------------------------------

def _compute_asset_scores(brief: dict) -> list[dict]:
    """Combine technicals, fundamentals, sentiment, momentum into a composite
    score per asset.  Returns sorted list of {symbol, score, factors, conflicts}."""

    results = []

    # --- Stocks ---
    stock_technicals = brief.get("stock_technicals", {})
    fundamentals = brief.get("fundamentals", {})
    sentiment_data = brief.get("sentiment_scores", {})
    analyst_recs = brief.get("analyst_recommendations", {})
    insider_txns = brief.get("insider_transactions", {})
    volatility = brief.get("stock_volatility", {})

    by_symbol_sent = sentiment_data.get("by_symbol", {}) if sentiment_data else {}

    for sym in set(list(stock_technicals.keys()) + list(fundamentals.keys())):
        score = 0
        factors = []
        conflicts = []
        tech = stock_technicals.get(sym, {})
        fund = fundamentals.get(sym, {})

        # Technical component (max ±40)
        rsi = tech.get("rsi_14")
        if rsi is not None:
            if rsi < 30:
                s = 15
                factors.append(f"RSI {rsi:.0f} (oversold)")
            elif rsi > 70:
                s = -15
                conflicts.append(f"RSI {rsi:.0f} (overbought)")
            else:
                s = 0
            score += s

        sig = tech.get("signal", {})
        if sig.get("score"):
            sig_score = sig["score"]
            # Normalize from ~(-100,+100) to (-15,+15)
            s = max(-15, min(15, sig_score // 7))
            score += s
            label = sig.get("label", "")
            if s > 5:
                factors.append(f"signal {label} ({sig_score:+d})")
            elif s < -5:
                conflicts.append(f"signal {label} ({sig_score:+d})")

        vs_sma20 = tech.get("vs_sma_20")
        vs_sma50 = tech.get("vs_sma_50")
        if vs_sma20 is not None and vs_sma50 is not None:
            if vs_sma20 > 0 and vs_sma50 > 0:
                score += 10
                factors.append("above SMA20/50")
            elif vs_sma20 < 0 and vs_sma50 < 0:
                score -= 10
                conflicts.append("below SMA20/50")

        # Fundamental component (max ±30)
        rec = analyst_recs.get(sym, {})
        if rec:
            total = rec.get("buy", 0) + rec.get("hold", 0) + rec.get("sell", 0)
            if total > 0:
                buy_pct = rec["buy"] / total
                if buy_pct > 0.7:
                    score += 10
                    factors.append(f"analyst Strong Buy ({buy_pct:.0%})")
                elif buy_pct < 0.3:
                    score -= 10
                    conflicts.append(f"analyst bearish ({buy_pct:.0%} buy)")

        insider = insider_txns.get(sym, [])
        if insider:
            buys = sum(t["value"] for t in insider if t["side"] == "buy")
            sells = sum(t["value"] for t in insider if t["side"] == "sell")
            if buys > sells * 2 and buys > 100_000:
                score += 10
                factors.append(f"insider buying ${buys / 1e6:.1f}M")
            elif sells > buys * 2 and sells > 100_000:
                score -= 10
                conflicts.append(f"insider selling ${sells / 1e6:.1f}M")

        # Sentiment component (max ±20)
        sym_sent = by_symbol_sent.get(sym, {})
        if sym_sent.get("score") is not None:
            sent_s = sym_sent["score"]
            s = max(-20, min(20, int(sent_s * 40)))
            score += s
            if s > 5:
                factors.append(f"sentiment {sent_s:+.2f}")
            elif s < -5:
                conflicts.append(f"sentiment {sent_s:+.2f}")

        # Momentum component (max ±10)
        ret_7d = tech.get("7d_return")
        if ret_7d is not None:
            if ret_7d > 2:
                score += 5
                factors.append(f"7d {ret_7d:+.1f}%")
            elif ret_7d < -2:
                score -= 5
                conflicts.append(f"7d {ret_7d:+.1f}%")

        rel_vol = tech.get("relative_volume")
        if rel_vol is not None:
            if rel_vol > 1.5:
                factors.append(f"volume {rel_vol:.1f}x (high)")
            elif rel_vol < 0.5:
                conflicts.append(f"volume {rel_vol:.1f}x (thin)")

        sector = STOCK_SECTORS.get(sym, "")
        vol = volatility.get(sym)
        vol_str = f", vol {vol}%" if vol else ""

        if factors or conflicts:
            results.append({
                "symbol": sym,
                "asset_type": "stock",
                "score": score,
                "sector": sector,
                "vol": vol_str,
                "factors": factors,
                "conflicts": conflicts,
            })

    # --- Crypto ---
    crypto_tech = brief.get("crypto_technicals", {})
    crypto_market = brief.get("crypto_market_data", {})
    for sym in crypto_tech:
        score = 0
        factors = []
        conflicts = []
        tech = crypto_tech[sym]

        rsi = tech.get("rsi_14")
        if rsi is not None:
            if rsi < 30:
                score += 15
                factors.append(f"RSI {rsi:.0f} (oversold)")
            elif rsi > 70:
                score -= 15
                conflicts.append(f"RSI {rsi:.0f} (overbought)")

        sig = tech.get("signal", {})
        if sig.get("score"):
            s = max(-15, min(15, sig["score"] // 7))
            score += s
            label = sig.get("label", "")
            if s > 5:
                factors.append(f"signal {label} ({sig['score']:+d})")
            elif s < -5:
                conflicts.append(f"signal {label} ({sig['score']:+d})")

        vs_sma20 = tech.get("vs_sma_20")
        vs_sma50 = tech.get("vs_sma_50")
        if vs_sma20 is not None and vs_sma50 is not None:
            if vs_sma20 > 0 and vs_sma50 > 0:
                score += 10
                factors.append("above SMA20/50")
            elif vs_sma20 < 0 and vs_sma50 < 0:
                score -= 10
                conflicts.append("below SMA20/50")

        ret_7d = tech.get("7d_return")
        if ret_7d is not None:
            if ret_7d > 3:
                score += 5
                factors.append(f"7d {ret_7d:+.1f}%")
            elif ret_7d < -3:
                score -= 5
                conflicts.append(f"7d {ret_7d:+.1f}%")

        # Crypto-specific: ATH distance
        cm = crypto_market.get(sym, {})
        ath_drop = cm.get("ath_drop_pct")
        if ath_drop is not None and ath_drop > 50:
            score += 5
            factors.append(f"{ath_drop}% below ATH")

        sym_sent = by_symbol_sent.get(sym, {})
        if sym_sent.get("score") is not None:
            s = max(-20, min(20, int(sym_sent["score"] * 40)))
            score += s
            if s > 5:
                factors.append(f"sentiment {sym_sent['score']:+.2f}")
            elif s < -5:
                conflicts.append(f"sentiment {sym_sent['score']:+.2f}")

        if factors or conflicts:
            results.append({
                "symbol": sym,
                "asset_type": "crypto",
                "score": score,
                "sector": "Crypto",
                "vol": "",
                "factors": factors,
                "conflicts": conflicts,
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def _format_signal_ranker(brief: dict) -> str:
    """Format composite signal scores with anti-convergence framing."""
    scored = _compute_asset_scores(brief)
    if not scored:
        return ""

    lines = [
        "### COMPOSITE DATA SYNTHESIS",
        "This section combines technicals, fundamentals, sentiment, and momentum",
        "into a single view per asset. These scores reflect what the DATA shows,",
        "not what you should DO. A contrarian seeing +80 may correctly sell (crowded",
        "trade). A momentum trader may correctly buy. A value investor may ignore it",
        "entirely if the PE doesn't fit. INTERPRET THROUGH YOUR OWN STRATEGY.",
        "",
        "Scores range from roughly -100 (bearish data) to +100 (bullish data).",
        "Conflicting signals are listed — these are often MORE informative than",
        "the score itself. A stock at +60 with zero conflicts is different from",
        "one at +60 with three strong bearish flags that happen to be outweighed.",
        "",
        "IMPORTANT — asymmetry in sell signals: A bearish flip (RSI > 70, weakening",
        "SMA trend, or a sudden negative composite) in a sustained uptrend is often a",
        "CONTINUATION signal, not a reversal. These flags identify overbought",
        "conditions, not tops. Selling a strong winner purely because its ranker",
        "score rolled over has historically left meaningful upside on the table.",
        "If you're tempted to exit on a bearish flip, require confirming evidence:",
        "a catalyst (earnings miss, sector downgrade), a broken structural level,",
        "or a thesis that has actually played out.",
        "",
    ]

    # Separate stocks and crypto
    stocks = [s for s in scored if s["asset_type"] == "stock"]
    crypto = [s for s in scored if s["asset_type"] == "crypto"]

    if stocks:
        lines.append("[Stocks — ranked by data alignment]")
        for s in stocks[:20]:
            score = s["score"]
            sym = s["symbol"]
            sector = s["sector"]
            vol = s["vol"]
            factor_str = " | ".join(s["factors"]) if s["factors"] else "no strong bullish signals"
            lines.append(f"  {sym} ({score:+d}) [{sector}{vol}]: {factor_str}")
            if s["conflicts"]:
                conflict_str = " | ".join(s["conflicts"])
                lines.append(f"    ^ Conflicts: {conflict_str}")
        lines.append("")

    if crypto:
        lines.append("[Crypto — ranked by data alignment]")
        for s in crypto[:15]:
            score = s["score"]
            sym = s["symbol"]
            factor_str = " | ".join(s["factors"]) if s["factors"] else "no strong bullish signals"
            lines.append(f"  {sym} ({score:+d}): {factor_str}")
            if s["conflicts"]:
                conflict_str = " | ".join(s["conflicts"])
                lines.append(f"    ^ Conflicts: {conflict_str}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module: Trade Context — historical lookback from own trades
# ---------------------------------------------------------------------------

def _format_trade_context(ctx: dict) -> str:
    """Compute trading track record statistics from trader's own history.
    Shows what has worked and what hasn't for THIS specific trader."""
    trade_stats = ctx.get("trade_context")
    if not trade_stats:
        return ""

    lines = [
        "### YOUR HISTORICAL TRACK RECORD",
        "Statistics from your own past trades. Use this as a mirror — what patterns",
        "in YOUR behavior led to wins vs losses? This is YOUR data, not general advice.",
        "",
    ]

    # Overall stats
    total_sells = trade_stats.get("total_round_trips", 0)
    if total_sells == 0:
        lines.append("  Not enough completed trades for statistical analysis yet.")
        return "\n".join(lines)

    win_rate = trade_stats.get("win_rate", 0)
    avg_win = trade_stats.get("avg_win_pct", 0)
    avg_loss = trade_stats.get("avg_loss_pct", 0)

    # Pre-computed KEY PATTERN line so the model doesn't have to synthesize from raw stats.
    # This line cites the strongest + weakest sector and flags any losing streak — these
    # are the takeaways most likely to change today's decision.
    by_sector = trade_stats.get("by_sector", {})
    sector_ranked = [
        (s, v) for s, v in sorted(by_sector.items(), key=lambda x: x[1]["avg_pnl"], reverse=True)
        if v["count"] >= 2
    ]
    by_type = trade_stats.get("by_asset_type", {})
    streak = trade_stats.get("streak", {})

    takeaway_parts = []
    if sector_ranked:
        best_s, best_v = sector_ranked[0]
        takeaway_parts.append(
            f"strongest sector is {best_s} ({best_v['win_rate']:.0f}% WR over {best_v['count']} trades — size up here)"
        )
        if len(sector_ranked) >= 2:
            worst_s, worst_v = sector_ranked[-1]
            if worst_v["avg_pnl"] < best_v["avg_pnl"] - 5:
                takeaway_parts.append(
                    f"weakest is {worst_s} ({worst_v['win_rate']:.0f}% WR over {worst_v['count']} — trim or skip)"
                )
    if len(by_type) > 1:
        stocks_pnl = by_type.get("stock", {}).get("avg_pnl", 0)
        crypto_pnl = by_type.get("crypto", {}).get("avg_pnl", 0)
        if abs(stocks_pnl - crypto_pnl) > 5:
            winner = ("stocks", stocks_pnl) if stocks_pnl > crypto_pnl else ("crypto", crypto_pnl)
            loser = ("crypto", crypto_pnl) if stocks_pnl > crypto_pnl else ("stocks", stocks_pnl)
            takeaway_parts.append(
                f"you outperform in {winner[0]} (avg {winner[1]:+.1f}%) vs {loser[0]} ({loser[1]:+.1f}%)"
            )
    if streak.get("direction") == "losing" and streak.get("length", 0) >= 3:
        takeaway_parts.append(
            f"you're on a {streak['length']}-trade losing streak — reduce size until confidence returns"
        )
    elif streak.get("direction") == "winning" and streak.get("length", 0) >= 4:
        takeaway_parts.append(
            f"you're on a {streak['length']}-trade winning streak — stay disciplined, don't let confidence become overconfidence"
        )

    if takeaway_parts:
        lines.append(f"  KEY PATTERN: {'; '.join(takeaway_parts)}.")
        lines.append("")

    lines.append(f"  Overall: {total_sells} round-trips, {win_rate:.0f}% win rate")
    lines.append(f"  Avg winner: +{avg_win:.1f}% | Avg loser: {avg_loss:.1f}%")

    # By asset type
    if len(by_type) > 1:
        lines.append("")
        lines.append("  By asset type:")
        for atype, stats in by_type.items():
            wr = stats["win_rate"]
            label = atype.capitalize()
            lines.append(f"    {label}: {stats['count']} trades, {wr:.0f}% win rate, avg P&L {stats['avg_pnl']:+.1f}%")

    # By holding period
    by_hold = trade_stats.get("by_hold_period", {})
    if by_hold:
        lines.append("")
        lines.append("  By holding period:")
        for period, stats in by_hold.items():
            lines.append(f"    {period}: {stats['count']} trades, {stats['win_rate']:.0f}% win rate, avg P&L {stats['avg_pnl']:+.1f}%")

    # By sector (stocks only)
    if sector_ranked:
        lines.append("")
        lines.append("  By sector (strongest → weakest):")
        for sector, stats in sector_ranked:
            lines.append(f"    {sector}: {stats['count']} trades, {stats['win_rate']:.0f}% win, avg {stats['avg_pnl']:+.1f}%")

    # Recent streak
    streak = trade_stats.get("streak", {})
    if streak.get("length", 0) >= 2:
        direction = streak["direction"]  # "winning" or "losing"
        length = streak["length"]
        if direction == "losing" and length >= 3:
            lines.append(f"\n  ** {length}-trade losing streak. Consider reducing position sizes until confidence returns.")
        elif direction == "winning" and length >= 3:
            lines.append(f"\n  {length}-trade winning streak. Stay disciplined — don't let confidence become overconfidence.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module: Dynamic Risk — drawdown-aware position sizing
# ---------------------------------------------------------------------------

def _format_dynamic_risk(ctx: dict) -> str:
    """Format drawdown-aware risk adjustments based on portfolio equity curve."""
    risk_data = ctx.get("dynamic_risk")
    if not risk_data:
        return ""

    lines = [
        "### DYNAMIC RISK ADJUSTMENT (based on your equity curve)",
        "Your recent performance affects how much risk you should take today.",
        "These are guardrails, not commands — but ignoring drawdown risk is how",
        "small losses become large ones.",
        "",
    ]

    peak = risk_data.get("peak_value", 100_000)
    current = risk_data.get("current_value", 100_000)
    dd_pct = risk_data.get("drawdown_pct", 0)
    dd_days = risk_data.get("drawdown_days", 0)
    multiplier = risk_data.get("size_multiplier", 1.0)
    trend = risk_data.get("equity_trend", "flat")
    recent_return = risk_data.get("recent_5d_return", 0)

    # Equity state
    if dd_pct < 1:
        lines.append(f"  Equity state: NEAR PEAK (${current:,.0f}, peak ${peak:,.0f})")
        lines.append(f"  Position sizing: FULL (1.0x) — no drawdown adjustment needed")
    elif dd_pct < 5:
        lines.append(f"  Equity state: MILD DRAWDOWN (-{dd_pct:.1f}% from ${peak:,.0f} peak, {dd_days}d)")
        lines.append(f"  Position sizing: REDUCED ({multiplier:.2f}x) — preserve capital while drawdown persists")
    elif dd_pct < 10:
        lines.append(f"  Equity state: MODERATE DRAWDOWN (-{dd_pct:.1f}% from ${peak:,.0f} peak, {dd_days}d)")
        lines.append(f"  Position sizing: DEFENSIVE ({multiplier:.2f}x) — focus on high-conviction trades only")
        lines.append(f"  Consider: fewer positions, tighter stops, higher cash allocation")
    else:
        lines.append(f"  Equity state: SEVERE DRAWDOWN (-{dd_pct:.1f}% from ${peak:,.0f} peak, {dd_days}d)")
        lines.append(f"  Position sizing: MINIMAL ({multiplier:.2f}x) — capital preservation is priority")
        lines.append(f"  Reduce exposure. Do not try to 'make it back' with larger bets.")

    # Trend context
    if trend == "recovering":
        lines.append(f"  Trend: RECOVERING (5d return {recent_return:+.1f}%) — drawdown may be ending")
    elif trend == "declining":
        lines.append(f"  Trend: DECLINING (5d return {recent_return:+.1f}%) — conditions worsening")
    elif trend == "flat":
        lines.append(f"  Trend: FLAT (5d return {recent_return:+.1f}%) — no clear direction")

    return "\n".join(lines)


def _format_options_flow(brief: dict) -> str:
    """VIX (CBOE Volatility Index) — the options market's fear gauge."""
    flow = brief.get("options_flow")
    if not flow:
        return ""

    vix = flow.get("vix")
    signal = flow.get("signal", "NEUTRAL")
    trend = flow.get("trend")
    change_pct = flow.get("change_5d_pct")
    stale = flow.get("stale_from_previous_day")

    # Build a one-line QUOTABLE callout the model can drop verbatim into
    # reasoning. Same playbook as the Trade Context KEY PATTERN line and the
    # Expert Opinion ticker callouts — short, citable, ranked-up in the prompt.
    quotable_parts = []
    if vix is not None:
        quotable_parts.append(f"VIX {vix} ({signal})")
    if trend and change_pct is not None:
        quotable_parts.append(f"{trend} {change_pct:+.1f}% 5d")
    if stale:
        quotable_parts.append("[stale, fallback]")
    quotable = ", ".join(quotable_parts)

    lines = [
        "### Options Flow (VIX — CBOE Volatility Index)",
    ]
    if quotable:
        lines.append(f"QUOTABLE: {quotable} — cite this directly when adjusting risk-on/off positioning today.")
        lines.append("")
    lines.extend([
        "NOTE: VIX measures expected 30-day S&P 500 volatility, derived from options prices. "
        "It is the market's consensus FEAR level. Different strategies interpret fear differently — "
        "a momentum trader sees high VIX as a warning to reduce risk, while a contrarian sees "
        "it as a buying opportunity. Apply YOUR strategy's logic.",
    ])

    if vix is not None:
        lines.append(f"  VIX level: {vix} ({signal})")
        if signal == "EXTREME_FEAR":
            lines.append("  Context: VIX above 35 — options market pricing in severe turbulence. "
                         "Historically, extreme VIX spikes have preceded both further crashes AND "
                         "sharp V-shaped reversals. The data alone does not tell you which.")
        elif signal == "ELEVATED_FEAR":
            lines.append("  Context: VIX 25-35 — meaningful fear. Market participants are paying up "
                         "for downside protection. Conditions are volatile.")
        elif signal == "COMPLACENT" or signal == "EXTREME_COMPLACENCY":
            lines.append("  Context: VIX below 15 — very low expected volatility. Markets are calm "
                         "but complacency can precede sudden corrections. Low VIX has preceded both "
                         "continued rallies AND sharp selloffs.")

    high_10d = flow.get("high_10d")
    low_10d = flow.get("low_10d")
    if high_10d is not None and low_10d is not None:
        lines.append(f"  10-day range: {low_10d} — {high_10d}")

    trend = flow.get("trend")
    change_5d = flow.get("change_5d")
    change_pct = flow.get("change_5d_pct")
    if trend and change_5d is not None:
        lines.append(f"  5-day trend: {trend} ({change_5d:+.2f} pts, {change_pct:+.1f}%)")
        if trend == "FEAR_SPIKING":
            lines.append("  Volatility is rising sharply — market stress increasing.")
        elif trend == "FEAR_COLLAPSING":
            lines.append("  Volatility is dropping fast — market calming rapidly.")

    return "\n".join(lines)


def _format_yield_curve(brief: dict) -> str:
    """Treasury yields and curve shape — rate and recession indicators."""
    curve = brief.get("yield_curve")
    if not curve:
        return ""

    lines = [
        "### Yield Curve & Interest Rates",
        "NOTE: The yield curve is one of the most reliable macro indicators, but its signals "
        "play out over months to years, not days. An inverted curve preceded every US recession "
        "since 1970, but the lag between inversion and recession ranges from 6 to 24 months. "
        "Use this as a backdrop for your strategy, not as a daily trading signal.",
    ]

    rates = curve.get("rates", {})
    if rates:
        rate_parts = []
        for label in ["Fed Funds", "2Y", "10Y", "30Y"]:
            info = rates.get(label)
            if info:
                rate_parts.append(f"{label}: {info['rate']:.3f}%")
        if rate_parts:
            lines.append(f"  Current rates: {' | '.join(rate_parts)}")

    spread = curve.get("spread_10y_2y")
    if spread is not None:
        signal = curve.get("curve_signal", "UNKNOWN")
        recession = curve.get("recession_risk", "UNKNOWN")
        lines.append(f"  10Y-2Y spread: {spread:+.3f}% ({signal})")
        lines.append(f"  Recession risk indicator: {recession}")
        if signal == "DEEPLY_INVERTED":
            lines.append("  Context: Deeply inverted curve. Historically this has preceded recessions, "
                         "but the timing is uncertain and markets can rally for months during inversions.")
        elif signal == "INVERTED":
            lines.append("  Context: Mildly inverted. Bond market is pricing in economic slowdown or rate cuts.")
        elif signal == "FLAT":
            lines.append("  Context: Flat curve suggests uncertainty about economic direction.")

    spread_30_10 = curve.get("spread_30y_10y")
    if spread_30_10 is not None:
        lines.append(f"  30Y-10Y spread: {spread_30_10:+.3f}% (term premium)")

    rate_exp = curve.get("rate_expectation")
    if rate_exp:
        if rate_exp == "CUTS_EXPECTED":
            lines.append("  Bond market pricing: RATE CUTS expected (2Y below Fed Funds)")
            lines.append("  Implication: Falling rates tend to support growth stocks and crypto. "
                         "But cuts also signal the Fed sees economic weakness.")
        elif rate_exp == "HIKES_EXPECTED":
            lines.append("  Bond market pricing: RATE HIKES expected (2Y above Fed Funds)")
            lines.append("  Implication: Rising rates tend to pressure growth/speculative assets. "
                         "But hikes also signal a strong economy.")
        else:
            lines.append("  Bond market pricing: Rates ON HOLD (2Y near Fed Funds)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module: Expert Opinion — independent analyst digest
# ---------------------------------------------------------------------------

def _format_expert_opinion(brief: dict, invert: bool = False) -> str:
    """Format the expert opinion digest from analyst blog scraping pipeline.
    Surfaces the TICKER CALLS section at the top so traders can quote specific
    calls. Falls back gracefully if the digest isn't structured."""
    digest = brief.get("expert_opinion_digest")
    if not digest:
        return ""

    header_suffix = " (CONTRARIAN LENS)" if invert else ""

    lines = [
        f"### Expert Opinion Digest{header_suffix}",
        "Opinions from external independent analysts (Wolf Street, Mish Talk, Calculated Risk,",
        "and others). They may be wrong, biased, or outdated. Treat as ONE perspective among",
        "many. CITE THE SOURCE if you use one of these calls in your reasoning.",
    ]

    if invert:
        lines.append(
            "CONTRARIAN LENS: Where these analysts see consensus, you see a crowded trade. "
            "Where they see risk, you see opportunity. Their conviction is your contrarian signal."
        )

    # Try to extract the TICKER CALLS section and surface it as a quotable callout.
    import re
    ticker_section = ""
    if isinstance(digest, str):
        m = re.search(r"TICKER CALLS:\s*\n(.+?)(?=\n[A-Z][A-Z ]+:|\Z)", digest, re.DOTALL)
        if m:
            ticker_section = m.group(1).strip()

    if ticker_section and "no ticker" not in ticker_section.lower():
        lines.append("")
        lines.append("QUOTABLE TICKER CALLS (cite these directly when relevant):")
        for line in ticker_section.splitlines():
            line = line.strip()
            if line:
                lines.append(f"  {line}")

    lines.append("")
    lines.append(digest)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Discipline report card (always-on, not a selectable module)
# ---------------------------------------------------------------------------

def _format_discipline(discipline: dict | None) -> str:
    """Format the trade discipline report card for the AI prompt."""
    if not discipline:
        return ""

    grade = discipline.get("grade", "?")
    score = discipline.get("overall_score", 0)
    scores = discipline.get("scores", {})
    violations = discipline.get("violations", [])

    lines = [
        f"## Your Discipline Report Card: {grade} ({score}/100)",
        "This grades how well you follow YOUR OWN risk rules. Fix violations before making new trades.",
    ]

    # Score breakdown
    breakdown = []
    for category, val in scores.items():
        label = category.replace("_", " ").title()
        icon = "pass" if val >= 75 else "FAIL" if val < 50 else "warn"
        breakdown.append(f"  {label}: {val}/100 [{icon}]")
    lines.append("\n".join(breakdown))

    if violations:
        lines.append("\nViolations (address these BEFORE making new buys):")
        for v in violations:
            lines.append(f"  - {v}")

    if grade in ("A",):
        lines.append("\nYou're following your rules well. Keep it up.")
    elif grade in ("D", "F"):
        lines.append(
            "\nYour discipline is poor. Focus ENTIRELY on fixing violations "
            "before adding any new positions. Sell first, buy later."
        )

    return "\n".join(lines)


def _format_btc_onchain(brief: dict) -> str:
    """Format BTC on-chain + derivatives metrics with regime classifications.
    Lead with a QUOTABLE one-liner the model can drop into reasoning verbatim."""
    oc = brief.get("btc_onchain")
    if not oc:
        return ""

    lines = ["### BTC On-Chain & Derivatives"]

    # Quotable summary line — same pattern as Trade Context KEY PATTERN and VIX QUOTABLE
    quotable_parts = []
    if "mvrv_z" in oc:
        quotable_parts.append(f"MVRV-Z {oc['mvrv_z']:.2f} ({oc.get('mvrv_z_regime','?')})")
    if "nupl" in oc:
        quotable_parts.append(f"NUPL {oc['nupl']:.2f} ({oc.get('nupl_regime','?')})")
    if "puell_multiple" in oc:
        quotable_parts.append(f"Puell {oc['puell_multiple']:.2f} ({oc.get('puell_regime','?')})")
    if "cohort_signal" in oc:
        quotable_parts.append(f"cohort: {oc['cohort_signal']}")
    if quotable_parts:
        lines.append(f"QUOTABLE: {' | '.join(quotable_parts)} — cite these directly when reasoning about BTC/ETH entries.")
        lines.append("")

    lines.append(
        "NOTE: These are network-level and futures-market metrics, independent "
        "of price action. MVRV-Z and NUPL near 0 (or below) have called every "
        "BTC cycle bottom since 2013. Puell <0.5 marks miner capitulation, "
        "historically a buy signal. Funding rate and long/short ratio reveal "
        "whether a drawdown is real selling or leveraged shake-out."
    )

    # Long-term valuation block
    if any(k in oc for k in ("mvrv_z", "nupl", "realized_price", "puell_multiple")):
        lines.append("")
        lines.append("LONG-TERM VALUATION:")
        if "mvrv_z" in oc:
            lines.append(
                f"  MVRV-Z Score: {oc['mvrv_z']:.2f} → {oc.get('mvrv_z_regime','?')}"
                f"  (below 0 = deep bottom; 0-2 = accumulation; >7 = top)"
            )
        if "nupl" in oc:
            lines.append(
                f"  NUPL (Net Unrealized P/L): {oc['nupl']:.2f} → {oc.get('nupl_regime','?')}"
                f"  (<0 = capitulation; 0-0.25 = hope/fear; >0.75 = euphoria)"
            )
        if "realized_price" in oc:
            lines.append(
                f"  Realized Price: ${oc['realized_price']:,.0f}"
                f"  (network's average cost basis — BTC below this = aggregate holders losing)"
            )
        if "puell_multiple" in oc:
            lines.append(
                f"  Puell Multiple: {oc['puell_multiple']:.2f} → {oc.get('puell_regime','?')}"
                f"  (<0.5 = miner capitulation buy zone; >4 = miner sell pressure / top)"
            )

    # Network health
    if any(k in oc for k in ("hash_rate_eh", "active_addresses")):
        lines.append("")
        lines.append("NETWORK HEALTH:")
        if "hash_rate_eh" in oc:
            lines.append(f"  Hash rate: {oc['hash_rate_eh']:.1f} EH/s (high & rising = strong network conviction)")
        if "active_addresses" in oc:
            lines.append(f"  Active addresses (24h): {oc['active_addresses']:,.0f}")

    # Derivatives
    if any(k in oc for k in ("funding_rate_8h", "long_short_ratio")):
        lines.append("")
        lines.append("DERIVATIVES (Binance perpetuals):")
        if "funding_rate_8h" in oc:
            lines.append(
                f"  Funding rate (8h): {oc['funding_rate_8h']:+.4f}% "
                f"(~{oc.get('funding_rate_apr', 0):+.1f}% APR) → {oc.get('funding_signal','?')}"
            )
        if "long_short_ratio" in oc:
            lines.append(
                f"  Long/Short ratio: {oc['long_short_ratio']:.2f} "
                f"({oc.get('long_account_pct','?')}% long accounts) → {oc.get('positioning_signal','?')}"
            )

    # Synthesis call-out
    if oc.get("cohort_signal") == "CONTRARIAN_BUY_ZONE":
        lines.append("")
        lines.append(
            "  SYNTHESIS: Multiple long-term valuation metrics are signaling "
            "ACCUMULATION ZONE simultaneously — this combination historically "
            "marks BTC cycle bottoms. For Tier 1 BTC/ETH strategies, this is "
            "the highest-conviction kind of buy signal on-chain data provides."
        )
    elif oc.get("cohort_signal") == "TOP_OR_NEUTRAL":
        lines.append("")
        lines.append("  SYNTHESIS: Valuation metrics not in accumulation zone. Standard buy criteria apply.")

    return "\n".join(lines)


def _format_fleet_conviction(fleet: dict | None, invert: bool = False) -> str:
    """Show what the 20-trader AI fleet is collectively buying and selling.

    `invert=True` is set for Contrarian Carl — flips the framing so the model
    is told to FADE consensus instead of follow it.

    Critical guardrail: we expose aggregate counts only, never which specific
    trader bought what. Otherwise personalities would leak into each other.
    """
    if not fleet or not fleet.get("symbols"):
        return ""

    consensus = fleet.get("consensus_picks") or []
    dumps = fleet.get("consensus_dumps") or []
    controversial = fleet.get("controversial") or []
    fleet_size = fleet.get("fleet_size") or 0
    lookback = fleet.get("lookback_days", 3)

    if not (consensus or dumps or controversial):
        return ""

    lines = ["### Fleet Conviction (cross-trader signal)"]

    if invert:
        lines.append(
            "QUOTABLE (CONTRARIAN MODE): When the fleet is unanimous, you FADE it. "
            "Consensus accumulation = potential top forming. Consensus distribution = "
            "potential bottom forming. Controversial = where genuine alpha lives."
        )
    else:
        lines.append(
            "QUOTABLE: This is what the other 19 AI traders are doing — independent agents "
            "reading the same brief. High consensus = corroboration. Split = ambiguity. "
            "Use it as one input among many, not as instruction."
        )
    lines.append("")
    lines.append(
        f"NOTE: Aggregated from {fleet_size}-trader fleet over the last {lookback} days. "
        "Flow score: +1.0 = unanimous buying, -1.0 = unanimous selling. "
        "Breadth: % of fleet currently holding the symbol. Specific trader identities "
        "are intentionally hidden to prevent strategy leakage."
    )

    if consensus:
        if invert:
            lines.append("")
            lines.append("⚠ FADE CANDIDATES — fleet is piling in here (potential top forming):")
        else:
            lines.append("")
            lines.append("Fleet ACCUMULATING (consensus buys):")
        for p in consensus[:6]:
            lines.append(
                f"  {p['symbol']:6}  flow={p['flow_score']:+.2f}  "
                f"buyers={p['unique_buyers']} vs sellers={p['unique_sellers']}  "
                f"holders={p['breadth_pct']*100:.0f}% of fleet  [{p['conviction_label']}]"
            )

    if dumps:
        if invert:
            lines.append("")
            lines.append("⚠ FADE CANDIDATES — fleet is dumping here (potential bottom forming):")
        else:
            lines.append("")
            lines.append("Fleet DISTRIBUTING (consensus sells):")
        for p in dumps[:6]:
            lines.append(
                f"  {p['symbol']:6}  flow={p['flow_score']:+.2f}  "
                f"buyers={p['unique_buyers']} vs sellers={p['unique_sellers']}  "
                f"holders={p['breadth_pct']*100:.0f}% of fleet  [{p['conviction_label']}]"
            )

    if controversial:
        lines.append("")
        if invert:
            lines.append("ALPHA HUNTING GROUND — fleet is split, this is where independent analysis pays:")
        else:
            lines.append("CONTROVERSIAL — fleet is split, weight your own conviction:")
        for p in controversial[:4]:
            lines.append(
                f"  {p['symbol']:6}  buyers={p['unique_buyers']} vs sellers={p['unique_sellers']}  "
                f"holders={p['breadth_pct']*100:.0f}% of fleet"
            )

    lines.append("")
    if invert:
        lines.append(
            "  SYNTHESIS: Your edge is going AGAINST the fleet when conviction is high. "
            "Genuine contrarian moves require the fleet to be wrong AND visible. "
            "Don't fade a controversial name — fade unanimous ones."
        )
    else:
        lines.append(
            "  SYNTHESIS: Fleet consensus is one corroborating input. "
            "Strong consensus on quality names = corroboration. Strong consensus on hype = "
            "warning sign. Use this with your other modules, don't substitute for them."
        )

    return "\n".join(lines)


def _format_cross_asset(brief: dict) -> str:
    """Format DXY, gold, real yields, breakevens, WTI with a regime synthesis line.
    These are the four macro channels that drive risk-asset valuations:
    - DXY ↑ = headwind for crypto + EM equities (denominated in $)
    - Real yields ↑ = headwind for gold + duration + growth equities
    - Breakevens ↑ = tailwind for cyclicals + commodities
    - WTI = supply/demand inflation pulse; affects energy + transport
    """
    ca = brief.get("cross_asset")
    if not ca or not ca.get("series"):
        return ""

    series = ca["series"]
    dxy_signal = ca.get("dxy_signal", "?")
    ry_signal = ca.get("real_yield_signal", "?")
    inf_signal = ca.get("inflation_signal", "?")
    risk_regime = ca.get("risk_regime", "?")

    lines = ["### Cross-Asset Macro"]

    # QUOTABLE line with the highest-signal numbers
    quotable_parts = []
    if "DXY_broad" in series:
        d = series["DXY_broad"]
        quotable_parts.append(f"DXY {d['value']:.1f} ({d['change_5d_pct']:+.1f}% 5d, {dxy_signal})")
    if "Real_10Y" in series:
        r = series["Real_10Y"]
        quotable_parts.append(f"10Y real {r['value']:.2f}% ({r['change_5d_bps']:+.0f}bps 5d)")
    if "Breakeven_10Y" in series:
        b = series["Breakeven_10Y"]
        quotable_parts.append(f"breakeven {b['value']:.2f}% ({inf_signal})")
    if quotable_parts:
        lines.append(f"QUOTABLE: {' | '.join(quotable_parts)} — risk regime: {risk_regime}.")
        lines.append("")

    lines.append(
        "NOTE: Four macro channels drive risk-asset pricing. DXY rising = headwind "
        "for crypto and non-US equities. 10Y real yield = opportunity cost of holding "
        "gold and growth stocks. Breakeven = inflation expectations. WTI = energy "
        "and transport input cost."
    )

    # Detail per series
    lines.append("")
    lines.append("CURRENT LEVELS (5-day change in parens):")
    if "DXY_broad" in series:
        d = series["DXY_broad"]
        lines.append(f"  DXY (broad USD): {d['value']:.2f}  ({d['change_5d_pct']:+.2f}% 5d)  → {dxy_signal}")
    if "Real_10Y" in series:
        r = series["Real_10Y"]
        lines.append(f"  10Y real yield: {r['value']:.2f}%  ({r['change_5d_bps']:+.0f} bps 5d)  → {ry_signal}")
    if "Breakeven_10Y" in series:
        b = series["Breakeven_10Y"]
        lines.append(f"  10Y breakeven inflation: {b['value']:.2f}%  ({b['change_5d_bps']:+.0f} bps 5d)  → {inf_signal}")
    if "Gold" in series:
        g = series["Gold"]
        lines.append(f"  Gold (GC futures): ${g['value']:,.0f}/oz  ({g['change_5d_pct']:+.2f}% 5d)")
    if "WTI" in series:
        w = series["WTI"]
        lines.append(f"  WTI crude: ${w['value']:.2f}/bbl  ({w['change_5d_pct']:+.2f}% 5d)")

    # Synthesis
    lines.append("")
    if risk_regime == "TAILWIND":
        lines.append(
            "  SYNTHESIS: Macro is supportive — weakening dollar AND falling/stable real "
            "yields AND anchored inflation. Risk assets (BTC, growth equities, EM) get "
            "tailwind. Use this as corroboration when adding risk."
        )
    elif risk_regime == "HEADWIND":
        lines.append(
            "  SYNTHESIS: Macro is restrictive — strengthening dollar AND rising real yields. "
            "Risk assets face direct headwind through valuation channel. Size accordingly: "
            "avoid stretched valuations, lean into beta-light names, hold dry powder."
        )
    else:
        lines.append(
            "  SYNTHESIS: Macro signals are mixed — no clean directional read. Don't "
            "over-weight macro framing; lean on bottom-up signals from your other modules."
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Formatter dispatch table
# ---------------------------------------------------------------------------

_MODULE_FORMATTERS = {
    "technicals": lambda ctx: _format_technicals(ctx["brief"]),
    "patterns": lambda ctx: _format_patterns(ctx.get("pattern_results", {})),
    "fundamentals": lambda ctx: _format_fundamentals(ctx["brief"]),
    "sentiment": lambda ctx: _format_sentiment(ctx["brief"], invert=ctx.get("invert", False)),
    "momentum": lambda ctx: _format_momentum(ctx["brief"]),
    "macro": lambda ctx: _format_macro(ctx["brief"]),
    "optimizer": lambda ctx: _format_optimizer(
        ctx.get("correlations", []),
        ctx.get("allocation", {}),
        ctx.get("sizing"),
    ),
    "signal_ranker": lambda ctx: _format_signal_ranker(ctx["brief"]),
    "trade_context": lambda ctx: _format_trade_context(ctx),
    "dynamic_risk": lambda ctx: _format_dynamic_risk(ctx),
    "options_flow": lambda ctx: _format_options_flow(ctx["brief"]),
    "yield_curve": lambda ctx: _format_yield_curve(ctx["brief"]),
    "expert_opinion": lambda ctx: _format_expert_opinion(ctx["brief"], invert=ctx.get("invert", False)),
    "btc_onchain": lambda ctx: _format_btc_onchain(ctx["brief"]),
    "fleet_conviction": lambda ctx: _format_fleet_conviction(
        ctx.get("fleet_signals"), invert=ctx.get("invert", False)
    ),
    "cross_asset": lambda ctx: _format_cross_asset(ctx["brief"]),
}


# ---------------------------------------------------------------------------
# Toolkit assembler
# ---------------------------------------------------------------------------

def assemble_toolkit_prompt(
    personality_key: str,
    personality_prompt: str,
    toolkit_config: list[dict],
    brief: dict,
    portfolio: dict,
    risk_params: dict,
    risk_analysis: str,
    trade_memory: str,
    agentic_data: dict,
) -> str:
    """Build the full user message using only the modules this personality selected.

    Parameters
    ----------
    personality_key : str
        Key into PERSONALITIES dict.
    personality_prompt : str
        The personality's strategy description.
    toolkit_config : list[dict]
        Each entry has "module" (str), "weight" (int 1-10), and optionally "invert" (bool).
    brief : dict
        The compiled market brief.
    portfolio : dict
        The trader's current portfolio state.
    risk_params : dict
        Personality-specific risk parameters.
    risk_analysis : str
        Pre-computed portfolio risk analysis string.
    trade_memory : str
        Formatted recent trade history.
    agentic_data : dict
        Raw data from agentic pipeline steps: pattern_results, correlations, allocation.
    """
    parts = []

    # Strategy section (always first)
    parts.append(f"## Your Strategy\n{personality_prompt}")

    # Toolkit manifest (tells the LLM what data it has and why)
    sorted_toolkit = sorted(toolkit_config, key=lambda t: t.get("weight", 0), reverse=True)
    active_modules = {t["module"] for t in sorted_toolkit}
    inactive = [
        name for name, meta in RAG_MODULES.items()
        if not meta["always_included"] and name not in active_modules
    ]

    manifest_lines = [
        f"## Your Data Toolkit ({len(sorted_toolkit)} of {len(RAG_MODULES) - 1} modules)",
        "These modules were selected to match your trading strategy, ordered by priority:",
    ]
    for i, entry in enumerate(sorted_toolkit, 1):
        mod = entry["module"]
        meta = RAG_MODULES.get(mod, {})
        label = meta.get("label", mod)
        desc = meta.get("description", "")
        invert_note = " [CONTRARIAN — interpret inversely]" if entry.get("invert") else ""
        manifest_lines.append(f"  {i}. [{entry.get('weight', 5)}] {label}{invert_note} — {desc}")
    if inactive:
        inactive_labels = [RAG_MODULES[m]["label"] for m in inactive if m in RAG_MODULES]
        manifest_lines.append(f"  Not included: {', '.join(inactive_labels)}")
    parts.append("\n".join(manifest_lines))

    # Core section (always included)
    core_text = _format_core(portfolio, personality_key, risk_params, risk_analysis, brief)
    parts.append(core_text)

    # Date header
    parts.append(f"## Today's Market Data ({brief.get('date', 'today')})")

    # Module sections, sorted by weight (highest first)
    ctx = {
        "brief": brief,
        "pattern_results": agentic_data.get("pattern_results", {}),
        "correlations": agentic_data.get("correlations", []),
        "allocation": agentic_data.get("allocation", {}),
        "sizing": agentic_data.get("sizing"),
        "trade_context": agentic_data.get("trade_context"),
        "dynamic_risk": agentic_data.get("dynamic_risk"),
        "fleet_signals": agentic_data.get("fleet_signals"),
    }

    for entry in sorted_toolkit:
        mod = entry["module"]
        formatter = _MODULE_FORMATTERS.get(mod)
        if not formatter:
            continue

        # Pass invert flag for sentiment module
        if entry.get("invert"):
            ctx["invert"] = True
        else:
            ctx["invert"] = False

        section = formatter(ctx)
        if section:
            parts.append(section)

    # Cross trader awareness (what other personalities hold)
    cross_trader = agentic_data.get("cross_trader_text", "")
    if cross_trader:
        parts.append(cross_trader)

    # Performance intelligence (self-assessment + peer learning)
    perf_intel = agentic_data.get("performance_intel", "")
    if perf_intel:
        parts.append(perf_intel)

    # Discipline report card (always-on nudge)
    discipline = agentic_data.get("discipline")
    if discipline:
        disc_text = _format_discipline(discipline)
        if disc_text:
            parts.append(disc_text)

    # Trading memory
    parts.append(f"## Your Trading Memory\n{trade_memory}")

    # Final instruction
    parts.append(
        "Based on ALL the data above — including any pattern recognition, "
        "correlation warnings, optimizer suggestions, and SUGGESTED POSITION SIZES — "
        "what trades do you want to make today?\n\n"
        "**Priority order:**\n"
        "1. Address any MANDATORY RISK ACTIONS first (stop-loss, take-profit, overweight)\n"
        "2. Follow your strategy's BUY/SELL criteria using the data modules provided\n"
        "3. For NEW BUYS: use the suggested position sizes from the optimizer if available — "
        "they account for signal strength, volatility, and your personality's risk budget\n"
        "4. In your reasoning, cite which news cluster or specific data drove each decision"
    )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# API helper for frontend
# ---------------------------------------------------------------------------

def get_personality_toolkit_info(personality_key: str, toolkit_config: list[dict]) -> list[dict]:
    """Return toolkit metadata suitable for the frontend.

    Returns a list of dicts, one per module (active ones with their weight,
    then inactive ones with weight=0).
    """
    active = {t["module"]: t for t in toolkit_config}
    result = []

    for name, meta in RAG_MODULES.items():
        if meta["always_included"]:
            continue
        entry = {
            "module": name,
            "label": meta["label"],
            "description": meta["description"],
            "icon": meta["icon"],
            "color": meta["color"],
            "active": name in active,
            "weight": active[name].get("weight", 0) if name in active else 0,
            "inverted": active[name].get("invert", False) if name in active else False,
        }
        result.append(entry)

    # Sort: active modules by weight desc, then inactive
    result.sort(key=lambda x: (-int(x["active"]), -x["weight"]))
    return result
