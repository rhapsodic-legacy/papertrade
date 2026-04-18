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
    from app.services.gemma_preprocess import run_preprocessing

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

    # Skip if already preprocessed
    if brief.get("headline_clusters") is not None:
        print(f"[LOCAL PREPROCESS] Brief for {today} already has clusters — skipping")
        return

    print(f"[LOCAL PREPROCESS] Running Gemma preprocessing for {today}...")
    await run_preprocessing(brief)

    # Update the brief in Supabase
    db.table("market_briefs").update(
        {"brief_data": brief}
    ).eq("brief_date", today).execute()

    active = sum(1 for k in ("headline_clusters", "analyst_consensus", "insider_summary")
                 if brief.get(k) is not None)
    print(f"[LOCAL PREPROCESS] Done — {active}/3 preprocessors updated brief for {today}")


if __name__ == "__main__":
    asyncio.run(main())
