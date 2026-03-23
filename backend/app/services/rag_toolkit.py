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

    # Analyst recommendations
    recs = brief.get("analyst_recommendations", {})
    if recs:
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

    # Insider transactions
    insider = brief.get("insider_transactions", {})
    if insider:
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

    # Earnings calendar
    earnings = brief.get("earnings_calendar", [])
    if earnings:
        earn_lines = []
        for e in earnings[:10]:
            eps_str = f" (est EPS ${e['estimate_eps']:.2f})" if e.get("estimate_eps") else ""
            earn_lines.append(f"  {e['symbol']} reports {e['date']}{eps_str} — expect volatility")
        sections.append("### Upcoming Earnings (next 7 days)\n" + "\n".join(earn_lines))

    return "\n\n".join(sections)


def _format_sentiment(brief: dict, invert: bool = False) -> str:
    """News headlines, company news, sentiment scores, and day-over-day context."""
    sections = []
    header_suffix = " (CONTRARIAN LENS)" if invert else ""

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

    # General market news (with inline scores when available)
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

    # Company-specific news (with inline scores when available)
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

    # Social/retail sentiment (StockTwits)
    social = brief.get("social_sentiment", {})
    if social:
        social_lines = []
        news_sent = sent.get("by_symbol", {}) if sent else {}
        for sym, s in social.items():
            bull = s.get("bullish_pct")
            if bull is None:
                continue
            bear = s.get("bearish_pct", 0)
            vol = s.get("volume_signal", "NORMAL")
            line = f"  {sym}: {bull:.0f}% bullish / {bear:.0f}% bearish (volume: {vol})"
            # Compare with news sentiment if available
            news_score = news_sent.get(sym, {}).get("score")
            if news_score is not None:
                news_dir = "bullish" if news_score > 0.1 else "bearish" if news_score < -0.1 else "neutral"
                social_dir = "bullish" if bull > 60 else "bearish" if bear > 60 else "mixed"
                if news_dir != social_dir and news_dir != "neutral" and social_dir != "mixed":
                    line += f" << DIVERGENCE: news {news_dir} vs social {social_dir}"
            social_lines.append(line)
        if social_lines:
            header = "### Social/Retail Sentiment (StockTwits)"
            if invert:
                header += "\nCONTRARIAN NOTE: High social bullishness = everyone already bought. Look for extremes."
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

    gainers = brief.get("top_gainers", [])
    if gainers:
        sections.append("### Top Gainers (momentum leaders)\n" + json.dumps(gainers, indent=2))

    losers = brief.get("top_losers", [])
    if losers:
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
            vol_mcap = c.get("volume_to_mcap")
            if vol_mcap is not None:
                activity = "HIGH" if vol_mcap > 15 else "LOW" if vol_mcap < 3 else "NORMAL"
                momentum_parts.append(f"Vol/MCap {vol_mcap}% ({activity})")
            if momentum_parts:
                crypto_lines.append(f"    Momentum: {', '.join(momentum_parts)}")

        if crypto_lines:
            sections.append("### Crypto Market Data\n" + "\n".join(crypto_lines))

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

    # Trading memory
    parts.append(f"## Your Trading Memory\n{trade_memory}")

    # Final instruction
    parts.append(
        "Based on ALL the data above — including any pattern recognition, "
        "correlation warnings, and optimizer suggestions — what trades do you want "
        "to make today? Address any MANDATORY RISK ACTIONS first, then follow your "
        "strategy's BUY/SELL criteria using the data modules provided."
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
