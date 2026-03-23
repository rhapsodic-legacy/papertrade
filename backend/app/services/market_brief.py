import asyncio
import math
import httpx
from datetime import date, datetime, timedelta, timezone

from app.config import get_settings
from app.services.market_data import (
    TOP_STOCKS,
    CRYPTO_MAP,
    STOCK_SECTORS,
    get_quote,
    get_all_crypto_quotes,
    get_stock_candles,
    get_crypto_history,
    FINNHUB_BASE,
    COINGECKO_BASE,
)
from app.services.supabase_client import get_supabase_admin


# ---------------------------------------------------------------------------
# Technical indicator helpers (computed from candle data, zero API cost)
# ---------------------------------------------------------------------------

def _compute_sma(closes: list[float], period: int) -> float | None:
    """Simple Moving Average over the last N closes."""
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 2)


def _compute_rsi(closes: list[float], period: int = 14) -> float | None:
    """Relative Strength Index. >70 = overbought, <30 = oversold."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(-period, 0):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def _compute_momentum(closes: list[float]) -> dict:
    """Compute short/medium term momentum from close prices."""
    result = {}
    if len(closes) >= 7:
        result["7d_return"] = round((closes[-1] / closes[-7] - 1) * 100, 2)
    if len(closes) >= 30:
        result["30d_return"] = round((closes[-1] / closes[-30] - 1) * 100, 2)
    return result


def _compute_ema(closes: list[float], period: int) -> float | None:
    """Exponential Moving Average — reacts faster to recent price changes than SMA."""
    if len(closes) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(closes[:period]) / period  # seed with SMA
    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema
    return round(ema, 2)


def _compute_macd(closes: list[float]) -> dict | None:
    """MACD (12, 26, 9) — trend following momentum indicator.
    Positive histogram = bullish momentum, negative = bearish.
    Signal line crossovers indicate trade entries/exits."""
    ema_12 = _compute_ema(closes, 12)
    ema_26 = _compute_ema(closes, 26)
    if ema_12 is None or ema_26 is None:
        return None
    macd_line = round(ema_12 - ema_26, 2)
    # Approximate signal line from recent MACD values
    if len(closes) < 35:
        return {"macd_line": macd_line, "signal_line": None, "histogram": None}
    macd_series = []
    for i in range(26, len(closes)):
        e12 = _compute_ema(closes[:i + 1], 12)
        e26 = _compute_ema(closes[:i + 1], 26)
        if e12 and e26:
            macd_series.append(e12 - e26)
    signal_line = _compute_ema(macd_series, 9) if len(macd_series) >= 9 else None
    histogram = round(macd_line - signal_line, 2) if signal_line else None
    return {
        "macd_line": macd_line,
        "signal_line": round(signal_line, 2) if signal_line else None,
        "histogram": histogram,
    }


def _compute_bollinger_bands(closes: list[float], period: int = 20, std_dev: float = 2.0) -> dict | None:
    """Bollinger Bands — price channel based on volatility.
    Price near upper band = overbought, near lower = oversold.
    Squeeze (narrow bands) often precedes a breakout."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    sma = sum(window) / period
    variance = sum((p - sma) ** 2 for p in window) / period
    std = math.sqrt(variance)
    upper = round(sma + std_dev * std, 2)
    lower = round(sma - std_dev * std, 2)
    current = closes[-1]
    bandwidth = round((upper - lower) / sma * 100, 2)  # % width
    # Position within bands: 0 = at lower, 1 = at upper
    pct_b = round((current - lower) / (upper - lower), 2) if upper != lower else 0.5
    return {
        "upper": upper,
        "lower": lower,
        "bandwidth": bandwidth,
        "pct_b": pct_b,
    }


def _compute_atr(candles: list[dict], period: int = 14) -> float | None:
    """Average True Range — measures volatility in price units.
    Used for stop loss placement and position sizing."""
    if len(candles) < period + 1:
        return None
    true_ranges = []
    for i in range(-period, 0):
        high = candles[i].get("high", candles[i]["close"])
        low = candles[i].get("low", candles[i]["close"])
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    return round(sum(true_ranges) / period, 2)


def _compute_signal_score(technicals: dict, current_price: float) -> dict:
    """Composite signal score combining multiple indicators.
    Returns a score from -100 (strong sell) to +100 (strong buy)
    and a human readable signal label. Zero extra API cost."""
    signals = []
    weights = []

    # RSI signal (-1 to +1)
    rsi = technicals.get("rsi_14")
    if rsi is not None:
        if rsi < 30:
            signals.append(1.0)   # oversold = bullish
        elif rsi > 70:
            signals.append(-1.0)  # overbought = bearish
        elif rsi < 45:
            signals.append(0.3)
        elif rsi > 55:
            signals.append(-0.3)
        else:
            signals.append(0.0)
        weights.append(0.20)

    # SMA trend signal
    vs_20 = technicals.get("vs_sma_20")
    vs_50 = technicals.get("vs_sma_50")
    if vs_20 is not None and vs_50 is not None:
        if vs_20 > 0 and vs_50 > 0:
            signals.append(0.8)   # above both SMAs = uptrend
        elif vs_20 < 0 and vs_50 < 0:
            signals.append(-0.8)  # below both = downtrend
        elif vs_20 > 0 > vs_50:
            signals.append(0.3)   # recovering
        else:
            signals.append(-0.3)  # weakening
        weights.append(0.20)

    # MACD signal
    macd = technicals.get("macd")
    if macd and macd.get("histogram") is not None:
        hist = macd["histogram"]
        if hist > 0.5:
            signals.append(0.8)
        elif hist > 0:
            signals.append(0.3)
        elif hist < -0.5:
            signals.append(-0.8)
        else:
            signals.append(-0.3)
        weights.append(0.20)

    # Momentum signal
    ret_7d = technicals.get("7d_return")
    if ret_7d is not None:
        clamped = max(-5, min(5, ret_7d)) / 5  # normalize to -1..1
        signals.append(clamped)
        weights.append(0.15)

    # Bollinger Bands signal
    bb = technicals.get("bollinger_bands")
    if bb and bb.get("pct_b") is not None:
        pct_b = bb["pct_b"]
        if pct_b < 0.2:
            signals.append(0.7)   # near lower band = buy signal
        elif pct_b > 0.8:
            signals.append(-0.7)  # near upper band = sell signal
        else:
            signals.append(0.0)
        weights.append(0.15)

    # Volume confirmation
    rel_vol = technicals.get("relative_volume")
    if rel_vol is not None and signals:
        # High volume confirms the prevailing signal direction
        vol_boost = 0.1 if rel_vol > 1.5 else (-0.1 if rel_vol < 0.5 else 0.0)
        avg_signal = sum(signals) / len(signals)
        if avg_signal > 0:
            signals.append(vol_boost)
        else:
            signals.append(-vol_boost)
        weights.append(0.10)

    if not signals:
        return {"score": 0, "label": "NO DATA"}

    # Weighted average, scaled to -100..+100
    total_weight = sum(weights)
    weighted_sum = sum(s * w for s, w in zip(signals, weights))
    score = round(weighted_sum / total_weight * 100)

    if score >= 60:
        label = "STRONG BUY"
    elif score >= 25:
        label = "BUY"
    elif score >= -25:
        label = "NEUTRAL"
    elif score >= -60:
        label = "SELL"
    else:
        label = "STRONG SELL"

    return {"score": score, "label": label}


def _derive_technicals(closes: list[float], current_price: float, candles: list[dict] | None = None) -> dict:
    """Derive technical indicators from historical close prices."""
    sma_20 = _compute_sma(closes, 20)
    sma_50 = _compute_sma(closes, 50)
    rsi = _compute_rsi(closes)
    momentum = _compute_momentum(closes)

    technicals = {}
    if sma_20:
        technicals["sma_20"] = sma_20
        technicals["vs_sma_20"] = round((current_price / sma_20 - 1) * 100, 2)
    if sma_50:
        technicals["sma_50"] = sma_50
        technicals["vs_sma_50"] = round((current_price / sma_50 - 1) * 100, 2)
    if rsi is not None:
        technicals["rsi_14"] = rsi
    technicals.update(momentum)

    # New indicators
    ema_12 = _compute_ema(closes, 12)
    ema_26 = _compute_ema(closes, 26)
    if ema_12:
        technicals["ema_12"] = ema_12
    if ema_26:
        technicals["ema_26"] = ema_26

    macd = _compute_macd(closes)
    if macd:
        technicals["macd"] = macd

    bb = _compute_bollinger_bands(closes)
    if bb:
        technicals["bollinger_bands"] = bb

    if candles:
        atr = _compute_atr(candles)
        if atr:
            technicals["atr_14"] = atr

    # Composite signal score (combines all indicators above)
    signal = _compute_signal_score(technicals, current_price)
    technicals["signal"] = signal

    return technicals


# ---------------------------------------------------------------------------
# Volatility and volume analysis (computed from candle data, zero API cost)
# ---------------------------------------------------------------------------


def _compute_historical_volatility(closes: list[float], period: int = 20) -> float | None:
    """Annualized historical volatility from daily close prices.
    Used by professionals to gauge risk — higher = more volatile."""
    if len(closes) < period + 1:
        return None
    returns = [(closes[i] / closes[i - 1]) - 1 for i in range(-period, 0)]
    if not returns:
        return None
    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    daily_vol = math.sqrt(variance)
    annualized = round(daily_vol * math.sqrt(252) * 100, 1)  # % annualized
    return annualized


def _compute_volume_analysis(candles: list[dict]) -> dict | None:
    """Compare recent volume to 20-day average. High relative volume = conviction."""
    if len(candles) < 21:
        return None
    volumes = [c.get("volume") or c.get("v", 0) for c in candles if c.get("volume") or c.get("v")]
    if len(volumes) < 21:
        return None
    avg_20 = sum(volumes[-21:-1]) / 20
    if avg_20 == 0:
        return None
    latest = volumes[-1]
    return {
        "latest_volume": latest,
        "avg_20d_volume": round(avg_20),
        "relative_volume": round(latest / avg_20, 2),
    }


# ---------------------------------------------------------------------------
# Market regime detection (from ETF proxies — zero extra API cost)
# ---------------------------------------------------------------------------

async def _detect_market_regime(stock_technicals: dict) -> dict:
    """Derive macro signals from ETF proxies already in our universe.
    SPY = broad market, QQQ = tech/growth, TLT = bonds/rates, GLD = safe haven."""
    regime = {}

    # SPY — overall market direction
    spy = stock_technicals.get("SPY", {})
    if spy:
        rsi = spy.get("rsi_14")
        mom_7d = spy.get("7d_return", 0)
        mom_30d = spy.get("30d_return", 0)
        if rsi and rsi > 65 and mom_7d > 1:
            regime["market_trend"] = "BULLISH"
        elif rsi and rsi < 35 and mom_7d < -1:
            regime["market_trend"] = "BEARISH"
        else:
            regime["market_trend"] = "NEUTRAL"
        regime["spy_rsi"] = rsi
        regime["spy_7d"] = mom_7d
        regime["spy_30d"] = mom_30d

    # QQQ vs SPY — growth vs value rotation
    qqq = stock_technicals.get("QQQ", {})
    if qqq and spy:
        qqq_7d = qqq.get("7d_return", 0)
        spy_7d = spy.get("7d_return", 0)
        spread = round(qqq_7d - spy_7d, 2)
        regime["growth_vs_value"] = "GROWTH_LEADING" if spread > 0.5 else "VALUE_LEADING" if spread < -0.5 else "BALANCED"
        regime["qqq_spy_spread_7d"] = spread

    # TLT — bond/rate signal (rising TLT = falling rates = risk-on for stocks)
    tlt = stock_technicals.get("TLT", {})
    if tlt:
        tlt_7d = tlt.get("7d_return", 0)
        regime["rate_signal"] = "RATES_FALLING" if tlt_7d > 0.5 else "RATES_RISING" if tlt_7d < -0.5 else "RATES_STABLE"
        regime["tlt_7d"] = tlt_7d

    # GLD — safe haven demand
    gld = stock_technicals.get("GLD", {})
    if gld:
        gld_7d = gld.get("7d_return", 0)
        regime["safe_haven_demand"] = "HIGH" if gld_7d > 1.0 else "LOW" if gld_7d < -0.5 else "NORMAL"
        regime["gld_7d"] = gld_7d

    # IWM — small cap health (leads economic cycles)
    iwm = stock_technicals.get("IWM", {})
    if iwm:
        iwm_7d = iwm.get("7d_return", 0)
        regime["small_cap_signal"] = "RISK_ON" if iwm_7d > 1.0 else "RISK_OFF" if iwm_7d < -1.0 else "NEUTRAL"
        regime["iwm_7d"] = iwm_7d

    return regime


# ---------------------------------------------------------------------------
# Sector performance aggregation (zero API cost)
# ---------------------------------------------------------------------------

def _compute_sector_performance(stock_quotes: list[dict]) -> dict[str, dict]:
    """Aggregate stock performance by sector for rotation analysis."""
    sector_data: dict[str, list[float]] = {}
    for q in stock_quotes:
        sector = STOCK_SECTORS.get(q["symbol"])
        if not sector or sector == "ETF":
            continue
        pct = q.get("change_pct")
        if pct is not None:
            sector_data.setdefault(sector, []).append(pct)

    result = {}
    for sector, pcts in sector_data.items():
        avg_pct = round(sum(pcts) / len(pcts), 2) if pcts else 0
        result[sector] = {
            "avg_change_pct": avg_pct,
            "stocks_up": sum(1 for p in pcts if p > 0),
            "stocks_down": sum(1 for p in pcts if p < 0),
            "count": len(pcts),
        }
    return result


# ---------------------------------------------------------------------------
# Stock volatility batch computation (zero API cost — uses cached candles)
# ---------------------------------------------------------------------------

async def _compute_stock_volatility(symbols: list[str]) -> dict[str, float]:
    """Compute 20-day annualized volatility for each stock."""
    volatility = {}
    for symbol in symbols:
        candles = await get_stock_candles(symbol, days=60)
        if not candles or len(candles) < 21:
            continue
        closes = [c["close"] for c in candles]
        vol = _compute_historical_volatility(closes)
        if vol is not None:
            volatility[symbol] = vol
    return volatility


# ---------------------------------------------------------------------------
# Finnhub fundamental data fetchers
# ---------------------------------------------------------------------------

async def _fetch_stock_fundamentals(
    api_key: str, symbols: list[str]
) -> dict[str, dict]:
    """Fetch basic fundamentals for a batch of stocks from Finnhub.
    Returns {symbol: {pe, market_cap, 52w_high, 52w_low, beta, ...}}
    Rate limit: 60/min on free tier, so we batch carefully."""
    fundamentals = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for symbol in symbols:
            try:
                resp = await client.get(
                    f"{FINNHUB_BASE}/stock/metric",
                    params={
                        "symbol": symbol,
                        "metric": "all",
                        "token": api_key,
                    },
                )
                if resp.status_code != 200:
                    continue
                data = resp.json().get("metric", {})
                if not data:
                    continue
                fundamentals[symbol] = {
                    "pe_ratio": data.get("peBasicExclExtraTTM"),
                    "market_cap_m": data.get("marketCapitalization"),
                    "52w_high": data.get("52WeekHigh"),
                    "52w_low": data.get("52WeekLow"),
                    "beta": data.get("beta"),
                    "dividend_yield": data.get("dividendYieldIndicatedAnnual"),
                }
            except Exception:
                continue
            # Brief pause to stay under 60 req/min
            await asyncio.sleep(0.5)
    return fundamentals


async def _fetch_analyst_recommendations(
    api_key: str, symbols: list[str]
) -> dict[str, dict]:
    """Fetch latest analyst consensus (buy/hold/sell counts) from Finnhub."""
    recs = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for symbol in symbols:
            try:
                resp = await client.get(
                    f"{FINNHUB_BASE}/stock/recommendation",
                    params={"symbol": symbol, "token": api_key},
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if data:
                    latest = data[0]
                    recs[symbol] = {
                        "buy": latest.get("buy", 0) + latest.get("strongBuy", 0),
                        "hold": latest.get("hold", 0),
                        "sell": latest.get("sell", 0) + latest.get("strongSell", 0),
                    }
            except Exception:
                continue
            await asyncio.sleep(0.5)
    return recs


async def _fetch_upcoming_earnings(api_key: str) -> list[dict]:
    """Fetch earnings calendar for the next 7 days."""
    today = date.today()
    end = today + timedelta(days=7)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{FINNHUB_BASE}/calendar/earnings",
                params={
                    "from": today.isoformat(),
                    "to": end.isoformat(),
                    "token": api_key,
                },
            )
            if resp.status_code != 200:
                return []
            data = resp.json().get("earningsCalendar", [])
            # Filter to our supported stocks only
            supported = set(TOP_STOCKS.keys())
            return [
                {
                    "symbol": e["symbol"],
                    "date": e.get("date"),
                    "estimate_eps": e.get("epsEstimate"),
                }
                for e in data
                if e.get("symbol") in supported
            ][:20]
    except Exception:
        return []


async def _fetch_economic_calendar(api_key: str) -> list[dict]:
    """Fetch economic events for the next 7 days from Finnhub."""
    today = date.today()
    end = today + timedelta(days=7)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{FINNHUB_BASE}/calendar/economic",
                params={
                    "from": today.isoformat(),
                    "to": end.isoformat(),
                    "token": api_key,
                },
            )
            if resp.status_code != 200:
                return []
            events = resp.json().get("economicCalendar", [])
            # Filter to US events with medium/high impact
            result = []
            for e in events:
                impact = e.get("impact", 0)
                country = e.get("country", "")
                if country != "US" or impact < 2:
                    continue
                event_date = e.get("time", "")[:10]
                result.append({
                    "event": e.get("event", "Unknown"),
                    "date": event_date,
                    "time": e.get("time", ""),
                    "impact": impact,
                    "estimate": e.get("estimate"),
                    "actual": e.get("actual"),
                    "prev": e.get("prev"),
                    "unit": e.get("unit", ""),
                    "is_today": event_date == today.isoformat(),
                })
            return result[:20]
    except Exception:
        return []


async def _fetch_insider_transactions(
    api_key: str, symbols: list[str]
) -> dict[str, list[dict]]:
    """Fetch insider transactions for stocks from Finnhub. Top 10 symbols."""
    today = date.today()
    cutoff = (today - timedelta(days=30)).isoformat()
    result: dict[str, list[dict]] = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for symbol in symbols[:10]:
            try:
                await asyncio.sleep(0.5)
                resp = await client.get(
                    f"{FINNHUB_BASE}/stock/insider-transactions",
                    params={"symbol": symbol, "token": api_key},
                )
                if resp.status_code != 200:
                    continue
                txns = resp.json().get("data", [])
                significant = []
                for t in txns:
                    tx_date = t.get("transactionDate", "")
                    if tx_date < cutoff:
                        continue
                    shares = abs(t.get("share", 0))
                    price = t.get("transactionPrice", 0) or 0
                    value = shares * price
                    if value < 100_000:
                        continue
                    code = t.get("transactionCode", "")
                    side = "buy" if code in ("P", "A") else "sell" if code == "S" else "other"
                    if side == "other":
                        continue
                    significant.append({
                        "name": t.get("name", "Unknown"),
                        "side": side,
                        "shares": shares,
                        "value": round(value),
                        "date": tx_date,
                    })
                if significant:
                    result[symbol] = significant[:5]
            except Exception:
                continue
    return result


# ---------------------------------------------------------------------------
# Social/retail sentiment (StockTwits public API — no auth needed)
# ---------------------------------------------------------------------------

STOCKTWITS_BASE = "https://api.stocktwits.com/api/2"


async def _fetch_social_sentiment(symbols: list[str]) -> dict[str, dict]:
    """Fetch social sentiment from StockTwits for given symbols."""
    result: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=10) as client:
        for symbol in symbols[:10]:
            try:
                resp = await client.get(
                    f"{STOCKTWITS_BASE}/streams/symbol/{symbol}.json",
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                messages = data.get("messages", [])
                if not messages:
                    continue
                bullish = sum(1 for m in messages if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bullish")
                bearish = sum(1 for m in messages if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bearish")
                total = len(messages)
                labeled = bullish + bearish
                result[symbol] = {
                    "message_count": total,
                    "bullish_pct": round(bullish / labeled * 100, 1) if labeled else None,
                    "bearish_pct": round(bearish / labeled * 100, 1) if labeled else None,
                    "volume_signal": "HIGH" if total >= 25 else "LOW" if total <= 5 else "NORMAL",
                }
            except Exception:
                continue
    return result


# ---------------------------------------------------------------------------
# Crypto enrichment (from CoinGecko free tier)
# ---------------------------------------------------------------------------

async def _fetch_crypto_market_data() -> dict[str, dict]:
    """Fetch market cap, volume, and ATH data for all supported crypto."""
    ids = ",".join(info["coingecko_id"] for info in CRYPTO_MAP.values())
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{COINGECKO_BASE}/coins/markets",
                params={
                    "vs_currency": "usd",
                    "ids": ids,
                    "order": "market_cap_desc",
                    "sparkline": "false",
                },
            )
            if resp.status_code != 200:
                return {}
            data = resp.json()
            result = {}
            for coin in data:
                # Map coingecko_id back to our symbol
                symbol = None
                for sym, info in CRYPTO_MAP.items():
                    if info["coingecko_id"] == coin["id"]:
                        symbol = sym
                        break
                if not symbol:
                    continue
                ath = coin.get("ath", 0)
                price = coin.get("current_price", 0)
                market_cap = coin.get("market_cap", 0)
                volume_24h = coin.get("total_volume", 0)
                result[symbol] = {
                    "market_cap_rank": coin.get("market_cap_rank"),
                    "market_cap_b": round(market_cap / 1e9, 2),
                    "volume_24h_m": round(volume_24h / 1e6, 1),
                    "ath": ath,
                    "ath_drop_pct": round((1 - price / ath) * 100, 1) if ath else None,
                    "price_change_7d": coin.get("price_change_percentage_7d_in_currency"),
                    "price_change_14d": coin.get("price_change_percentage_14d_in_currency"),
                    "price_change_30d": coin.get("price_change_percentage_30d_in_currency"),
                    "market_cap_change_24h": coin.get("market_cap_change_percentage_24h"),
                    "volume_to_mcap": round(volume_24h / market_cap * 100, 2) if market_cap else None,
                }
            return result
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Stock technicals (derived from candle data we already fetch)
# ---------------------------------------------------------------------------

async def _compute_stock_technicals(symbols: list[str]) -> dict[str, dict]:
    """Compute technical indicators for stocks from 60-day candle data."""
    technicals = {}
    for symbol in symbols:
        candles = await get_stock_candles(symbol, days=60)
        if not candles or len(candles) < 14:
            continue
        closes = [c["close"] for c in candles]
        current_price = closes[-1]
        tech = _derive_technicals(closes, current_price, candles=candles)
        # Add volume analysis if available (Finnhub candles include volume)
        vol_analysis = _compute_volume_analysis(candles)
        if vol_analysis:
            tech["relative_volume"] = vol_analysis["relative_volume"]
        technicals[symbol] = tech
        # Candles are already cached (1 hour), no rate limit concern
    return technicals


async def _compute_crypto_technicals() -> dict[str, dict]:
    """Compute technical indicators for crypto from CoinGecko history.
    Uses the same _derive_technicals as stocks — zero extra API cost
    since get_crypto_history caches for 1 hour."""
    technicals = {}
    for symbol in CRYPTO_MAP:
        candles = await get_crypto_history(symbol, days=60)
        if not candles or len(candles) < 14:
            continue
        closes = [c["close"] for c in candles]
        current_price = closes[-1]
        technicals[symbol] = _derive_technicals(closes, current_price)
    # CoinGecko rate limit — add a small pause between symbols
    return technicals


# ---------------------------------------------------------------------------
# Company-specific news (Finnhub — same free tier, 1 call per symbol)
# ---------------------------------------------------------------------------

async def _fetch_company_news(
    api_key: str, symbols: list[str], max_per_symbol: int = 3
) -> dict[str, list[dict]]:
    """Fetch recent news for specific stocks. Useful for top movers.
    Limits to 5 symbols to stay within rate limits."""
    today = date.today()
    week_ago = today - timedelta(days=7)
    result = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for symbol in symbols[:5]:  # Max 5 to limit API calls
            try:
                resp = await client.get(
                    f"{FINNHUB_BASE}/company-news",
                    params={
                        "symbol": symbol,
                        "from": week_ago.isoformat(),
                        "to": today.isoformat(),
                        "token": api_key,
                    },
                )
                if resp.status_code != 200:
                    continue
                articles = resp.json()
                if articles:
                    result[symbol] = [
                        {
                            "headline": a.get("headline", ""),
                            "summary": a.get("summary", "")[:200],
                        }
                        for a in articles[:max_per_symbol]
                    ]
            except Exception:
                continue
            await asyncio.sleep(0.5)
    return result


# ---------------------------------------------------------------------------
# Day-over-day context (compare with previous brief)
# ---------------------------------------------------------------------------

async def _get_previous_brief() -> dict | None:
    """Get the second most recent market brief for day-over-day comparison."""
    db = get_supabase_admin()
    resp = (
        db.table("market_briefs")
        .select("brief_data")
        .order("brief_date", desc=True)
        .limit(2)
        .execute()
    )
    if resp.data and len(resp.data) >= 2:
        return resp.data[1]["brief_data"]
    return None


def _compute_day_over_day(current_brief: dict, previous_brief: dict) -> dict:
    """Compute changes between today and yesterday's brief."""
    dod = {}

    # Market regime shift
    curr_regime = current_brief.get("market_regime", {})
    prev_regime = previous_brief.get("market_regime", {})
    if curr_regime.get("market_trend") and prev_regime.get("market_trend"):
        curr_trend = curr_regime["market_trend"]
        prev_trend = prev_regime["market_trend"]
        if curr_trend != prev_trend:
            dod["regime_shift"] = f"{prev_trend} → {curr_trend}"
        else:
            dod["regime_shift"] = f"Still {curr_trend}"

    # Sector rotation shift
    curr_sectors = current_brief.get("sector_performance", {})
    prev_sectors = previous_brief.get("sector_performance", {})
    sector_changes = []
    for sector in curr_sectors:
        curr_avg = curr_sectors[sector].get("avg_change_pct", 0)
        prev_avg = prev_sectors.get(sector, {}).get("avg_change_pct", 0)
        if abs(curr_avg - prev_avg) > 0.5:  # Notable shift
            direction = "improving" if curr_avg > prev_avg else "weakening"
            sector_changes.append(f"{sector} {direction}")
    if sector_changes:
        dod["sector_shifts"] = sector_changes

    # SPY day-over-day
    prev_spy_7d = prev_regime.get("spy_7d")
    curr_spy_7d = curr_regime.get("spy_7d")
    if prev_spy_7d is not None and curr_spy_7d is not None:
        dod["spy_momentum_change"] = round(curr_spy_7d - prev_spy_7d, 2)

    # Sentiment shift
    curr_sent = current_brief.get("sentiment_scores", {}).get("market_sentiment")
    prev_sent = previous_brief.get("sentiment_scores", {}).get("market_sentiment")
    if curr_sent is not None and prev_sent is not None:
        shift = round(curr_sent - prev_sent, 3)
        if abs(shift) > 0.1:
            direction = "more bullish" if shift > 0 else "more bearish"
            dod["sentiment_shift"] = f"Market sentiment {direction} ({shift:+.3f})"

    return dod


# ---------------------------------------------------------------------------
# Main brief compilation
# ---------------------------------------------------------------------------

async def compile_market_brief() -> dict:
    """Compile a daily market brief with prices, fundamentals,
    technicals, analyst consensus, earnings, and news."""
    settings = get_settings()
    today = date.today()

    # 1. Fetch all stock quotes
    stock_quotes = []
    for symbol, name in TOP_STOCKS.items():
        quote = await get_quote(symbol, "stock")
        if quote:
            stock_quotes.append({
                "symbol": symbol,
                "name": name,
                "price": quote["price"],
                "change": quote.get("change"),
                "change_pct": quote.get("change_pct"),
            })

    # 2. Fetch all crypto quotes (single API call instead of 20 individual ones)
    all_crypto = await get_all_crypto_quotes()
    crypto_quotes = []
    for symbol, quote in all_crypto.items():
        crypto_quotes.append({
            "symbol": symbol,
            "name": CRYPTO_MAP[symbol]["name"],
            "price": quote["price"],
            "change": quote.get("change"),
            "change_pct": quote.get("change_pct"),
        })

    # 3. Fetch market news from Finnhub
    news = await _fetch_finnhub_news(settings.finnhub_api_key)

    # 4. Top movers
    movers_up = sorted(
        [s for s in stock_quotes if s.get("change_pct") and s["change_pct"] > 0],
        key=lambda s: s["change_pct"],
        reverse=True,
    )[:5]
    movers_down = sorted(
        [s for s in stock_quotes if s.get("change_pct") and s["change_pct"] < 0],
        key=lambda s: s["change_pct"],
    )[:5]

    # 5. Enrichment: fundamentals, analyst recs, earnings, technicals, crypto data
    # Only fetch fundamentals for top 20 stocks to stay under rate limits
    top_symbols = list(TOP_STOCKS.keys())[:20]

    # Run Finnhub sequential calls (fundamentals, then analyst recs) in parallel
    # with CoinGecko and cached-data calls (different APIs, no rate conflict)
    async def _finnhub_enrichment():
        funds = await _fetch_stock_fundamentals(settings.finnhub_api_key, top_symbols)
        recs = await _fetch_analyst_recommendations(settings.finnhub_api_key, top_symbols)
        earnings = await _fetch_upcoming_earnings(settings.finnhub_api_key)
        econ_cal = await _fetch_economic_calendar(settings.finnhub_api_key)
        insider = await _fetch_insider_transactions(settings.finnhub_api_key, top_symbols)
        return funds, recs, earnings, econ_cal, insider

    # Social sentiment uses StockTwits (separate API) — safe to run in parallel
    social_symbols = [m["symbol"] for m in (movers_up[:5] + movers_down[:5])]

    (fundamentals, analyst_recs, earnings_calendar, economic_calendar, insider_transactions), stock_technicals, crypto_market, social_sentiment = (
        await asyncio.gather(
            _finnhub_enrichment(),
            _compute_stock_technicals(top_symbols),
            _fetch_crypto_market_data(),
            _fetch_social_sentiment(social_symbols),
        )
    )

    # 6. Crypto technicals (uses cached CoinGecko history — minimal API cost)
    crypto_technicals = await _compute_crypto_technicals()

    # 7. New enrichment: market regime, sector performance, volatility
    # These are computed from data already fetched — zero additional API calls
    market_regime = await _detect_market_regime(stock_technicals)
    sector_performance = _compute_sector_performance(stock_quotes)
    stock_volatility = await _compute_stock_volatility(top_symbols)

    # 8. Company-specific news for today's top movers (5 API calls)
    mover_symbols = [m["symbol"] for m in (movers_up[:3] + movers_down[:2])]
    company_news = await _fetch_company_news(settings.finnhub_api_key, mover_symbols)

    # 9. Score headlines for sentiment (1 Groq API call)
    from app.services.sentiment import score_headlines
    _scored, sentiment_scores = await score_headlines(news, company_news)

    # 10. Day-over-day context
    previous_brief = await _get_previous_brief()
    day_over_day = None  # Will be computed after brief is assembled

    brief = {
        "date": today.isoformat(),
        "stocks": stock_quotes,
        "crypto": crypto_quotes,
        "top_gainers": movers_up,
        "top_losers": movers_down,
        "news": news,
        "company_news": company_news,
        "fundamentals": fundamentals,
        "analyst_recommendations": analyst_recs,
        "earnings_calendar": earnings_calendar,
        "stock_technicals": stock_technicals,
        "crypto_technicals": crypto_technicals,
        "crypto_market_data": crypto_market,
        "market_regime": market_regime,
        "sector_performance": sector_performance,
        "stock_volatility": stock_volatility,
        "sentiment_scores": sentiment_scores,
        "economic_calendar": economic_calendar,
        "insider_transactions": insider_transactions,
        "social_sentiment": social_sentiment,
    }

    # Compute day-over-day after regime/sectors are set
    if previous_brief:
        brief["day_over_day"] = _compute_day_over_day(brief, previous_brief)

    # 6. Upsert into market_briefs table
    db = get_supabase_admin()
    db.table("market_briefs").upsert(
        {"brief_date": today.isoformat(), "brief_data": brief},
        on_conflict="brief_date",
    ).execute()

    return brief


async def get_latest_brief() -> dict | None:
    """Get the most recent market brief from the database."""
    db = get_supabase_admin()
    resp = (
        db.table("market_briefs")
        .select("brief_data")
        .order("brief_date", desc=True)
        .limit(1)
        .execute()
    )
    if resp.data:
        return resp.data[0]["brief_data"]
    return None


async def _fetch_finnhub_news(api_key: str, max_items: int = 15) -> list[dict]:
    """Fetch general market news from Finnhub."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{FINNHUB_BASE}/news",
                params={
                    "category": "general",
                    "token": api_key,
                },
            )
            if resp.status_code != 200:
                return []
            articles = resp.json()
            return [
                {
                    "headline": a.get("headline", ""),
                    "summary": a.get("summary", "")[:300],
                    "source": a.get("source", ""),
                    "url": a.get("url", ""),
                    "datetime": a.get("datetime", 0),
                }
                for a in articles[:max_items]
            ]
    except Exception:
        return []
