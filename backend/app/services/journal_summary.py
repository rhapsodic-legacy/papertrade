"""Weekly & monthly journal summaries.

Each AI trader rolls up its DAILY commentary into a reflective WEEKLY entry, and
its 4 weekly entries into a MONTHLY entry. These are narrative/reflective — for
humans to read over time, and a future substrate the traders could learn from.
They are NOT injected into the daily trading prompt and they don't force signal;
the trader is free to surface insight or not (emergent).

Hierarchy keeps each prompt small:
  daily journals  ->  weekly summary
  4 weekly summaries  ->  monthly summary

HARD CONSTRAINT — these prompts ingest multiple prior journals and are LONG, so
they MUST run on Cloud Run with the paid Mistral/NVIDIA APIs. They must NEVER
route to local Gemma (the 8GB box crashes on long Gemma prompts). This module
calls the cloud providers directly and never touches the local tier.

Cadence: run on the WEEKEND, separated from the 5PM trading pipeline, so the
~25 summary calls don't contend with live trading for the shared Mistral keys.
"""

import asyncio
import json
from datetime import date, datetime, timedelta, timezone

from app.services.supabase_client import get_supabase_admin, fetch_all_rows
from app.config import get_settings
from app.services.ai_trader import (
    PERSONALITIES,
    MODELS,
    resolve_personality_key,
    _get_ai_portfolio,
    _call_mistral,
    _call_nvidia_nim,
    _call_groq,
    _call_gemini,
)

# Spacing between summary calls (seconds). Well under Mistral free-tier ~1 RPS;
# 25 traders * this = ~a couple minutes for the whole weekend job.
_SUMMARY_CALL_DELAY = 4.0


WEEKLY_SYSTEM = """\
You are an AI trader writing your WEEKLY journal — a reflective look back over \
the past week of trading, in your own voice and personality.

You will be given your daily journal entries for the week plus how your \
portfolio actually moved. Write a thoughtful weekly reflection that a curious \
human could learn from:
- What was your read on the market this week, and how did it evolve day to day?
- What did you do (key trades, holds, things you resisted) and WHY?
- What worked, what didn't, and what are you noticing about your own decisions?
- What are you watching going into next week?

This is reflection, not a trade plan. Be honest, specific, and human. Cite real \
moves and numbers from your week. Do NOT invent trades that aren't in your \
journals. 250-450 words.

Start with a single line: HEADLINE: <a punchy one-line summary of your week>"""


MONTHLY_SYSTEM = """\
You are an AI trader writing your MONTHLY journal — a reflective look back over \
the past month, in your own voice and personality.

You will be given your four WEEKLY journal entries for the month. Synthesize \
them into a higher-level reflection a curious human could learn from:
- What was the arc of the month? How did your thinking shift week to week?
- What were your best and worst decisions, and what do you make of them now?
- What patterns are you seeing in your OWN behavior over the month?
- What's your stance heading into next month?

This is reflection, not a trade plan. Be honest and specific, draw threads \
ACROSS the weeks rather than re-listing each one. Do NOT invent events not in \
your weekly entries. 300-500 words.

Start with a single line: HEADLINE: <a punchy one-line summary of your month>"""


def _iso_week_window(target: date) -> tuple[date, date]:
    """Monday..Sunday of the week containing `target`."""
    monday = target - timedelta(days=target.weekday())
    return monday, monday + timedelta(days=6)


def _last_completed_week(today: date) -> tuple[date, date]:
    """The most recent fully-completed Mon..Sun week before `today`."""
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(days=7)
    return last_monday, last_monday + timedelta(days=6)


def _month_window(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) - timedelta(days=1) if month == 12 \
        else date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def _last_completed_month(today: date) -> tuple[date, date]:
    first_this = date(today.year, today.month, 1)
    last_prev_end = first_this - timedelta(days=1)
    return _month_window(last_prev_end.year, last_prev_end.month)


async def _call_model_cloud(model_key: str, system: str, user_msg: str) -> str:
    """Dispatch to the trader's own model via its CLOUD provider. Never local
    Gemma — these prompts are long and would crash the 8GB box."""
    settings = get_settings()
    model_cfg = MODELS[model_key]
    api = model_cfg["api"]
    if api == "mistral":
        key_field = model_cfg.get("api_key_field", "mistral_api_key")
        api_key = getattr(settings, key_field, "") or settings.mistral_api_key
        if not api_key:
            raise Exception(f"{key_field} not configured")
        return await _call_mistral(model_cfg["model_id"], system, user_msg, api_key)
    if api == "nvidia":
        if not settings.nvidia_api_key:
            raise Exception("nvidia_api_key not configured")
        return await _call_nvidia_nim(model_cfg["model_id"], system, user_msg, settings.nvidia_api_key)
    if api == "groq":
        if not settings.groq_api_key:
            raise Exception("groq_api_key not configured")
        return await _call_groq(model_cfg["model_id"], system, user_msg, settings.groq_api_key)
    if api == "gemini":
        if not settings.gemini_api_key:
            raise Exception("gemini_api_key not configured")
        return await _call_gemini(model_cfg["model_id"], system, user_msg, settings.gemini_api_key)
    raise Exception(f"Unknown api for model {model_key}: {api}")


def _parse_headline(raw: str) -> str:
    """Match the daily-commentary storage format: 'HEADLINE:<x>\\n<body>'."""
    text = raw.strip()
    if text.upper().startswith("HEADLINE:"):
        parts = text.split("\n", 1)
        headline = parts[0].split(":", 1)[1].strip()
        body = parts[1].strip() if len(parts) > 1 else text
        return f"HEADLINE:{headline}\n{body}"
    return text


def _already_exists(db, user_id: str, period_end: date, summary_type: str) -> bool:
    r = (
        db.table("ai_commentary")
        .select("id")
        .eq("user_id", user_id)
        .eq("commentary_date", period_end.isoformat())
        .eq("summary_type", summary_type)
        .limit(1)
        .execute()
    )
    return bool(r.data)


def _week_return_pct(db, user_id: str, start: date, end: date) -> float | None:
    rows = fetch_all_rows(
        db.table("portfolio_snapshots")
        .select("snapshot_date, total_value")
        .eq("user_id", user_id)
        .gte("snapshot_date", start.isoformat())
        .lte("snapshot_date", end.isoformat())
        .order("snapshot_date", desc=False)
    )
    if len(rows) < 2:
        return None
    a, b = float(rows[0]["total_value"]), float(rows[-1]["total_value"])
    return ((b / a) - 1) * 100 if a > 0 else None


async def _build_weekly(db, user_id: str, start: date, end: date) -> str | None:
    """Assemble the weekly prompt body from this trader's daily journals +
    actual portfolio move. Returns None if there's nothing to summarize."""
    dailies = fetch_all_rows(
        db.table("ai_commentary")
        .select("commentary_date, commentary, trades_summary")
        .eq("user_id", user_id)
        .eq("summary_type", "daily")
        .gte("commentary_date", start.isoformat())
        .lte("commentary_date", end.isoformat())
        .order("commentary_date", desc=False)
    )
    if not dailies:
        return None

    parts = [f"## Your Daily Journals — week of {start.isoformat()} to {end.isoformat()}\n"]
    for d in dailies:
        body = d["commentary"]
        if body.upper().startswith("HEADLINE:"):
            body = body.split("\n", 1)[-1].strip()
        trades = d.get("trades_summary")
        if isinstance(trades, str):
            try:
                trades = json.loads(trades)
            except (json.JSONDecodeError, TypeError):
                trades = []
        tline = ""
        if trades:
            tline = "  trades: " + ", ".join(
                f"{t['side']} {t['quantity']} {t['symbol']}" for t in trades
            )
        parts.append(f"### {d['commentary_date']}\n{body}\n{tline}")

    wk_ret = _week_return_pct(db, user_id, start, end)
    if wk_ret is not None:
        parts.append(f"\n## How your portfolio actually moved this week: {wk_ret:+.2f}%")
    return "\n\n".join(parts)


async def _build_monthly(db, user_id: str, start: date, end: date) -> str | None:
    """Assemble the monthly prompt body from this trader's weekly summaries."""
    weeklies = fetch_all_rows(
        db.table("ai_commentary")
        .select("period_start, period_end, commentary")
        .eq("user_id", user_id)
        .eq("summary_type", "weekly")
        .gte("commentary_date", start.isoformat())
        .lte("commentary_date", end.isoformat())
        .order("commentary_date", desc=False)
    )
    if not weeklies:
        return None
    parts = [f"## Your Weekly Journals — {start.isoformat()} to {end.isoformat()}\n"]
    for w in weeklies:
        body = w["commentary"]
        if body.upper().startswith("HEADLINE:"):
            body = body.split("\n", 1)[-1].strip()
        label = f"Week {w.get('period_start','?')}..{w.get('period_end','?')}"
        parts.append(f"### {label}\n{body}")
    return "\n\n".join(parts)


async def generate_period_summaries(
    period_type: str,
    end_date: date | None = None,
    only_user_id: str | None = None,
) -> dict:
    """Generate weekly or monthly journal summaries for all AI traders.

    period_type : 'weekly' | 'monthly'
    end_date    : a date inside the target period (defaults to the most recent
                  COMPLETED period). For weekly, the Mon..Sun week is used; for
                  monthly, the calendar month.
    only_user_id: restrict to one trader (used for tests/backfill of a single).
    """
    assert period_type in ("weekly", "monthly")
    db = get_supabase_admin()
    today = datetime.now(timezone.utc).date()

    if period_type == "weekly":
        start, end = _iso_week_window(end_date) if end_date else _last_completed_week(today)
        system = WEEKLY_SYSTEM
        build = _build_weekly
    else:
        if end_date:
            start, end = _month_window(end_date.year, end_date.month)
        else:
            start, end = _last_completed_month(today)
        system = MONTHLY_SYSTEM
        build = _build_monthly

    profiles = db.table("profiles").select("id, display_name, ai_model").eq("is_ai", True)
    if only_user_id:
        profiles = profiles.eq("id", only_user_id)
    profiles = profiles.execute().data or []

    result = {"period_type": period_type, "period": f"{start} .. {end}",
              "generated": 0, "skipped": 0, "errors": 0}

    for i, p in enumerate(profiles):
        user_id = p["id"]
        display_name = p["display_name"]
        model_key = p.get("ai_model")
        if model_key not in MODELS:
            result["skipped"] += 1
            continue
        personality_key = resolve_personality_key(display_name)
        if not personality_key:
            result["skipped"] += 1
            continue

        if _already_exists(db, user_id, end, period_type):
            result["skipped"] += 1
            continue

        try:
            body = await build(db, user_id, start, end)
            if not body:
                result["skipped"] += 1
                continue

            user_msg = (
                f"## Your Strategy\n{PERSONALITIES[personality_key]['prompt'][:600]}...\n\n{body}\n\n"
                f"Write your {period_type} journal reflection now."
            )
            if i > 0:
                await asyncio.sleep(_SUMMARY_CALL_DELAY)
            raw = await _call_model_cloud(model_key, system, user_msg)
            stored = _parse_headline(raw)

            db.table("ai_commentary").insert({
                "user_id": user_id,
                "commentary_date": end.isoformat(),
                "display_name": display_name,
                "personality": personality_key,
                "model": model_key,
                "commentary": stored,
                "trades_summary": json.dumps([]),
                "summary_type": period_type,
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
            }).execute()
            result["generated"] += 1
            print(f"[JOURNAL] {period_type} {display_name}: generated ({start}..{end})")
        except Exception as e:
            result["errors"] += 1
            print(f"[JOURNAL] {period_type} {display_name}: error {e}")

    return result
