"""Pattern Recognition Engine (Step 3 of Agentic Pipeline).

Detects chart patterns, support/resistance levels, and crossover signals
from cached candle data. Zero API cost — all computed locally.

Patterns detected:
- Candlestick patterns: doji, hammer, engulfing, morning/evening star
- Trend signals: golden cross, death cross, EMA crossovers
- Support/resistance levels from recent price action
- Volume anomalies (z-score based)
"""

import math


# ---------------------------------------------------------------------------
# Candlestick pattern detection
# ---------------------------------------------------------------------------

def _detect_candlestick_patterns(candles: list[dict]) -> list[dict]:
    """Detect common candlestick patterns from OHLC data.
    Returns list of detected patterns with signal direction and strength."""
    if len(candles) < 3:
        return []

    patterns = []
    c = candles[-1]  # current candle
    p = candles[-2]  # previous candle
    pp = candles[-3]  # two candles ago

    body = c["close"] - c["open"]
    body_abs = abs(body)
    wick_upper = c["high"] - max(c["open"], c["close"])
    wick_lower = min(c["open"], c["close"]) - c["low"]
    candle_range = c["high"] - c["low"]

    if candle_range == 0:
        return patterns

    body_pct = body_abs / candle_range

    # Doji: very small body relative to range (indecision)
    if body_pct < 0.1 and candle_range > 0:
        patterns.append({
            "pattern": "Doji",
            "signal": "NEUTRAL",
            "meaning": "Market indecision. Often precedes a reversal.",
            "strength": 1,
        })

    # Hammer: small body at top, long lower wick (bullish reversal)
    if (body_pct < 0.35
            and wick_lower > body_abs * 2
            and wick_upper < body_abs * 0.5
            and body <= 0):  # after a down move
        # Check if preceded by downtrend
        if p["close"] < pp["close"]:
            patterns.append({
                "pattern": "Hammer",
                "signal": "BULLISH",
                "meaning": "Bullish reversal signal. Sellers pushed price down but buyers recovered.",
                "strength": 2,
            })

    # Inverted Hammer / Shooting Star
    if (body_pct < 0.35
            and wick_upper > body_abs * 2
            and wick_lower < body_abs * 0.5):
        if p["close"] > pp["close"] and body >= 0:
            patterns.append({
                "pattern": "Shooting Star",
                "signal": "BEARISH",
                "meaning": "Bearish reversal after uptrend. Buyers failed to hold highs.",
                "strength": 2,
            })
        elif p["close"] < pp["close"]:
            patterns.append({
                "pattern": "Inverted Hammer",
                "signal": "BULLISH",
                "meaning": "Potential bullish reversal. Watch for confirmation.",
                "strength": 1,
            })

    # Bullish Engulfing: current green candle fully engulfs previous red candle
    p_body = p["close"] - p["open"]
    if (body > 0 and p_body < 0
            and c["open"] <= p["close"]
            and c["close"] >= p["open"]
            and body_abs > abs(p_body)):
        patterns.append({
            "pattern": "Bullish Engulfing",
            "signal": "BULLISH",
            "meaning": "Strong bullish reversal. Buyers completely overpowered sellers.",
            "strength": 3,
        })

    # Bearish Engulfing: current red candle fully engulfs previous green candle
    if (body < 0 and p_body > 0
            and c["open"] >= p["close"]
            and c["close"] <= p["open"]
            and body_abs > abs(p_body)):
        patterns.append({
            "pattern": "Bearish Engulfing",
            "signal": "BEARISH",
            "meaning": "Strong bearish reversal. Sellers completely overpowered buyers.",
            "strength": 3,
        })

    # Morning Star (3-candle bullish reversal)
    pp_body = pp["close"] - pp["open"]
    p_body_abs = abs(p_body)
    pp_body_abs = abs(pp_body)
    p_range = p["high"] - p["low"]
    if (pp_body < 0 and pp_body_abs > 0  # first: red
            and p_range > 0 and p_body_abs / p_range < 0.3  # second: small body (star)
            and body > 0 and body_abs > pp_body_abs * 0.5):  # third: green, recovers >50%
        patterns.append({
            "pattern": "Morning Star",
            "signal": "BULLISH",
            "meaning": "Three candle bullish reversal. High reliability pattern.",
            "strength": 3,
        })

    # Evening Star (3-candle bearish reversal)
    if (pp_body > 0 and pp_body_abs > 0
            and p_range > 0 and p_body_abs / p_range < 0.3
            and body < 0 and body_abs > pp_body_abs * 0.5):
        patterns.append({
            "pattern": "Evening Star",
            "signal": "BEARISH",
            "meaning": "Three candle bearish reversal. High reliability pattern.",
            "strength": 3,
        })

    return patterns


# ---------------------------------------------------------------------------
# Support / Resistance detection
# ---------------------------------------------------------------------------

def _detect_support_resistance(candles: list[dict], num_levels: int = 3) -> dict:
    """Identify support and resistance levels from recent price pivots.
    Uses local min/max detection over a rolling window."""
    if len(candles) < 10:
        return {"support": [], "resistance": []}

    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    current = candles[-1]["close"]

    # Find pivot highs (local maxima) and pivot lows (local minima)
    pivot_highs = []
    pivot_lows = []
    window = 3

    for i in range(window, len(candles) - window):
        # Pivot high: higher than neighbors
        if all(highs[i] >= highs[i - j] for j in range(1, window + 1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, window + 1)):
            pivot_highs.append(highs[i])

        # Pivot low: lower than neighbors
        if all(lows[i] <= lows[i - j] for j in range(1, window + 1)) and \
           all(lows[i] <= lows[i + j] for j in range(1, window + 1)):
            pivot_lows.append(lows[i])

    # Cluster nearby levels (within 1.5% of each other)
    def _cluster_levels(levels: list[float]) -> list[float]:
        if not levels:
            return []
        sorted_levels = sorted(levels)
        clusters = [[sorted_levels[0]]]
        for lvl in sorted_levels[1:]:
            if abs(lvl - clusters[-1][-1]) / clusters[-1][-1] < 0.015:
                clusters[-1].append(lvl)
            else:
                clusters.append([lvl])
        # Return the average of each cluster, sorted by number of touches
        result = [(sum(c) / len(c), len(c)) for c in clusters]
        result.sort(key=lambda x: x[1], reverse=True)
        return [round(r[0], 2) for r in result[:num_levels]]

    resistance = [r for r in _cluster_levels(pivot_highs) if r > current]
    support = [s for s in _cluster_levels(pivot_lows) if s < current]

    return {
        "support": support[:num_levels],
        "resistance": resistance[:num_levels],
        "current_price": round(current, 2),
    }


# ---------------------------------------------------------------------------
# Trend crossover signals
# ---------------------------------------------------------------------------

def _detect_crossovers(candles: list[dict]) -> list[dict]:
    """Detect golden cross, death cross, and EMA crossovers.
    These are computed from close prices over the candle history."""
    if len(candles) < 52:
        return []

    closes = [c["close"] for c in candles]
    signals = []

    # Compute SMAs for recent days
    def _sma(data, period, offset=0):
        start = len(data) - period - offset
        end = len(data) - offset
        if start < 0:
            return None
        return sum(data[start:end]) / period

    sma20_now = _sma(closes, 20)
    sma50_now = _sma(closes, 50)
    sma20_prev = _sma(closes, 20, 1)
    sma50_prev = _sma(closes, 50, 1)

    # Golden Cross: SMA20 crosses above SMA50
    if sma20_now and sma50_now and sma20_prev and sma50_prev:
        if sma20_prev <= sma50_prev and sma20_now > sma50_now:
            signals.append({
                "signal": "Golden Cross",
                "direction": "BULLISH",
                "meaning": "SMA20 crossed above SMA50. Classic bullish trend confirmation.",
                "strength": 3,
            })
        # Death Cross: SMA20 crosses below SMA50
        elif sma20_prev >= sma50_prev and sma20_now < sma50_now:
            signals.append({
                "signal": "Death Cross",
                "direction": "BEARISH",
                "meaning": "SMA20 crossed below SMA50. Classic bearish trend confirmation.",
                "strength": 3,
            })

    # EMA 12/26 crossover (faster signal than SMA)
    def _ema(data, period):
        mult = 2 / (period + 1)
        ema = sum(data[:period]) / period
        for price in data[period:]:
            ema = (price - ema) * mult + ema
        return ema

    if len(closes) >= 27:
        ema12_now = _ema(closes, 12)
        ema26_now = _ema(closes, 26)
        ema12_prev = _ema(closes[:-1], 12)
        ema26_prev = _ema(closes[:-1], 26)

        if ema12_prev <= ema26_prev and ema12_now > ema26_now:
            signals.append({
                "signal": "EMA Bullish Crossover",
                "direction": "BULLISH",
                "meaning": "EMA12 crossed above EMA26. Short term momentum turning positive.",
                "strength": 2,
            })
        elif ema12_prev >= ema26_prev and ema12_now < ema26_now:
            signals.append({
                "signal": "EMA Bearish Crossover",
                "direction": "BEARISH",
                "meaning": "EMA12 crossed below EMA26. Short term momentum turning negative.",
                "strength": 2,
            })

    return signals


# ---------------------------------------------------------------------------
# Volume anomaly detection
# ---------------------------------------------------------------------------

def _detect_volume_anomalies(candles: list[dict]) -> dict | None:
    """Detect unusual volume activity using z-score analysis.
    High volume on a move = conviction. High volume on no move = distribution."""
    volumes = [c.get("volume", 0) for c in candles if c.get("volume")]
    if len(volumes) < 21:
        return None

    recent_vol = volumes[-1]
    mean_vol = sum(volumes[-21:-1]) / 20
    if mean_vol == 0:
        return None

    # Standard deviation
    variance = sum((v - mean_vol) ** 2 for v in volumes[-21:-1]) / 20
    std_vol = math.sqrt(variance) if variance > 0 else 1

    z_score = round((recent_vol - mean_vol) / std_vol, 2)

    # Price change for context
    price_change = candles[-1]["close"] - candles[-2]["close"] if len(candles) >= 2 else 0
    price_change_pct = round(price_change / candles[-2]["close"] * 100, 2) if candles[-2]["close"] else 0

    result = {
        "z_score": z_score,
        "relative_volume": round(recent_vol / mean_vol, 2),
    }

    if z_score > 2.0:
        if abs(price_change_pct) > 1.0:
            result["anomaly"] = "HIGH_VOLUME_BREAKOUT"
            result["meaning"] = f"Volume spike ({z_score:.1f} sigma) with {price_change_pct:+.1f}% price move. Strong conviction."
        else:
            result["anomaly"] = "HIGH_VOLUME_CHURN"
            result["meaning"] = f"Volume spike ({z_score:.1f} sigma) but price flat. Possible distribution or accumulation."
    elif z_score < -1.5:
        result["anomaly"] = "LOW_VOLUME"
        result["meaning"] = "Unusually low volume. Low conviction in current price."

    return result


# ---------------------------------------------------------------------------
# Main pattern analysis function
# ---------------------------------------------------------------------------

def analyze_patterns(candles: list[dict], symbol: str = "") -> dict:
    """Run full pattern recognition analysis on candle data.
    Returns a dict with all detected patterns, levels, and signals."""
    if not candles or len(candles) < 5:
        return {"symbol": symbol, "patterns": [], "signals": [], "levels": {}, "volume": None}

    # Only run candlestick patterns on stocks (need OHLC)
    has_ohlc = "open" in candles[-1] and "high" in candles[-1] and "low" in candles[-1]

    patterns = _detect_candlestick_patterns(candles) if has_ohlc else []
    levels = _detect_support_resistance(candles) if has_ohlc else {"support": [], "resistance": []}
    crossovers = _detect_crossovers(candles)
    volume = _detect_volume_anomalies(candles) if has_ohlc else None

    # Compute aggregate signal
    bullish = sum(p["strength"] for p in patterns if p["signal"] == "BULLISH")
    bullish += sum(s["strength"] for s in crossovers if s["direction"] == "BULLISH")
    bearish = sum(p["strength"] for p in patterns if p["signal"] == "BEARISH")
    bearish += sum(s["strength"] for s in crossovers if s["direction"] == "BEARISH")

    if bullish > bearish + 2:
        aggregate = "BULLISH"
    elif bearish > bullish + 2:
        aggregate = "BEARISH"
    else:
        aggregate = "NEUTRAL"

    return {
        "symbol": symbol,
        "candlestick_patterns": patterns,
        "crossover_signals": crossovers,
        "support_resistance": levels,
        "volume_analysis": volume,
        "aggregate_signal": aggregate,
        "bullish_score": bullish,
        "bearish_score": bearish,
    }
