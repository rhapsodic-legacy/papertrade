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

FINNHUB_BASE = "https://finnhub.io/api/v1"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Price cache: {symbol: {"data": quote_dict, "timestamp": float}}
CACHE_TTL_SECONDS = 30
_price_cache: dict[str, dict] = {}


def _get_cached(symbol: str) -> dict | None:
    entry = _price_cache.get(symbol)
    if entry and (time.time() - entry["timestamp"]) < CACHE_TTL_SECONDS:
        return entry["data"]
    return None


def _set_cached(symbol: str, data: dict) -> None:
    _price_cache[symbol] = {"data": data, "timestamp": time.time()}


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
    async with httpx.AsyncClient() as client:
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
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{COINGECKO_BASE}/simple/price",
            params={
                "ids": crypto["coingecko_id"],
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "precision": "full",
            },
        )
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
    settings = get_settings()
    now = int(datetime.now(timezone.utc).timestamp())
    start = now - (days * 86400)
    async with httpx.AsyncClient() as client:
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
        return candles


async def get_crypto_history(symbol: str, days: int = 30) -> list[dict]:
    """Fetch historical daily prices from CoinGecko."""
    crypto = CRYPTO_MAP.get(symbol.upper())
    if not crypto:
        return []
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{COINGECKO_BASE}/coins/{crypto['coingecko_id']}/market_chart",
            params={"vs_currency": "usd", "days": days, "interval": "daily"},
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        points = []
        for ts, price in data.get("prices", []):
            points.append({
                "time": int(ts / 1000),
                "close": price,
            })
        return points


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
