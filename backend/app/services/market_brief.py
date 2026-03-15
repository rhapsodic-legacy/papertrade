import httpx
from datetime import date, datetime, timedelta, timezone

from app.config import get_settings
from app.services.market_data import (
    TOP_STOCKS,
    CRYPTO_MAP,
    get_quote,
    FINNHUB_BASE,
)
from app.services.supabase_client import get_supabase_admin


async def compile_market_brief() -> dict:
    """Compile a daily market brief from prices and news. Returns the brief dict."""
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

    # 4. Fetch top movers (sort stocks by absolute change %)
    movers_up = sorted(
        [s for s in stock_quotes if s.get("change_pct") and s["change_pct"] > 0],
        key=lambda s: s["change_pct"],
        reverse=True,
    )[:5]
    movers_down = sorted(
        [s for s in stock_quotes if s.get("change_pct") and s["change_pct"] < 0],
        key=lambda s: s["change_pct"],
    )[:5]

    brief = {
        "date": today.isoformat(),
        "stocks": stock_quotes,
        "crypto": crypto_quotes,
        "top_gainers": movers_up,
        "top_losers": movers_down,
        "news": news,
    }

    # 5. Upsert into market_briefs table
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
