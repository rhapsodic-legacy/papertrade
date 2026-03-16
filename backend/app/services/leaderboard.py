from datetime import date, timedelta

from app.services.supabase_client import get_supabase_admin

# Weights for each time period (must sum to 1.0)
WEIGHTS = {
    1: 0.10,   # 1-day return
    7: 0.20,   # 7-day return
    30: 0.30,  # 30-day return
    90: 0.40,  # 90-day return
}

PERIODS = sorted(WEIGHTS.keys())
STARTING_BALANCE = 100_000.0


async def get_scored_leaderboard(
    user_id: str | None = None,
    category: str = "human",
    limit: int = 25,
) -> dict:
    db = get_supabase_admin()
    today = date.today()

    # Fetch all profiles
    is_ai = category == "ai"
    profiles_resp = (
        db.table("profiles")
        .select("id, display_name, is_ai, ai_model")
        .eq("is_ai", is_ai)
        .execute()
    )
    profiles = {p["id"]: p for p in profiles_resp.data}

    if not profiles:
        return {"entries": [], "user_entry": None}

    # Fetch all AI profiles for computing fallback averages
    if not is_ai:
        ai_profiles_resp = (
            db.table("profiles")
            .select("id")
            .eq("is_ai", True)
            .execute()
        )
        ai_user_ids = {p["id"] for p in ai_profiles_resp.data}
    else:
        ai_user_ids = set(profiles.keys())

    # Fetch snapshots for the relevant date range
    earliest = today - timedelta(days=max(PERIODS) + 3)
    all_user_ids = list(profiles.keys()) + list(ai_user_ids - set(profiles.keys()))

    snapshots_resp = (
        db.table("portfolio_snapshots")
        .select("user_id, snapshot_date, total_value")
        .in_("user_id", all_user_ids)
        .gte("snapshot_date", earliest.isoformat())
        .lte("snapshot_date", today.isoformat())
        .order("snapshot_date", desc=False)
        .execute()
    )

    # Organize snapshots: {user_id: {date_str: total_value}}
    user_snapshots: dict[str, dict[str, float]] = {}
    for snap in snapshots_resp.data:
        uid = snap["user_id"]
        user_snapshots.setdefault(uid, {})[snap["snapshot_date"]] = float(snap["total_value"])

    # For each period, compute AI average return (for fallback)
    ai_period_averages: dict[int, float] = {}
    for period in PERIODS:
        target_date = today - timedelta(days=period)
        ai_returns = []
        for uid in ai_user_ids:
            snaps = user_snapshots.get(uid, {})
            current = _find_closest(snaps, today, window=2)
            past = _find_closest(snaps, target_date, window=3)
            if current is not None and past is not None and past > 0:
                ai_returns.append((current - past) / past * 100)
        ai_period_averages[period] = (
            sum(ai_returns) / len(ai_returns) if ai_returns else 0.0
        )

    # Score each user in the requested category
    scored = []
    for uid, profile in profiles.items():
        snaps = user_snapshots.get(uid, {})
        current = _find_closest(snaps, today, window=2)
        if current is None:
            current = STARTING_BALANCE

        period_returns = {}
        weighted_score = 0.0
        for period in PERIODS:
            target_date = today - timedelta(days=period)
            past = _find_closest(snaps, target_date, window=3)
            if past is not None and past > 0:
                ret = (current - past) / past * 100
            else:
                ret = ai_period_averages.get(period, 0.0)
            period_returns[period] = round(ret, 2)
            weighted_score += WEIGHTS[period] * ret

        scored.append({
            "display_name": profile["display_name"],
            "score": round(weighted_score, 2),
            "return_1d": period_returns[1],
            "return_7d": period_returns[7],
            "return_30d": period_returns[30],
            "return_90d": period_returns[90],
            "is_ai": profile["is_ai"],
            "ai_model": profile["ai_model"],
            "user_id": uid,
        })

    # Sort by score descending
    scored.sort(key=lambda e: e["score"], reverse=True)

    # Assign ranks
    for i, entry in enumerate(scored, 1):
        entry["rank"] = i

    # Find the requesting user's entry
    user_entry = None
    if user_id:
        for entry in scored:
            if entry["user_id"] == user_id:
                user_entry = {k: v for k, v in entry.items() if k != "user_id"}
                break

    # Trim to limit; keep user_id for AI traders (for profile links)
    entries = []
    for e in scored[:limit]:
        entry = {k: v for k, v in e.items()}
        if not e.get("is_ai"):
            entry.pop("user_id", None)
        entries.append(entry)

    return {"entries": entries, "user_entry": user_entry}


def _find_closest(
    snaps: dict[str, float], target: date, window: int = 3
) -> float | None:
    for offset in range(window + 1):
        key = (target - timedelta(days=offset)).isoformat()
        if key in snaps:
            return snaps[key]
    return None
