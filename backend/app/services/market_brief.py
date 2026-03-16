import asyncio
import httpx
from datetime import date, datetime, timedelta, timezone

from app.config import get_settings
from app.services.market_data import (
    TOP_STOCKS,
    CRYPTO_MAP,
    get_quote,
    get_stock_candles,
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


def _derive_technicals(closes: list[float], current_price: float) -> dict:
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
    return technicals


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
                result[symbol] = {
                    "market_cap_rank": coin.get("market_cap_rank"),
                    "market_cap_b": round(coin.get("market_cap", 0) / 1e9, 2),
                    "volume_24h_m": round(coin.get("total_volume", 0) / 1e6, 1),
                    "ath": ath,
                    "ath_drop_pct": round((1 - price / ath) * 100, 1) if ath else None,
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
        technicals[symbol] = _derive_technicals(closes, current_price)
        # Candles are already cached (1 hour), no rate limit concern
    return technicals


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

    # 2. Fetch all crypto quotes
    crypto_quotes = []
    for symbol, info in CRYPTO_MAP.items():
        quote = await get_quote(symbol, "crypto")
        if quote:
            crypto_quotes.append({
                "symbol": symbol,
                "name": info["name"],
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
    fundamentals = await _fetch_stock_fundamentals(
        settings.finnhub_api_key, top_symbols
    )
    analyst_recs = await _fetch_analyst_recommendations(
        settings.finnhub_api_key, top_symbols
    )
    earnings_calendar = await _fetch_upcoming_earnings(settings.finnhub_api_key)
    stock_technicals = await _compute_stock_technicals(top_symbols)
    crypto_market = await _fetch_crypto_market_data()

    brief = {
        "date": today.isoformat(),
        "stocks": stock_quotes,
        "crypto": crypto_quotes,
        "top_gainers": movers_up,
        "top_losers": movers_down,
        "news": news,
        "fundamentals": fundamentals,
        "analyst_recommendations": analyst_recs,
        "earnings_calendar": earnings_calendar,
        "stock_technicals": stock_technicals,
        "crypto_market_data": crypto_market,
    }

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
