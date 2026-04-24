#!/usr/bin/env python3
"""Local Gemma preprocessing — runs on Mac mini via launchd.

Fetches today's market brief from Supabase, runs Gemma preprocessing
via local Ollama, and updates the brief with clustered/summarized data.

Designed to run at 4:55 PM ET (5 min before the Cloud Run pipeline).
If no brief exists yet or Ollama is down, exits gracefully.

Usage:
    python3 scripts/local_preprocess.py
"""

import asyncio
import os
import sys

# Add backend to path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


async def main():
    from datetime import date
    from app.services.supabase_client import get_supabase_admin
    from app.services.llm import is_ollama_available
    from app.services.gemma_preprocess import run_preprocessing, run_analyst_summarization

    # Check Ollama first
    if not await is_ollama_available():
        print("[LOCAL PREPROCESS] Ollama not available — exiting")
        return

    print("[LOCAL PREPROCESS] Ollama is up, checking for today's brief...")

    # Fetch today's brief from Supabase
    db = get_supabase_admin()
    today = date.today().isoformat()
    result = db.table("market_briefs").select("brief_data").eq("brief_date", today).execute()

    if not result.data:
        print(f"[LOCAL PREPROCESS] No brief found for {today} — nothing to preprocess")
        return

    brief = result.data[0]["brief_data"]

    # --- Step 1: Standard Gemma preprocessing (headlines, analyst, insider, movers) ---
    if brief.get("headline_clusters") is not None:
        print(f"[LOCAL PREPROCESS] Brief for {today} already has clusters — skipping standard preprocessing")
    else:
        print(f"[LOCAL PREPROCESS] Running Gemma preprocessing for {today}...")
        await run_preprocessing(brief)

    # --- Step 2: Analyst blog scraping + Gemma summarization ---
    print(f"[LOCAL PREPROCESS] Running analyst blog pipeline...")
    try:
        from app.services.analyst_scraper import run_analyst_scraping
        stored = await run_analyst_scraping()
        print(f"[LOCAL PREPROCESS] Analyst scraping: {stored} new articles stored")
    except Exception as e:
        print(f"[LOCAL PREPROCESS] Analyst scraping failed (non-fatal): {e}")

    try:
        summaries, digest = await run_analyst_summarization()
        if digest:
            brief["expert_opinion_digest"] = digest
            print(f"[LOCAL PREPROCESS] Expert opinion digest: {len(digest)} chars from {len(summaries)} articles")
        else:
            print(f"[LOCAL PREPROCESS] No expert opinion digest generated")
    except Exception as e:
        print(f"[LOCAL PREPROCESS] Analyst summarization failed (non-fatal): {e}")

    # Update the brief in Supabase
    db.table("market_briefs").update(
        {"brief_data": brief}
    ).eq("brief_date", today).execute()

    preprocess_keys = ("headline_clusters", "analyst_consensus", "insider_summary", "movers_narrative", "expert_opinion_digest")
    active = sum(1 for k in preprocess_keys if brief.get(k) is not None)
    print(f"[LOCAL PREPROCESS] Done — {active}/{len(preprocess_keys)} preprocessors updated brief for {today}")


if __name__ == "__main__":
    asyncio.run(main())
