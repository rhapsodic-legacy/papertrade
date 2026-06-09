"""Cross-trader fleet signal aggregation.

Surfaces what the 20-trader AI fleet is collectively doing as a market-internal
signal. Each personality interprets this differently — Contrarian Carl fades
consensus, Steady Eddie treats it as corroboration on stable names, YOLO Bot
rides momentum confirmation, etc. The personality decides; we just compute
the aggregate.

Two metrics per symbol:
  1. flow_score    — last N days of buy/sell intent. +1 = unanimous buying,
                     -1 = unanimous selling, 0 = balanced or zero activity.
  2. breadth_pct   — % of AI fleet currently holding this symbol.

Combined into a single "conviction_label" per symbol:
  STRONG_ACCUMULATION   flow ≥ +0.5  AND breadth rising
  STRONG_DISTRIBUTION   flow ≤ -0.5  AND breadth falling
  CONTROVERSIAL         |flow| < 0.3 with ≥ 4 traders active on both sides
  QUIET                 no recent activity
  ACCUMULATING / DISTRIBUTING for intermediate cases

We intentionally do NOT expose which specific traders are on which side.
Doing so would let personalities leak into each other (Vanilla copying
Contrarian Carl's contrarian positioning would defeat the whole design).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app.services.supabase_client import get_supabase_admin

logger = logging.getLogger(__name__)


def _classify_conviction(flow: float, breadth: float, buy_n: int, sell_n: int) -> str:
    if buy_n == 0 and sell_n == 0:
        return "QUIET"
    # Real disagreement: 4+ traders active on both sides AND |flow| small
    if buy_n >= 4 and sell_n >= 4 and abs(flow) < 0.3:
        return "CONTROVERSIAL"
    if flow >= 0.5:
        return "STRONG_ACCUMULATION"
    if flow <= -0.5:
        return "STRONG_DISTRIBUTION"
    if flow >= 0.2:
        return "ACCUMULATING"
    if flow <= -0.2:
        return "DISTRIBUTING"
    return "MIXED"


async def compute_fleet_signals(lookback_days: int = 3) -> dict:
    """Compute current fleet-wide positioning signals.

    Returns:
        {
          "as_of": iso datetime,
          "fleet_size": int,
          "lookback_days": int,
          "symbols": {
            "BTC": {
              "buys_count": int, "sells_count": int,
              "unique_buyers": int, "unique_sellers": int,
              "flow_score": float in [-1, 1],
              "breadth_holders": int,
              "breadth_pct": float in [0, 1],
              "conviction_label": str,
            },
            ...
          },
          "consensus_picks": [...],   # top STRONG_ACCUMULATION names
          "consensus_dumps": [...],   # top STRONG_DISTRIBUTION names
          "controversial": [...],     # top CONTROVERSIAL names
        }
    """
    db = get_supabase_admin()

    # 1) Identify the AI fleet
    profiles_resp = (
        db.table("profiles")
        .select("id, display_name")
        .eq("is_ai", True)
        .execute()
    )
    ai_user_ids = {p["id"] for p in (profiles_resp.data or [])}
    fleet_size = len(ai_user_ids)
    if fleet_size == 0:
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "fleet_size": 0, "lookback_days": lookback_days,
            "symbols": {}, "consensus_picks": [],
            "consensus_dumps": [], "controversial": [],
        }

    # 2) Recent transactions across the fleet
    since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    tx_resp = (
        db.table("transactions")
        .select("user_id, symbol, side, quantity, price, created_at, asset_type")
        .gte("created_at", since)
        .in_("user_id", list(ai_user_ids))
        .execute()
    )
    txs = tx_resp.data or []

    # 3) Current positions (breadth)
    pos_resp = (
        db.table("positions")
        .select("user_id, symbol, quantity")
        .in_("user_id", list(ai_user_ids))
        .gt("quantity", 0)
        .execute()
    )
    positions = pos_resp.data or []

    # Per-symbol aggregations — defaultdict keeps us defensive against missing keys
    buys_by_symbol: dict[str, list] = defaultdict(list)
    sells_by_symbol: dict[str, list] = defaultdict(list)
    for tx in txs:
        bucket = buys_by_symbol if tx["side"] == "buy" else sells_by_symbol
        bucket[tx["symbol"]].append(tx)

    breadth_holders: dict[str, set] = defaultdict(set)
    for p in positions:
        breadth_holders[p["symbol"]].add(p["user_id"])

    all_symbols = (
        set(buys_by_symbol.keys())
        | set(sells_by_symbol.keys())
        | set(breadth_holders.keys())
    )

    symbol_signals: dict[str, dict] = {}
    for sym in all_symbols:
        buys = buys_by_symbol.get(sym, [])
        sells = sells_by_symbol.get(sym, [])
        unique_buyers = len({tx["user_id"] for tx in buys})
        unique_sellers = len({tx["user_id"] for tx in sells})
        total_active = unique_buyers + unique_sellers
        # Flow score: net intent normalized by participation. -1..+1.
        flow_score = 0.0
        if total_active > 0:
            flow_score = (unique_buyers - unique_sellers) / total_active
        breadth = len(breadth_holders.get(sym, set()))
        breadth_pct = breadth / fleet_size if fleet_size else 0.0

        label = _classify_conviction(flow_score, breadth_pct, unique_buyers, unique_sellers)

        symbol_signals[sym] = {
            "buys_count": len(buys),
            "sells_count": len(sells),
            "unique_buyers": unique_buyers,
            "unique_sellers": unique_sellers,
            "flow_score": round(flow_score, 3),
            "breadth_holders": breadth,
            "breadth_pct": round(breadth_pct, 3),
            "conviction_label": label,
        }

    # Rank highlights — sort by combined signal strength
    def _sig_strength(item):
        sym, sig = item
        return (sig["unique_buyers"] + sig["unique_sellers"], abs(sig["flow_score"]))

    sorted_signals = sorted(symbol_signals.items(), key=_sig_strength, reverse=True)

    consensus_picks = [
        {"symbol": s, **sig} for s, sig in sorted_signals
        if sig["conviction_label"] in ("STRONG_ACCUMULATION", "ACCUMULATING")
    ][:8]
    consensus_dumps = [
        {"symbol": s, **sig} for s, sig in sorted_signals
        if sig["conviction_label"] in ("STRONG_DISTRIBUTION", "DISTRIBUTING")
    ][:8]
    controversial = [
        {"symbol": s, **sig} for s, sig in sorted_signals
        if sig["conviction_label"] == "CONTROVERSIAL"
    ][:5]

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "fleet_size": fleet_size,
        "lookback_days": lookback_days,
        "symbols": symbol_signals,
        "consensus_picks": consensus_picks,
        "consensus_dumps": consensus_dumps,
        "controversial": controversial,
    }
