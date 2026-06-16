#!/usr/bin/env python3
"""Backfill weekly + monthly journal summaries over historical daily commentary.

The Mistral/NVIDIA keys live only on Cloud Run, so this driver POSTs to the
deployed /api/ai/journals/generate endpoint (which runs the generation there)
rather than calling the service locally. Weeklies are generated first, then
monthlies (monthly reads the weeklies).

Generation is idempotent (skips traders that already have a summary for a
period), so this is safe to re-run and safe to interrupt.

⚠️ FREE-TIER NOTE: a full backfill is ~12 weeks x 25 + 3 months x 25 ≈ 375
Mistral calls. They're paced server-side, but mind the monthly token budget —
consider running a slice at a time (e.g. one month of weeks) via --weeks-from.

Usage:
  python3 scripts/backfill_journals.py --base-url https://...run.app \
      --start 2026-03-16 --end 2026-06-14 [--weekly-only] [--dry-run]
"""
import argparse
import sys
import time
from datetime import date, timedelta

import httpx


def mondays_between(start: date, end: date):
    """Yield each Monday whose Mon..Sun week overlaps [start, end]."""
    d = start - timedelta(days=start.weekday())  # Monday of start's week
    while d <= end:
        yield d
        d += timedelta(days=7)


def months_between(start: date, end: date):
    """Yield (year, month) for each calendar month touched by [start, end]."""
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m = 1 if m == 12 else m + 1
        y = y + 1 if m == 1 else y


def post(base_url: str, period_type: str, end_date: date, dry_run: bool) -> dict:
    url = f"{base_url.rstrip('/')}/api/ai/journals/generate"
    params = {"period_type": period_type, "end_date": end_date.isoformat()}
    if dry_run:
        print(f"  [dry-run] POST {url} {params}")
        return {}
    r = httpx.post(url, params=params, timeout=600)
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--start", required=True, help="YYYY-MM-DD (first day with daily journals)")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD (last day to cover)")
    ap.add_argument("--weekly-only", action="store_true")
    ap.add_argument("--monthly-only", action="store_true")
    ap.add_argument("--pause", type=float, default=5.0, help="seconds between periods")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    today = date.today()

    if not args.monthly_only:
        print("=== WEEKLY backfill ===")
        for monday in mondays_between(start, end):
            wk_end = monday + timedelta(days=6)
            if wk_end >= today:
                print(f"  skip incomplete week {monday}..{wk_end}")
                continue
            res = post(args.base_url, "weekly", monday + timedelta(days=3), args.dry_run)
            print(f"  week {monday}..{wk_end}: {res}")
            time.sleep(args.pause)

    if not args.weekly_only:
        print("=== MONTHLY backfill (reads weeklies — run after weekly) ===")
        for y, m in months_between(start, end):
            # only complete months
            month_end = (date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)) - timedelta(days=1)
            if month_end >= today:
                print(f"  skip incomplete month {y}-{m:02d}")
                continue
            res = post(args.base_url, "monthly", date(y, m, 15), args.dry_run)
            print(f"  month {y}-{m:02d}: {res}")
            time.sleep(args.pause)

    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
