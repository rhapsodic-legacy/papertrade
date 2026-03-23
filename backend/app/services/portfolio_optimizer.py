"""Portfolio Optimizer (Step 4 of Agentic Pipeline).

Provides code-based portfolio optimization that runs before the LLM decision.
Zero API cost — all computed from cached data and current positions.

Features:
- Correlation matrix between held assets (avoid overconcentration in correlated names)
- Signal-weighted target allocation (uses composite signal scores)
- Risk budget enforcement per personality
- Specific trade suggestions the LLM can accept, modify, or reject
"""

import math
from app.services.market_data import STOCK_SECTORS


# ---------------------------------------------------------------------------
# Correlation analysis
# ---------------------------------------------------------------------------

def _compute_correlation(returns_a: list[float], returns_b: list[float]) -> float | None:
    """Pearson correlation between two return series."""
    n = min(len(returns_a), len(returns_b))
    if n < 10:
        return None

    a = returns_a[-n:]
    b = returns_b[-n:]

    mean_a = sum(a) / n
    mean_b = sum(b) / n

    cov = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n)) / n
    std_a = math.sqrt(sum((x - mean_a) ** 2 for x in a) / n)
    std_b = math.sqrt(sum((x - mean_b) ** 2 for x in b) / n)

    if std_a == 0 or std_b == 0:
        return None

    return round(cov / (std_a * std_b), 2)


def compute_portfolio_correlations(
    positions: list[dict],
    candle_data: dict[str, list[dict]],
) -> list[dict]:
    """Compute pairwise correlations for currently held assets.
    Returns warnings for highly correlated pairs (>0.8)."""

    # Build daily return series per symbol
    return_series: dict[str, list[float]] = {}
    for pos in positions:
        sym = pos["symbol"]
        candles = candle_data.get(sym, [])
        if len(candles) < 15:
            continue
        closes = [c["close"] for c in candles]
        returns = [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes))]
        return_series[sym] = returns

    symbols = list(return_series.keys())
    warnings = []

    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            corr = _compute_correlation(return_series[symbols[i]], return_series[symbols[j]])
            if corr is not None and abs(corr) > 0.75:
                direction = "positively" if corr > 0 else "negatively"
                risk = "HIGH" if abs(corr) > 0.85 else "MODERATE"
                warnings.append({
                    "pair": f"{symbols[i]}/{symbols[j]}",
                    "correlation": corr,
                    "risk": risk,
                    "warning": (
                        f"{symbols[i]} and {symbols[j]} are {direction} correlated ({corr:.2f}). "
                        f"Holding both provides limited diversification."
                    ),
                })

    return warnings


# ---------------------------------------------------------------------------
# Signal-weighted allocation
# ---------------------------------------------------------------------------

def compute_target_allocation(
    signal_scores: dict[str, dict],
    personality_key: str,
    risk_params: dict,
    current_positions: list[dict],
    cash: float,
    total_value: float,
) -> dict:
    """Compute suggested target allocation based on signal scores and personality.
    Returns suggested buys, sells, and rebalancing moves."""

    if total_value <= 0:
        return {"suggestions": [], "cash_target_pct": 0}

    max_position_pct = risk_params.get("max_position_pct", 15.0)

    # Personality-based allocation preferences
    allocation_profiles = {
        "vanilla": {
            "max_equity_pct": 85,
            "min_cash_pct": 10,
            "prefer_sectors": None,  # balanced
            "crypto_max_pct": 15,
        },
        "steady_eddie": {
            "max_equity_pct": 70,
            "min_cash_pct": 15,
            "prefer_sectors": ["Healthcare", "Consumer", "Finance"],
            "crypto_max_pct": 5,
        },
        "yolo_bot": {
            "max_equity_pct": 95,
            "min_cash_pct": 3,
            "prefer_sectors": None,  # follows momentum
            "crypto_max_pct": 40,
        },
        "contrarian_carl": {
            "max_equity_pct": 80,
            "min_cash_pct": 15,
            "prefer_sectors": None,  # follows oversold
            "crypto_max_pct": 15,
        },
        "crypto_chad": {
            "max_equity_pct": 90,
            "min_cash_pct": 5,
            "prefer_sectors": ["Technology"],
            "crypto_max_pct": 80,
        },
    }

    profile = allocation_profiles.get(personality_key, allocation_profiles["vanilla"])
    suggestions = []

    # Build current position map
    pos_map = {}
    for p in current_positions:
        pct = (p.get("market_value", 0) / total_value * 100) if total_value > 0 else 0
        pos_map[p["symbol"]] = {
            "current_pct": round(pct, 1),
            "market_value": p.get("market_value", 0),
            "quantity": p.get("quantity", 0),
            "asset_type": p.get("asset_type", "stock"),
            "unrealized_pnl_pct": p.get("unrealized_pnl_pct", 0),
        }

    # Check overweight positions
    for sym, pos in pos_map.items():
        if pos["current_pct"] > max_position_pct:
            suggestions.append({
                "action": "TRIM",
                "symbol": sym,
                "reason": f"Position is {pos['current_pct']:.1f}% of portfolio (max {max_position_pct}%). Trim to reduce concentration risk.",
                "priority": "HIGH",
            })

    # Check crypto allocation vs personality limit
    crypto_pct = sum(
        p["current_pct"] for p in pos_map.values()
        if p["asset_type"] == "crypto"
    )
    if crypto_pct > profile["crypto_max_pct"]:
        suggestions.append({
            "action": "REDUCE_CRYPTO",
            "reason": f"Crypto allocation is {crypto_pct:.1f}% (personality max {profile['crypto_max_pct']}%). Consider trimming crypto positions.",
            "priority": "MEDIUM",
        })

    # Check sector concentration
    sector_exposure: dict[str, float] = {}
    for sym, pos in pos_map.items():
        if pos["asset_type"] == "stock":
            sector = STOCK_SECTORS.get(sym, "Other")
            sector_exposure[sector] = sector_exposure.get(sector, 0) + pos["current_pct"]

    for sector, pct in sector_exposure.items():
        if pct > 40:
            suggestions.append({
                "action": "DIVERSIFY",
                "reason": f"{sector} sector is {pct:.1f}% of portfolio. Consider diversifying into other sectors.",
                "priority": "MEDIUM",
            })

    # Signal-based opportunities (assets not currently held with strong signals)
    buy_candidates = []
    for sym, sig in signal_scores.items():
        score = sig.get("score", 0)
        label = sig.get("label", "NEUTRAL")
        if sym not in pos_map and score >= 25:
            buy_candidates.append({
                "symbol": sym,
                "score": score,
                "label": label,
            })

    # Sort by signal strength
    buy_candidates.sort(key=lambda x: x["score"], reverse=True)

    # Suggest top opportunities based on personality
    cash_pct = (cash / total_value * 100) if total_value > 0 else 0
    if cash_pct > profile["min_cash_pct"] and buy_candidates:
        available_pct = cash_pct - profile["min_cash_pct"]
        for candidate in buy_candidates[:3]:
            if available_pct <= 0:
                break
            alloc = min(available_pct, max_position_pct)
            suggestions.append({
                "action": "BUY",
                "symbol": candidate["symbol"],
                "signal": candidate["label"],
                "signal_score": candidate["score"],
                "suggested_allocation_pct": round(alloc, 1),
                "reason": f"Signal score {candidate['score']:+d} ({candidate['label']}). Suggested allocation: {alloc:.1f}% of portfolio.",
                "priority": "LOW",  # suggestions, not mandates
            })
            available_pct -= alloc

    # Check for held positions with SELL signals
    for sym, pos in pos_map.items():
        sig = signal_scores.get(sym, {})
        score = sig.get("score", 0)
        if score <= -40:
            suggestions.append({
                "action": "SELL",
                "symbol": sym,
                "signal": sig.get("label", "SELL"),
                "signal_score": score,
                "reason": f"Held position {sym} has signal score {score:+d} ({sig.get('label', 'SELL')}). Consider reducing or exiting.",
                "priority": "MEDIUM",
            })

    return {
        "suggestions": suggestions,
        "cash_pct": round(cash_pct, 1),
        "cash_target_pct": profile["min_cash_pct"],
        "crypto_pct": round(crypto_pct, 1),
        "crypto_max_pct": profile["crypto_max_pct"],
        "sector_exposure": {k: round(v, 1) for k, v in sector_exposure.items()},
        "num_positions": len(pos_map),
    }


def compute_position_sizes(
    signal_scores: dict[str, dict],
    volatility: dict[str, float],
    personality_key: str,
    risk_params: dict,
    total_value: float,
    cash: float,
) -> dict[str, dict]:
    """Compute suggested position sizes based on signal strength and volatility.

    Returns {symbol: {suggested_pct, dollar_amount, shares_approx, reasoning}}.
    Only includes symbols with BUY signals and available cash.
    """
    if total_value <= 0 or cash <= 0:
        return {}

    max_pos_pct = risk_params.get("max_position_pct", 15.0)
    # Base allocation per position varies by personality aggressiveness
    base_alloc = {
        "vanilla": 6.0,
        "steady_eddie": 5.0,
        "yolo_bot": 10.0,
        "contrarian_carl": 7.0,
        "crypto_chad": 8.0,
    }.get(personality_key, 6.0)

    # Rank volatilities to scale position sizes (lower vol = bigger position)
    vol_values = [v for v in volatility.values() if v and v > 0]
    median_vol = sorted(vol_values)[len(vol_values) // 2] if vol_values else 25.0

    result = {}
    for sym, sig in signal_scores.items():
        score = sig.get("score", 0)
        if score < 20:
            continue

        # Scale by signal strength (20-100 range mapped to 0.2-1.0)
        signal_factor = min(score, 100) / 100

        # Scale by inverse volatility (high vol = smaller size)
        sym_vol = volatility.get(sym, median_vol) or median_vol
        vol_factor = median_vol / max(sym_vol, 5)
        vol_factor = max(0.3, min(1.5, vol_factor))

        suggested_pct = base_alloc * signal_factor * vol_factor
        suggested_pct = min(suggested_pct, max_pos_pct)
        suggested_pct = round(suggested_pct, 1)

        dollar_amount = total_value * (suggested_pct / 100)
        if dollar_amount > cash:
            dollar_amount = cash
            suggested_pct = round(dollar_amount / total_value * 100, 1)

        if dollar_amount < 100:
            continue

        vol_label = "low" if sym_vol < 20 else "high" if sym_vol > 40 else "moderate"
        result[sym] = {
            "suggested_pct": suggested_pct,
            "dollar_amount": round(dollar_amount),
            "reasoning": f"signal {score:+d}, {vol_label} volatility ({sym_vol:.0f}%)",
        }

    return result


# ---------------------------------------------------------------------------
# Format for AI prompt
# ---------------------------------------------------------------------------

def format_optimizer_output(
    correlations: list[dict],
    allocation: dict,
    patterns: dict[str, dict],
) -> str:
    """Format all optimizer output into a section for the AI prompt."""
    sections = []

    # Pattern recognition results
    pattern_lines = []
    for sym, analysis in patterns.items():
        parts = []
        # Candlestick patterns
        for p in analysis.get("candlestick_patterns", []):
            parts.append(f"{p['pattern']} ({p['signal']})")
        # Crossover signals
        for s in analysis.get("crossover_signals", []):
            parts.append(f"{s['signal']} ({s['direction']})")
        # Support/resistance
        levels = analysis.get("support_resistance", {})
        if levels.get("support"):
            parts.append(f"Support: ${', $'.join(str(s) for s in levels['support'][:2])}")
        if levels.get("resistance"):
            parts.append(f"Resistance: ${', $'.join(str(r) for r in levels['resistance'][:2])}")
        # Volume anomaly
        vol = analysis.get("volume_analysis")
        if vol and vol.get("anomaly"):
            parts.append(f"{vol['anomaly']}: {vol['meaning']}")
        # Aggregate
        agg = analysis.get("aggregate_signal")
        if agg and agg != "NEUTRAL":
            parts.insert(0, f"Pattern Signal: {agg}")

        if parts:
            pattern_lines.append(f"  {sym}: {', '.join(parts)}")

    if pattern_lines:
        sections.append(
            "### PATTERN RECOGNITION (chart patterns, crossovers, support/resistance)\n"
            + "\n".join(pattern_lines)
        )

    # Correlation warnings
    if correlations:
        corr_lines = [f"  {c['warning']}" for c in correlations]
        sections.append(
            "### CORRELATION WARNINGS (diversification risk)\n"
            + "\n".join(corr_lines)
        )

    # Allocation suggestions
    sugs = allocation.get("suggestions", [])
    if sugs:
        # Sort by priority
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

    return "\n\n".join(sections) if sections else ""
