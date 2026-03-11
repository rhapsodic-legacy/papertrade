import httpx
from datetime import datetime, timezone

from app.config import get_settings

# Top stocks from major exchanges
TOP_STOCKS = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "GOOGL": "Alphabet",
    "AMZN": "Amazon",
    "NVDA": "NVIDIA",
    "META": "Meta Platforms",
    "TSLA": "Tesla",
    "BRK.B": "Berkshire Hathaway",
    "JPM": "JPMorgan Chase",
    "V": "Visa",
    "JNJ": "Johnson & Johnson",
    "WMT": "Walmart",
    "PG": "Procter & Gamble",
    "MA": "Mastercard",
    "HD": "Home Depot",
    "DIS": "Walt Disney",
    "NFLX": "Netflix",
    "ADBE": "Adobe",
    "CRM": "Salesforce",
    "INTC": "Intel",
}

# Supported cryptocurrencies
CRYPTO_MAP = {
    "BTC": {"coingecko_id": "bitcoin", "name": "Bitcoin"},
    "ETH": {"coingecko_id": "ethereum", "name": "Ethereum"},
    "AUKI": {"coingecko_id": "auki-labs", "name": "Auki Labs"},
    "SOL": {"coingecko_id": "solana", "name": "Solana"},
    "ADA": {"coingecko_id": "cardano", "name": "Cardano"},
    "DOT": {"coingecko_id": "polkadot", "name": "Polkadot"},
    "LINK": {"coingecko_id": "chainlink", "name": "Chainlink"},
    "AVAX": {"coingecko_id": "avalanche-2", "name": "Avalanche"},
}

FINNHUB_BASE = "https://finnhub.io/api/v1"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"


def is_stock_market_open() -> bool:
    now = datetime.now(timezone.utc)
    # NYSE/NASDAQ: Mon-Fri, 9:30 AM - 4:00 PM ET (UTC-5 / UTC-4 DST)
    # Simplified: check weekday and approximate hours
    if now.weekday() >= 5:  # Saturday or Sunday
        return False
    et_hour = (now.hour - 5) % 24  # rough EST conversion
    return 9 <= et_hour < 16


async def get_stock_quote(symbol: str) -> dict | None:
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
        return {
            "symbol": symbol,
            "asset_type": "stock",
            "price": data["c"],  # current price
            "change": data["d"],  # change
            "change_pct": data["dp"],  # change percent
            "name": TOP_STOCKS.get(symbol, symbol),
        }


async def get_crypto_quote(symbol: str) -> dict | None:
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
        return {
            "symbol": symbol.upper(),
            "asset_type": "crypto",
            "price": price,
            "change": round(price * (change_pct / 100), 2) if change_pct else None,
            "change_pct": round(change_pct, 2) if change_pct else None,
            "name": crypto["name"],
        }


async def get_quote(symbol: str, asset_type: str) -> dict | None:
    if asset_type == "stock":
        return await get_stock_quote(symbol.upper())
    elif asset_type == "crypto":
        return await get_crypto_quote(symbol.upper())
    return None


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
