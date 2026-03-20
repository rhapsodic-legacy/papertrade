import httpx
import time
from datetime import datetime, timezone

from app.config import get_settings

# Top stocks from major exchanges
TOP_STOCKS = {
    # Mega cap tech
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "GOOGL": "Alphabet",
    "AMZN": "Amazon",
    "NVDA": "NVIDIA",
    "META": "Meta Platforms",
    "TSLA": "Tesla",
    # Finance
    "BRK.B": "Berkshire Hathaway",
    "JPM": "JPMorgan Chase",
    "V": "Visa",
    "MA": "Mastercard",
    "GS": "Goldman Sachs",
    "BAC": "Bank of America",
    # Healthcare
    "JNJ": "Johnson & Johnson",
    "UNH": "UnitedHealth",
    "PFE": "Pfizer",
    "ABBV": "AbbVie",
    "MRK": "Merck",
    "LLY": "Eli Lilly",
    # Consumer
    "WMT": "Walmart",
    "PG": "Procter & Gamble",
    "KO": "Coca Cola",
    "PEP": "PepsiCo",
    "COST": "Costco",
    "MCD": "McDonalds",
    "NKE": "Nike",
    "SBUX": "Starbucks",
    # Tech / Software
    "NFLX": "Netflix",
    "ADBE": "Adobe",
    "CRM": "Salesforce",
    "INTC": "Intel",
    "AMD": "AMD",
    "ORCL": "Oracle",
    "CSCO": "Cisco",
    "QCOM": "Qualcomm",
    "AVGO": "Broadcom",
    "NOW": "ServiceNow",
    "UBER": "Uber",
    "SQ": "Block",
    "SHOP": "Shopify",
    "SNOW": "Snowflake",
    "PLTR": "Palantir",
    # Industrial / Energy
    "HD": "Home Depot",
    "DIS": "Walt Disney",
    "BA": "Boeing",
    "CAT": "Caterpillar",
    "XOM": "Exxon Mobil",
    "CVX": "Chevron",
    # International ADRs (Asia)
    "BABA": "Alibaba",
    "TSM": "Taiwan Semiconductor",
    "TM": "Toyota Motor",
    "SONY": "Sony Group",
    "NIO": "NIO",
    "BIDU": "Baidu",
    "INFY": "Infosys",
    "HDB": "HDFC Bank",
    "GRAB": "Grab Holdings",
    "SE": "Sea Limited",
    # ETFs
    "SPY": "S&P 500 ETF",
    "QQQ": "Nasdaq 100 ETF",
    "IWM": "Russell 2000 ETF",
    "GLD": "Gold ETF",
    "TLT": "20+ Year Treasury ETF",
}

# Supported cryptocurrencies
CRYPTO_MAP = {
    "BTC": {"coingecko_id": "bitcoin", "name": "Bitcoin"},
    "ETH": {"coingecko_id": "ethereum", "name": "Ethereum"},
    "SOL": {"coingecko_id": "solana", "name": "Solana"},
    "ADA": {"coingecko_id": "cardano", "name": "Cardano"},
    "DOT": {"coingecko_id": "polkadot", "name": "Polkadot"},
    "LINK": {"coingecko_id": "chainlink", "name": "Chainlink"},
    "AVAX": {"coingecko_id": "avalanche-2", "name": "Avalanche"},
    "AUKI": {"coingecko_id": "auki-labs", "name": "Auki Labs"},
    "XRP": {"coingecko_id": "ripple", "name": "XRP"},
    "DOGE": {"coingecko_id": "dogecoin", "name": "Dogecoin"},
    "SHIB": {"coingecko_id": "shiba-inu", "name": "Shiba Inu"},
    "MATIC": {"coingecko_id": "matic-network", "name": "Polygon"},
    "UNI": {"coingecko_id": "uniswap", "name": "Uniswap"},
    "ATOM": {"coingecko_id": "cosmos", "name": "Cosmos"},
    "NEAR": {"coingecko_id": "near", "name": "NEAR Protocol"},
    "APT": {"coingecko_id": "aptos", "name": "Aptos"},
    "ARB": {"coingecko_id": "arbitrum", "name": "Arbitrum"},
    "OP": {"coingecko_id": "optimism", "name": "Optimism"},
    "SUI": {"coingecko_id": "sui", "name": "Sui"},
    "RENDER": {"coingecko_id": "render-token", "name": "Render"},
}

# Sector classification (zero API cost — used for portfolio exposure analysis)
STOCK_SECTORS = {
    # Technology
    "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Technology",
    "AMZN": "Technology", "NVDA": "Technology", "META": "Technology",
    "TSLA": "Technology", "NFLX": "Technology", "ADBE": "Technology",
    "CRM": "Technology", "INTC": "Technology", "AMD": "Technology",
    "ORCL": "Technology", "CSCO": "Technology", "QCOM": "Technology",
    "AVGO": "Technology", "NOW": "Technology", "UBER": "Technology",
    "SQ": "Technology", "SHOP": "Technology", "SNOW": "Technology",
    "PLTR": "Technology", "TSM": "Technology", "BABA": "Technology",
    "BIDU": "Technology", "INFY": "Technology", "SE": "Technology",
    "GRAB": "Technology",
    # Finance
    "BRK.B": "Finance", "JPM": "Finance", "V": "Finance",
    "MA": "Finance", "GS": "Finance", "BAC": "Finance", "HDB": "Finance",
    # Healthcare
    "JNJ": "Healthcare", "UNH": "Healthcare", "PFE": "Healthcare",
    "ABBV": "Healthcare", "MRK": "Healthcare", "LLY": "Healthcare",
    # Consumer
    "WMT": "Consumer", "PG": "Consumer", "KO": "Consumer",
    "PEP": "Consumer", "COST": "Consumer", "MCD": "Consumer",
    "NKE": "Consumer", "SBUX": "Consumer", "DIS": "Consumer",
    # Industrial / Energy
    "HD": "Industrial", "BA": "Industrial", "CAT": "Industrial",
    "XOM": "Energy", "CVX": "Energy",
    # Automotive
    "TM": "Consumer", "NIO": "Technology", "SONY": "Technology",
    # ETFs (macro proxies)
    "SPY": "ETF", "QQQ": "ETF", "IWM": "ETF", "GLD": "ETF", "TLT": "ETF",
}

FINNHUB_BASE = "https://finnhub.io/api/v1"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Price cache: {symbol: {"data": dict, "timestamp": float}}
# Stock quotes update every 15 min (Finnhub delay), crypto less frequently on free tier
STOCK_CACHE_TTL = 30
CRYPTO_CACHE_TTL = 300  # 5 minutes — CoinGecko free tier is heavily rate-limited
CHART_CACHE_TTL = 3600  # 1 hour — historical data doesn't change often
_price_cache: dict[str, dict] = {}
_chart_cache: dict[str, dict] = {}


def _get_cached(symbol: str) -> dict | None:
    entry = _price_cache.get(symbol)
    if not entry:
        return None
    ttl = CRYPTO_CACHE_TTL if entry["data"].get("asset_type") == "crypto" else STOCK_CACHE_TTL
    if (time.time() - entry["timestamp"]) < ttl:
        return entry["data"]
    return None


def _set_cached(symbol: str, data: dict) -> None:
    _price_cache[symbol] = {"data": data, "timestamp": time.time()}


def _get_chart_cached(key: str) -> list | None:
    entry = _chart_cache.get(key)
    if entry and (time.time() - entry["timestamp"]) < CHART_CACHE_TTL:
        return entry["data"]
    return None


def _set_chart_cached(key: str, data: list) -> None:
    _chart_cache[key] = {"data": data, "timestamp": time.time()}


def is_stock_market_open() -> bool:
    now = datetime.now(timezone.utc)
    # NYSE/NASDAQ: Mon-Fri, 9:30 AM - 4:00 PM ET (UTC-5 / UTC-4 DST)
    # Simplified: check weekday and approximate hours
    if now.weekday() >= 5:  # Saturday or Sunday
        return False
    et_hour = (now.hour - 5) % 24  # rough EST conversion
    return 9 <= et_hour < 16


async def get_stock_quote(symbol: str) -> dict | None:
    cached = _get_cached(symbol)
    if cached:
        return cached

    settings = get_settings()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{FINNHUB_BASE}/quote",
            params={"symbol": symbol, "token": settings.finnhub_api_key},
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("c", 0) == 0:
            return None
        result = {
            "symbol": symbol,
            "asset_type": "stock",
            "price": data["c"],  # current price
            "change": data["d"],  # change
            "change_pct": data["dp"],  # change percent
            "name": TOP_STOCKS.get(symbol, symbol),
        }
        _set_cached(symbol, result)
        return result


async def get_crypto_quote(symbol: str) -> dict | None:
    cached = _get_cached(symbol)
    if cached:
        return cached

    crypto = CRYPTO_MAP.get(symbol.upper())
    if not crypto:
        return None
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{COINGECKO_BASE}/simple/price",
            params={
                "ids": crypto["coingecko_id"],
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "precision": "full",
            },
        )
        if resp.status_code == 429:
            # Rate limited — return stale cache if available, else None
            stale = _price_cache.get(symbol)
            return stale["data"] if stale else None
        if resp.status_code != 200:
            return None
        data = resp.json()
        coin_data = data.get(crypto["coingecko_id"], {})
        price = coin_data.get("usd")
        if price is None:
            return None
        change_pct = coin_data.get("usd_24h_change")
        result = {
            "symbol": symbol.upper(),
            "asset_type": "crypto",
            "price": price,
            "change": round(price * (change_pct / 100), 6) if change_pct else None,
            "change_pct": round(change_pct, 2) if change_pct else None,
            "name": crypto["name"],
        }
        _set_cached(symbol, result)
        return result


async def get_quote(symbol: str, asset_type: str) -> dict | None:
    if asset_type == "stock":
        return await get_stock_quote(symbol.upper())
    elif asset_type == "crypto":
        return await get_crypto_quote(symbol.upper())
    return None


async def get_stock_candles(symbol: str, days: int = 30) -> list[dict]:
    """Fetch historical daily candles from Finnhub."""
    cache_key = f"stock_candle:{symbol.upper()}:{days}"
    cached = _get_chart_cached(cache_key)
    if cached is not None:
        return cached

    settings = get_settings()
    now = int(datetime.now(timezone.utc).timestamp())
    start = now - (days * 86400)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{FINNHUB_BASE}/stock/candle",
                params={
                    "symbol": symbol.upper(),
                    "resolution": "D",
                    "from": start,
                    "to": now,
                    "token": settings.finnhub_api_key,
                },
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            if data.get("s") != "ok":
                return []
            candles = []
            for i in range(len(data.get("t", []))):
                candles.append({
                    "time": data["t"][i],
                    "open": data["o"][i],
                    "high": data["h"][i],
                    "low": data["l"][i],
                    "close": data["c"][i],
                })
            _set_chart_cached(cache_key, candles)
            return candles
    except httpx.TimeoutException:
        return []


async def get_crypto_history(symbol: str, days: int = 30) -> list[dict]:
    """Fetch historical daily prices from CoinGecko."""
    cache_key = f"crypto_chart:{symbol.upper()}:{days}"
    cached = _get_chart_cached(cache_key)
    if cached is not None:
        return cached

    crypto = CRYPTO_MAP.get(symbol.upper())
    if not crypto:
        return []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{COINGECKO_BASE}/coins/{crypto['coingecko_id']}/market_chart",
                params={"vs_currency": "usd", "days": days, "interval": "daily"},
            )
            if resp.status_code in (429, 403):
                # Rate limited — return stale chart cache if available
                stale = _chart_cache.get(cache_key)
                return stale["data"] if stale else []
            if resp.status_code != 200:
                return []
            data = resp.json()
            points = []
            for ts, price in data.get("prices", []):
                points.append({
                    "time": int(ts / 1000),
                    "close": price,
                })
            _set_chart_cached(cache_key, points)
            return points
    except httpx.TimeoutException:
        return []


async def get_available_assets() -> dict:
    return {
        "stocks": [
            {"symbol": sym, "name": name} for sym, name in TOP_STOCKS.items()
        ],
        "crypto": [
            {"symbol": sym, "name": info["name"]}
            for sym, info in CRYPTO_MAP.items()
        ],
    }
