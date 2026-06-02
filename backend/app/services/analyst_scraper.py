"""Analyst blog scraping pipeline.

Scrapes free public RSS feeds from independent financial analysts,
extracts article content, and stores in Supabase for Gemma summarization.

Sources cover macro, crypto, and tech/finance — all free, no API keys.
Designed to run during the daily brief compilation (~2 min).

Graceful degradation: if a source 403s or times out, skip it silently.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.services.supabase_client import get_supabase_admin


# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------

ANALYST_SOURCES: list[dict] = [
    # Macro
    {"key": "wolfstreet", "name": "Wolf Street", "url": "https://wolfstreet.com/feed/", "category": "macro"},
    {"key": "calculated_risk", "name": "Calculated Risk", "url": "https://www.calculatedriskblog.com/feeds/posts/default?alt=rss", "category": "macro"},
    {"key": "pragcap", "name": "Pragmatic Capitalism", "url": "https://www.pragcap.com/feed/", "category": "macro"},
    {"key": "mishtalk", "name": "Mish Talk", "url": "https://mishtalk.com/feed", "category": "macro"},
    {"key": "lyn_alden", "name": "Lyn Alden", "url": "https://www.lynalden.com/feed/", "category": "macro"},
    # Crypto
    {"key": "coindesk", "name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "category": "crypto"},
    {"key": "decrypt", "name": "Decrypt", "url": "https://decrypt.co/feed", "category": "crypto"},
    {"key": "cointelegraph", "name": "CoinTelegraph", "url": "https://cointelegraph.com/rss", "category": "crypto"},
    {"key": "the_defiant", "name": "The Defiant", "url": "https://thedefiant.io/feed", "category": "crypto"},
    # Tech/Finance
    {"key": "the_diff", "name": "The Diff", "url": "https://www.thediff.co/feed", "category": "tech_finance"},
    # Institutional / 13F-class — qualified-trader views that produce specific
    # ticker calls (longs, shorts, hedge-fund holdings). Added 2026-05-30 in
    # response to user-flagged Aschenbrenner short-semis thesis. These give
    # the expert_opinion digest its strongest source of conviction-weighted
    # ticker calls.
    {"key": "linas", "name": "Linas Substack", "url": "https://linas.substack.com/feed", "category": "tech_finance"},
    {"key": "net_interest", "name": "Net Interest (Marc Rubinstein)", "url": "https://www.netinterest.co/feed", "category": "tech_finance"},
    {"key": "bear_cave", "name": "The Bear Cave", "url": "https://thebearcave.substack.com/feed", "category": "tech_finance"},
    {"key": "bespoke", "name": "Bespoke Investment Group", "url": "https://www.bespokepremium.com/feed/", "category": "tech_finance"},
]

# Max age for articles to scrape (72 hours)
MAX_ARTICLE_AGE_HOURS = 72

# Polite delay between requests to same domain
REQUEST_DELAY_SECONDS = 2


# ---------------------------------------------------------------------------
# RSS parsing
# ---------------------------------------------------------------------------

def _parse_published(entry: dict) -> datetime | None:
    """Extract published datetime from a feedparser entry."""
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    # Try ISO string fallback
    for field in ("published", "updated"):
        val = entry.get(field)
        if val:
            try:
                # feedparser sometimes leaves raw strings
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(val).astimezone(timezone.utc)
            except Exception:
                pass
    return None


def _extract_text_from_html(html: str, max_chars: int = 5000) -> str:
    """Strip HTML tags and return plain text, truncated."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    # Remove script/style elements
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return text[:max_chars]


async def _fetch_full_content(url: str, client: httpx.AsyncClient) -> str | None:
    """Fetch full article content via HTTP when RSS entry is truncated."""
    try:
        resp = await client.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PaperTradeBot/1.0)"},
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        # Try common article content selectors
        for selector in ["article", ".post-content", ".entry-content", ".article-body", "main"]:
            content = soup.select_one(selector)
            if content:
                return _extract_text_from_html(str(content))
        # Fallback: grab body text
        body = soup.find("body")
        if body:
            return _extract_text_from_html(str(body))
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Core scraping logic
# ---------------------------------------------------------------------------

async def scrape_analyst_feeds() -> list[dict]:
    """Scrape all analyst RSS feeds, deduplicate, and return new articles.

    Returns list of dicts ready for Supabase insert:
        [{"source_key", "title", "url", "published_at", "content_text", "category"}]
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_ARTICLE_AGE_HOURS)

    # Get existing URLs for dedup
    db = get_supabase_admin()
    existing = db.table("analyst_content").select("url").execute()
    existing_urls = {row["url"] for row in (existing.data or [])}

    new_articles = []
    async with httpx.AsyncClient(timeout=30) as client:
        for source in ANALYST_SOURCES:
            try:
                articles = await _scrape_single_feed(
                    source, cutoff, existing_urls, client
                )
                new_articles.extend(articles)
                if articles:
                    print(f"[ANALYST] {source['name']}: {len(articles)} new articles")
            except Exception as e:
                print(f"[ANALYST] {source['name']} failed: {type(e).__name__}: {e}")
                continue
            # Polite delay between sources
            await asyncio.sleep(REQUEST_DELAY_SECONDS)

    print(f"[ANALYST] Total new articles scraped: {len(new_articles)}")
    return new_articles


async def _scrape_single_feed(
    source: dict,
    cutoff: datetime,
    existing_urls: set[str],
    client: httpx.AsyncClient,
) -> list[dict]:
    """Scrape a single RSS feed and return new articles."""
    # Fetch RSS feed
    resp = await client.get(
        source["url"],
        headers={"User-Agent": "Mozilla/5.0 (compatible; PaperTradeBot/1.0)"},
        follow_redirects=True,
    )
    if resp.status_code != 200:
        print(f"[ANALYST] {source['name']} returned HTTP {resp.status_code}")
        return []

    feed = feedparser.parse(resp.text)
    if not feed.entries:
        return []

    articles = []
    for entry in feed.entries[:10]:  # Max 10 per source
        url = entry.get("link", "")
        if not url or url in existing_urls:
            continue

        published = _parse_published(entry)
        if published and published < cutoff:
            continue

        title = entry.get("title", "").strip()
        if not title:
            continue

        # Try to get content from RSS entry first
        content_text = ""
        if entry.get("content"):
            # Atom feeds put content in entry.content[0].value
            content_text = _extract_text_from_html(entry.content[0].get("value", ""))
        elif entry.get("summary"):
            content_text = _extract_text_from_html(entry.summary)

        # If content is too short (truncated RSS), fetch full article
        if len(content_text) < 200:
            full = await _fetch_full_content(url, client)
            if full and len(full) > len(content_text):
                content_text = full
            await asyncio.sleep(1)  # Extra delay for full-page fetches

        if not content_text or len(content_text) < 50:
            continue

        articles.append({
            "source_key": source["key"],
            "title": title,
            "url": url,
            "published_at": published.isoformat() if published else datetime.now(timezone.utc).isoformat(),
            "content_text": content_text,
            "category": source["category"],
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        })

        existing_urls.add(url)  # Prevent dupes within same run

    return articles


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

async def store_analyst_articles(articles: list[dict]) -> int:
    """Insert new articles into Supabase analyst_content table.

    Returns number of articles stored.
    """
    if not articles:
        return 0

    db = get_supabase_admin()
    stored = 0
    for article in articles:
        try:
            db.table("analyst_content").insert(article).execute()
            stored += 1
        except Exception as e:
            # Likely a unique constraint violation on URL — skip silently
            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                continue
            print(f"[ANALYST] Failed to store '{article['title'][:50]}': {e}")
    return stored


# ---------------------------------------------------------------------------
# Fetch recent articles for summarization
# ---------------------------------------------------------------------------

async def get_unsummarized_articles(limit: int = 30) -> list[dict]:
    """Fetch recent articles that haven't been summarized yet."""
    db = get_supabase_admin()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=MAX_ARTICLE_AGE_HOURS)).isoformat()
    result = (
        db.table("analyst_content")
        .select("id, source_key, title, url, content_text, category, published_at")
        .is_("summary", "null")
        .gte("published_at", cutoff)
        .order("published_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


async def update_article_summary(article_id: str, summary_data: dict) -> None:
    """Update an article with its Gemma-generated summary."""
    db = get_supabase_admin()
    db.table("analyst_content").update(summary_data).eq("id", article_id).execute()


INSTITUTIONAL_SOURCE_KEYS = ("linas", "net_interest", "bear_cave", "bespoke")


async def get_recent_digested_articles(hours: int = 72, min_confidence: float = 0.3) -> list[dict]:
    """Fetch recently summarized articles for RAG injection.

    Only returns articles with confidence >= threshold. Two-pool merge
    (2026-06-01): a general pool (80 most recent) plus an institutional
    pool (20 most recent from Linas/Net Interest/Bear Cave/Bespoke). The
    institutional pool is queried separately because high-volume crypto
    news otherwise crowds out lower-frequency institutional sources even
    at the 80-article cap. The compress step applies reserved-slot
    ranking on top of this combined pool.
    """
    db = get_supabase_admin()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    cols = "source_key, title, summary, tickers, sentiment, analyst_call, confidence, category"

    general = (
        db.table("analyst_content")
        .select(cols)
        .not_.is_("summary", "null")
        .gte("confidence", min_confidence)
        .gte("published_at", cutoff)
        .order("published_at", desc=True)
        .limit(80)
        .execute()
    )

    # Wider window (14 days) and lower confidence floor (0.5) on the
    # institutional pool — these sources update less often and their
    # confidence scores skew lower than crypto news.
    inst_cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    institutional = (
        db.table("analyst_content")
        .select(cols)
        .not_.is_("summary", "null")
        .gte("confidence", 0.5)
        .gte("published_at", inst_cutoff)
        .in_("source_key", list(INSTITUTIONAL_SOURCE_KEYS))
        .order("published_at", desc=True)
        .limit(20)
        .execute()
    )

    # Merge, dedup by URL/title
    seen = set()
    merged = []
    for row in (general.data or []) + (institutional.data or []):
        key = row.get("title", "")
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


# ---------------------------------------------------------------------------
# Full pipeline: scrape + store
# ---------------------------------------------------------------------------

async def run_analyst_scraping() -> int:
    """Run the full scraping pipeline. Returns number of new articles stored."""
    articles = await scrape_analyst_feeds()
    stored = await store_analyst_articles(articles)
    print(f"[ANALYST] Pipeline complete: {stored} new articles stored")
    return stored
