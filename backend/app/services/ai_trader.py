import asyncio
import json
import logging
import httpx
from datetime import date

logger = logging.getLogger(__name__)

from app.config import get_settings
from app.services.market_brief import get_latest_brief
from app.services.market_data import get_quote, TOP_STOCKS, CRYPTO_MAP, STOCK_SECTORS
from app.services.supabase_client import get_supabase_admin

# ---------------------------------------------------------------------------
# Personality definitions
# ---------------------------------------------------------------------------

PERSONALITIES = {
    "vanilla": {
        "name": "Vanilla",
        "prompt": (
            "You are a balanced portfolio manager. Your goal is risk-adjusted returns. "
            "Use fundamentals (PE ratio, analyst consensus) to find fairly valued stocks. "
            "Use technicals (RSI, SMA trends) for entry/exit timing. "
            "Monitor sector exposure — don't let any one sector exceed 40% of portfolio. "
            "Check the market regime: reduce equity exposure if bearish, increase if bullish. "
            "Keep 10-20% cash reserve for opportunities. Rebalance when positions drift."
        ),
        "risk_params": {
            "stop_loss_pct": -8.0,
            "take_profit_pct": 15.0,
            "max_position_pct": 15.0,
            "max_hold_days": 30,
            "min_sells_with_positions": 1,
        },
    },
    "steady_eddie": {
        "name": "Steady Eddie",
        "prompt": (
            "You are a conservative portfolio manager called Steady Eddie, modeled after "
            "Warren Buffett's value investing philosophy. "
            "BUY criteria: PE ratio below sector average, strong analyst buy consensus, "
            "low beta (<1.0), dividend yield above 1%, RSI under 60. "
            "SELL criteria: RSI above 75 (overbought), position exceeds 15% of portfolio, "
            "analyst consensus shifts to majority sell. "
            "AVOID: stocks with beta >1.5, crypto (limit to <5% of portfolio), "
            "and any asset with annualized volatility >50%. "
            "TARGET: 60% blue-chip stocks, 20% defensive (healthcare/consumer staples), "
            "10% bonds (TLT), 10% cash. Rebalance toward targets each day. "
            "When market regime is BEARISH, shift to 40% stocks / 30% TLT / 30% cash."
        ),
        "risk_params": {
            "stop_loss_pct": -6.0,
            "take_profit_pct": 12.0,
            "max_position_pct": 12.0,
            "max_hold_days": 45,
            "min_sells_with_positions": 1,
        },
    },
    "yolo_bot": {
        "name": "YOLO Bot",
        "prompt": (
            "You are an aggressive momentum trader called YOLO Bot, inspired by "
            "high-frequency trend-following strategies. "
            "BUY criteria: 7d momentum >3%, RSI 50-75 (strong but not exhausted), "
            "price above SMA20, relative volume spike, and analyst consensus bullish. "
            "SELL criteria: RSI >80 (take profits), 7d momentum turns negative, "
            "or price drops below SMA20. Cut losses fast — sell if position drops >8%. "
            "STRATEGY: concentrate in top 3-5 momentum names. Ride winners, dump losers. "
            "Check sector rotation — overweight the leading sector. "
            "When market regime is BULLISH, go 90% invested in highest-momentum assets. "
            "When BEARISH, pivot to short-term crypto plays (24/7 trading advantage) "
            "and reduce stock exposure. Keep <5% cash — YOLO."
        ),
        "risk_params": {
            "stop_loss_pct": -5.0,
            "take_profit_pct": 10.0,
            "max_position_pct": 20.0,
            "max_hold_days": 14,
            "min_sells_with_positions": 1,
        },
    },
    "contrarian_carl": {
        "name": "Contrarian Carl",
        "prompt": (
            "You are a contrarian value investor called Contrarian Carl, inspired by "
            "Michael Burry and mean-reversion strategies. "
            "BUY criteria: RSI <30 (oversold), 7d return <-5% (panic selling), "
            "PE ratio below historical norms, analyst consensus mixed (not all sell). "
            "SELL criteria: RSI >70 (overextended recovery), 30d return >15% (mean reached), "
            "or position hits >20% profit. "
            "KEY SIGNALS: When market regime is BEARISH and safe_haven_demand is HIGH — "
            "this is your prime buying zone. Buy quality stocks that got dragged down. "
            "When market regime is BULLISH and RSI is high everywhere — take profits, "
            "build cash for the next downturn. "
            "TARGET: hold 15-25% cash as dry powder. Diversify across 6-10 positions. "
            "Never chase momentum — let it come to you."
        ),
        "risk_params": {
            "stop_loss_pct": -10.0,
            "take_profit_pct": 20.0,
            "max_position_pct": 15.0,
            "max_hold_days": 60,
            "min_sells_with_positions": 1,
        },
    },
    "crypto_chad": {
        "name": "Crypto Chad",
        "prompt": (
            "You are a crypto-native trader called Crypto Chad, inspired by "
            "on-chain analysts and narrative cycle trading. "
            "ALLOCATION: 60-80% crypto, 10-20% tech stocks (correlated growth), 10-20% cash. "
            "BUY criteria: coins with market_cap_rank <20 (established), distance from ATH >30% "
            "(upside potential), 7d momentum positive, and Bitcoin RSI >40 (not in death spiral). "
            "SELL criteria: ATH distance <5% (near top), RSI >80, or if BTC breaks below SMA50. "
            "STRATEGY: Bitcoin is the tide — when BTC is bullish, altcoins rally harder. "
            "When BTC is bearish, reduce ALL crypto exposure and park in stablecoins or GLD. "
            "Watch the growth_vs_value signal: when GROWTH_LEADING, tech and crypto thrive. "
            "Layer positions: core BTC/ETH (40%), mid-cap alts (30%), small-cap momentum (30%). "
            "Use rate signals: RATES_FALLING = risk-on, good for crypto. RATES_RISING = cautious."
        ),
        "risk_params": {
            "stop_loss_pct": -12.0,
            "take_profit_pct": 25.0,
            "max_position_pct": 20.0,
            "max_hold_days": 21,
            "min_sells_with_positions": 1,
        },
    },
}

# Model configurations
MODELS = {
    "gemini-flash": {
        "label": "Gemini Flash",
        "api": "gemini",
        "model_id": "gemini-2.5-flash",
    },
    "gemini-pro": {
        "label": "Gemini Pro",
        "api": "gemini",
        "model_id": "gemini-2.5-pro",
    },
    "mistral": {
        "label": "Mistral",
        "api": "mistral",
        "model_id": "mistral-large-latest",
    },
    "llama": {
        "label": "Llama",
        "api": "cerebras",
        "model_id": "gpt-oss-120b",
    },
}

# All AI traders: 5 personalities x 4 models = 20
AI_TRADERS = [
    {
        "personality_key": pkey,
        "model_key": mkey,
        "display_name": f"{pinfo['name']} ({minfo['label']})",
        "ai_model": f"{mkey}",
    }
    for pkey, pinfo in PERSONALITIES.items()
    for mkey, minfo in MODELS.items()
]

# Trade decision prompt shared across all AIs
TRADE_SYSTEM = """\
You are a professional portfolio manager running a paper trading portfolio.

## Data You Will Receive
1. Your personality/strategy description with specific BUY/SELL criteria
2. Market regime analysis (bullish/bearish, growth vs value rotation, rate direction, safe haven demand)
3. Sector performance breakdown (which sectors are leading/lagging today)
4. Stock fundamentals (PE ratio, beta, dividend yield, 52-week range, market cap)
5. Technical indicators (RSI, SMA 20/50 trends, 7d/30d momentum, volatility)
6. Analyst consensus (buy/hold/sell counts from Wall Street)
7. Earnings calendar (upcoming catalysts — can cause 5-20% swings)
8. Crypto market data (rank, market cap, volume, distance from all-time high)
9. News headlines with summaries (market-moving events)
10. Your current portfolio with sector exposure, risk metrics, and RISK ALERTS
11. Your recent trading history and what's working/failing

## Professional Decision Framework
Follow this checklist for EVERY trade decision:

1. CHECK RISK ALERTS FIRST: If the Portfolio Risk Analysis contains 🚨 MANDATORY RISK ACTIONS, \
you MUST include sells to address them. Ignoring risk alerts is a critical failure. \
Stop-losses protect capital. Take-profits lock in gains. Both are non-negotiable.
2. CHECK MACRO: What is the market regime? Adjust overall exposure accordingly.
3. CHECK SECTOR ROTATION: Which sectors are leading? Favor leaders, reduce laggards.
4. EVALUATE ENTRY/EXIT: Use your personality's specific BUY/SELL criteria.
   - For buys: Is the valuation reasonable (PE, analyst view)? Is the timing right (RSI, SMA)?
   - For sells: Has the thesis played out? Has it hit your exit criteria?
5. POSITION SIZING: Scale position size by conviction AND volatility.
   - High volatility (>40% annualized) → smaller position (2-5% of portfolio)
   - Low volatility (<25%) → larger position (5-10% of portfolio)
   - Never let one position exceed 15% of total portfolio value.
6. RISK MANAGEMENT: Check your portfolio's sector concentration and adjust if needed.
7. LEARN FROM HISTORY: Review what worked and what didn't in your recent trades.

## Sell Discipline (CRITICAL)
Professional traders sell as much as they buy. You MUST sell when:
- A position hits your stop-loss threshold (cut losses, preserve capital)
- A position hits your take-profit threshold (lock in gains before they evaporate)
- A position exceeds your max weight % (trim to maintain diversification)
- A position has been stale too long with minimal return (redeploy capital)
- Market regime shifts against your holdings (reduce exposure)

If you have 3+ positions, at least 1 of your trades today MUST be a sell. \
Portfolios that only buy become bloated and unmanageable. Active management means \
actively trimming, rotating, and rebalancing — not just accumulating.

## Rules
- You can buy or sell stocks and crypto from the supported list only.
- You cannot spend more cash than you have.
- You cannot sell more shares/coins than you own.
- Each trade needs: symbol, asset_type ("stock" or "crypto"), side ("buy" or "sell"), quantity (number).
- For stocks, quantity must be a whole number >= 1.
- For crypto, quantity can be a decimal (minimum 0.001).
- Crypto markets are open 24/7. Stock markets are Mon-Fri, but you can place trades anytime.
- You MUST make at least 1 trade every day. This is paper trading — there is zero risk. Not trading is the worst outcome.
- Maximum 8 trades per day (enough to rebalance: sell overweight positions + buy new ones).
- If you have no positions yet, build an initial portfolio of 4-6 assets matching your strategy.

Respond ONLY with valid JSON in this exact format, no other text:
{"trades": [{"symbol": "AAPL", "asset_type": "stock", "side": "buy", "quantity": 10, "reasoning": "Brief 1-2 sentence explanation of WHY this trade, citing specific data (e.g. RSI, PE, regime, sector rotation)."}]}
"""

# Session-specific instructions appended to the system prompt
SESSION_CONTEXTS = {
    "morning": (
        "\n\n## Session: Pre-Market (Morning)\n"
        "Focus on POSITIONING for the day ahead. Review overnight news, pre-market movers, "
        "and the market regime. This is the best time to:\n"
        "- Build new positions based on overnight developments\n"
        "- Set up portfolio for expected sector rotation\n"
        "- React to earnings releases or macro news from overnight\n"
        "Maximum 4 trades this session. Save capacity for midday adjustments."
    ),
    "midday": (
        "\n\n## Session: Midday Review\n"
        "Focus on ADJUSTMENTS based on how the morning played out. This is the time to:\n"
        "- Take profits on morning positions that moved in your favor\n"
        "- Cut losses on positions moving against you\n"
        "- React to any midday news or trend reversals\n"
        "- Rebalance if sectors shifted significantly\n"
        "Maximum 3 trades this session. Be selective — only act on clear signals."
    ),
    "close": (
        "\n\n## Session: Market Close\n"
        "Focus on END-OF-DAY positioning and risk management. This is the time to:\n"
        "- Lock in profits on day's winners\n"
        "- Reduce exposure if market regime turned negative during the day\n"
        "- Position for overnight/next-day catalysts (earnings, Fed, etc.)\n"
        "- Ensure portfolio risk levels match your strategy\n"
        "Maximum 4 trades this session."
    ),
}


# ---------------------------------------------------------------------------
# Account setup (one-time)
# ---------------------------------------------------------------------------

async def setup_ai_accounts() -> list[dict]:
    """Create AI trader profiles in the database. Idempotent."""
    db = get_supabase_admin()
    created = []

    for trader in AI_TRADERS:
        display_name = trader["display_name"]

        # Check if this AI trader already exists
        existing = (
            db.table("profiles")
            .select("id")
            .eq("display_name", display_name)
            .eq("is_ai", True)
            .execute()
        )
        if existing.data:
            created.append({"display_name": display_name, "status": "exists"})
            continue

        # Create auth user (AI traders get random unusable passwords)
        email = f"ai-{trader['personality_key']}-{trader['model_key']}@papertrade.bot"
        try:
            user_resp = db.auth.admin.create_user(
                {
                    "email": email,
                    "password": f"AI-{trader['personality_key']}-{trader['model_key']}-noLogin!",
                    "email_confirm": True,
                    "user_metadata": {"display_name": display_name},
                }
            )
            user_id = user_resp.user.id

            # The trigger should create the profile, but update it for AI fields
            db.table("profiles").update(
                {
                    "display_name": display_name,
                    "is_ai": True,
                    "ai_model": trader["ai_model"],
                }
            ).eq("id", user_id).execute()

            created.append({"display_name": display_name, "status": "created", "id": user_id})
        except Exception as e:
            created.append({"display_name": display_name, "status": f"error: {e}"})

    return created


# ---------------------------------------------------------------------------
# Portfolio helper
# ---------------------------------------------------------------------------

async def _get_ai_portfolio(db, user_id: str) -> dict:
    """Get an AI trader's cash and positions for the prompt."""
    profile = db.table("profiles").select("cash_balance").eq("id", user_id).single().execute()
    cash = float(profile.data["cash_balance"])

    positions_resp = (
        db.table("positions")
        .select("symbol, asset_type, quantity, avg_cost_basis")
        .eq("user_id", user_id)
        .gt("quantity", 0)
        .execute()
    )

    # Get first buy date per symbol to compute hold duration
    first_buys: dict[str, str] = {}
    if positions_resp.data:
        symbols = [p["symbol"] for p in positions_resp.data]
        tx_resp = (
            db.table("transactions")
            .select("symbol, created_at")
            .eq("user_id", user_id)
            .eq("side", "buy")
            .in_("symbol", symbols)
            .order("created_at", desc=False)
            .execute()
        )
        for tx in tx_resp.data:
            if tx["symbol"] not in first_buys:
                first_buys[tx["symbol"]] = tx["created_at"][:10]

    today = date.today()
    positions = []
    for p in positions_resp.data:
        quote = await get_quote(p["symbol"], p["asset_type"])
        current_price = quote["price"] if quote else float(p["avg_cost_basis"])
        qty = float(p["quantity"])

        # Compute hold days from first buy
        hold_days = 0
        if p["symbol"] in first_buys:
            try:
                first_date = date.fromisoformat(first_buys[p["symbol"]])
                hold_days = (today - first_date).days
            except ValueError:
                pass

        positions.append({
            "symbol": p["symbol"],
            "asset_type": p["asset_type"],
            "quantity": qty,
            "avg_cost": float(p["avg_cost_basis"]),
            "current_price": current_price,
            "market_value": round(qty * current_price, 2),
            "hold_days": hold_days,
        })

    return {"cash": cash, "positions": positions}


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------

async def _call_gemini(model_id: str, system: str, user_msg: str, api_key: str) -> str:
    """Call Google Gemini API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": user_msg}]}],
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 2048,
        },
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            url,
            params={"key": api_key},
            json=payload,
        )
        if resp.status_code != 200:
            raise Exception(f"Gemini {model_id} error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        # Extract text from response — handle thinking models that may
        # return multiple parts (thought + response)
        candidate = data["candidates"][0]["content"]
        parts = candidate.get("parts", [])
        # Find the last text part (thinking models put thought first, answer last)
        for part in reversed(parts):
            if "text" in part:
                return part["text"]
        # If no text parts, dump what we got for debugging
        raise Exception(f"Gemini {model_id}: no text parts. Keys: {list(candidate.keys())}. Parts: {str(parts)[:200]}")


async def _call_mistral(model_id: str, system: str, user_msg: str, api_key: str) -> str:
    """Call Mistral La Plateforme API (OpenAI-compatible)."""
    url = "https://api.mistral.ai/v1/chat/completions"
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.7,
        "max_tokens": 2048,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        if resp.status_code != 200:
            raise Exception(f"Mistral {model_id} error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def _call_cerebras(model_id: str, system: str, user_msg: str, api_key: str) -> str:
    """Call Cerebras API (OpenAI-compatible)."""
    url = "https://api.cerebras.ai/v1/chat/completions"
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.7,
        "max_tokens": 2048,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        if resp.status_code != 200:
            raise Exception(f"Cerebras {model_id} error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _get_ai_trade_history(db, user_id: str, limit: int = 15) -> list[dict]:
    """Get recent trades for an AI trader to include in the prompt as memory."""
    resp = (
        db.table("transactions")
        .select("symbol, asset_type, side, quantity, price, total, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data if resp.data else []


def _format_trade_memory(trades: list[dict], positions: list[dict]) -> str:
    """Format recent trades and P&L into a readable memory section."""
    if not trades:
        return "No trading history yet. This is your first day — build an initial portfolio."

    lines = ["Recent trades (newest first):"]
    for t in trades[:10]:
        day = t["created_at"][:10] if t.get("created_at") else "?"
        lines.append(
            f"  {day}: {t['side'].upper()} {t['quantity']} {t['symbol']} @ ${t['price']:,.2f}"
        )

    # Summarize position P&L with actionable context
    if positions:
        winners = []
        losers = []
        for p in positions:
            pnl_pct = ((p["current_price"] / p["avg_cost"]) - 1) * 100 if p["avg_cost"] > 0 else 0
            entry = (p["symbol"], pnl_pct, p["avg_cost"], p["current_price"])
            if pnl_pct >= 0:
                winners.append(entry)
            else:
                losers.append(entry)

        if winners:
            winners.sort(key=lambda x: x[1], reverse=True)
            lines.append("\n✓ Winners (consider taking partial profits on big gainers):")
            for sym, pnl, avg, cur in winners:
                lines.append(f"  {sym}: +{pnl:.1f}% (avg ${avg:,.2f} → ${cur:,.2f})")

        if losers:
            losers.sort(key=lambda x: x[1])
            lines.append("\n✗ Losers (consider cutting losses >10% or averaging down if thesis intact):")
            for sym, pnl, avg, cur in losers:
                lines.append(f"  {sym}: {pnl:.1f}% (avg ${avg:,.2f} → ${cur:,.2f})")

    return "\n".join(lines)


def _format_enriched_brief(brief: dict) -> str:
    """Format the enriched market brief sections for the AI prompt."""
    sections = []

    # Market Regime (new — macro context)
    regime = brief.get("market_regime", {})
    if regime:
        regime_lines = []
        if "market_trend" in regime:
            spy_rsi = regime.get('spy_rsi')
            spy_7d = regime.get('spy_7d')
            spy_30d = regime.get('spy_30d')
            parts = [f"Overall Market: {regime['market_trend']}"]
            detail = []
            if spy_rsi is not None:
                detail.append(f"SPY RSI={spy_rsi}")
            if spy_7d is not None:
                detail.append(f"7d={spy_7d:+.1f}%")
            if spy_30d is not None:
                detail.append(f"30d={spy_30d:+.1f}%")
            if detail:
                parts[0] += f" ({', '.join(detail)})"
            regime_lines.append(f"  {parts[0]}")
        if "growth_vs_value" in regime:
            regime_lines.append(f"  Rotation: {regime['growth_vs_value']} (QQQ-SPY spread: {regime.get('qqq_spy_spread_7d', 0):+.1f}%)")
        if "rate_signal" in regime:
            regime_lines.append(f"  Interest Rates: {regime['rate_signal']} (TLT 7d: {regime.get('tlt_7d', 0):+.1f}%)")
        if "safe_haven_demand" in regime:
            regime_lines.append(f"  Safe Haven Demand: {regime['safe_haven_demand']} (GLD 7d: {regime.get('gld_7d', 0):+.1f}%)")
        if "small_cap_signal" in regime:
            regime_lines.append(f"  Small Cap Health: {regime['small_cap_signal']} (IWM 7d: {regime.get('iwm_7d', 0):+.1f}%)")
        if regime_lines:
            sections.append("### MARKET REGIME (read this first — it sets the context)\n" + "\n".join(regime_lines))

    # Sector Performance (new — rotation signals)
    sector_perf = brief.get("sector_performance", {})
    if sector_perf:
        sorted_sectors = sorted(sector_perf.items(), key=lambda x: x[1]["avg_change_pct"], reverse=True)
        sector_lines = []
        for sector, data in sorted_sectors:
            sector_lines.append(
                f"  {sector}: {data['avg_change_pct']:+.2f}% avg ({data['stocks_up']} up / {data['stocks_down']} down)"
            )
        sections.append("### SECTOR PERFORMANCE (today's rotation)\n" + "\n".join(sector_lines))

    # Fundamentals for stocks (enhanced with volatility and sector)
    fundamentals = brief.get("fundamentals", {})
    volatility = brief.get("stock_volatility", {})
    if fundamentals:
        fund_lines = []
        for sym, f in list(fundamentals.items())[:20]:
            parts = []
            sector = STOCK_SECTORS.get(sym, "?")
            parts.append(f"[{sector}]")
            if f.get("pe_ratio"):
                parts.append(f"PE {f['pe_ratio']:.1f}")
            if f.get("beta"):
                parts.append(f"Beta {f['beta']:.2f}")
            if f.get("dividend_yield"):
                parts.append(f"Div {f['dividend_yield']:.1f}%")
            if f.get("52w_high") and f.get("52w_low"):
                parts.append(f"52w ${f['52w_low']:.0f}-${f['52w_high']:.0f}")
            if f.get("market_cap_m"):
                mcap = f["market_cap_m"]
                if mcap > 1000:
                    parts.append(f"MCap ${mcap/1000:.0f}B")
                else:
                    parts.append(f"MCap ${mcap:.0f}M")
            vol = volatility.get(sym)
            if vol:
                vol_label = "HIGH" if vol > 40 else "LOW" if vol < 20 else ""
                parts.append(f"Vol {vol}%{' ' + vol_label if vol_label else ''}")
            if len(parts) > 1:  # more than just sector
                fund_lines.append(f"  {sym}: {', '.join(parts)}")
        if fund_lines:
            sections.append("### Stock Fundamentals & Risk\n" + "\n".join(fund_lines))

    # Analyst recommendations
    recs = brief.get("analyst_recommendations", {})
    if recs:
        rec_lines = []
        for sym, r in list(recs.items())[:20]:
            total = r["buy"] + r["hold"] + r["sell"]
            if total > 0:
                buy_pct = round(r["buy"] / total * 100)
                signal = "STRONG BUY" if buy_pct > 70 else "MOSTLY BUY" if buy_pct > 50 else "MIXED" if r["hold"] > r["sell"] else "BEARISH"
                rec_lines.append(
                    f"  {sym}: {r['buy']} Buy / {r['hold']} Hold / {r['sell']} Sell → {signal}"
                )
        if rec_lines:
            sections.append("### Analyst Consensus\n" + "\n".join(rec_lines))

    # Earnings calendar (enhanced with EPS estimates)
    earnings = brief.get("earnings_calendar", [])
    if earnings:
        earn_lines = []
        for e in earnings[:10]:
            eps_str = f" (est EPS ${e['estimate_eps']:.2f})" if e.get("estimate_eps") else ""
            earn_lines.append(f"  ⚠ {e['symbol']} reports {e['date']}{eps_str} — expect volatility")
        sections.append("### Upcoming Earnings (next 7 days)\n" + "\n".join(earn_lines))

    # Technical indicators (enhanced with volume and more context)
    technicals = brief.get("stock_technicals", {})
    if technicals:
        tech_lines = []
        for sym, t in list(technicals.items())[:20]:
            parts = []
            if "rsi_14" in t:
                rsi = t["rsi_14"]
                label = "⚠ OVERBOUGHT" if rsi > 70 else "✓ OVERSOLD" if rsi < 30 else ""
                parts.append(f"RSI {rsi}{' ' + label if label else ''}")
            if "vs_sma_20" in t:
                direction = "above" if t["vs_sma_20"] > 0 else "below"
                parts.append(f"{direction} SMA20 by {abs(t['vs_sma_20']):.1f}%")
            if "vs_sma_50" in t:
                direction = "above" if t["vs_sma_50"] > 0 else "below"
                parts.append(f"{direction} SMA50 by {abs(t['vs_sma_50']):.1f}%")
            if "7d_return" in t:
                parts.append(f"7d {t['7d_return']:+.1f}%")
            if "30d_return" in t:
                parts.append(f"30d {t['30d_return']:+.1f}%")
            if "relative_volume" in t:
                rv = t["relative_volume"]
                vol_label = "⚡ HIGH VOLUME" if rv > 1.5 else "LOW VOLUME" if rv < 0.5 else ""
                parts.append(f"RelVol {rv:.1f}x{' ' + vol_label if vol_label else ''}")
            if parts:
                tech_lines.append(f"  {sym}: {', '.join(parts)}")
        if tech_lines:
            sections.append("### Stock Technical Indicators\n" + "\n".join(tech_lines))

    # Crypto technicals (NEW — RSI, SMA, momentum for crypto)
    crypto_tech = brief.get("crypto_technicals", {})
    if crypto_tech:
        ctech_lines = []
        for sym, t in list(crypto_tech.items())[:15]:
            parts = []
            if "rsi_14" in t:
                rsi = t["rsi_14"]
                label = "⚠ OVERBOUGHT" if rsi > 70 else "✓ OVERSOLD" if rsi < 30 else ""
                parts.append(f"RSI {rsi}{' ' + label if label else ''}")
            if "vs_sma_20" in t:
                direction = "above" if t["vs_sma_20"] > 0 else "below"
                parts.append(f"{direction} SMA20 by {abs(t['vs_sma_20']):.1f}%")
            if "vs_sma_50" in t:
                direction = "above" if t["vs_sma_50"] > 0 else "below"
                parts.append(f"{direction} SMA50 by {abs(t['vs_sma_50']):.1f}%")
            if "7d_return" in t:
                parts.append(f"7d {t['7d_return']:+.1f}%")
            if "30d_return" in t:
                parts.append(f"30d {t['30d_return']:+.1f}%")
            if parts:
                ctech_lines.append(f"  {sym}: {', '.join(parts)}")
        if ctech_lines:
            sections.append("### Crypto Technical Indicators\n" + "\n".join(ctech_lines))

    # Crypto market data (fundamentals)
    crypto_data = brief.get("crypto_market_data", {})
    if crypto_data:
        crypto_lines = []
        for sym, c in list(crypto_data.items())[:15]:
            parts = []
            if c.get("market_cap_rank"):
                parts.append(f"Rank #{c['market_cap_rank']}")
            if c.get("market_cap_b"):
                parts.append(f"MCap ${c['market_cap_b']}B")
            if c.get("volume_24h_m"):
                parts.append(f"24h Vol ${c['volume_24h_m']}M")
            if c.get("ath_drop_pct") is not None:
                pct = c["ath_drop_pct"]
                label = "NEAR ATH" if pct < 10 else "BIG DISCOUNT" if pct > 50 else ""
                parts.append(f"{pct}% below ATH{' — ' + label if label else ''}")
            if parts:
                crypto_lines.append(f"  {sym}: {', '.join(parts)}")
        if crypto_lines:
            sections.append("### Crypto Market Data\n" + "\n".join(crypto_lines))

    # Company-specific news for top movers (NEW)
    company_news = brief.get("company_news", {})
    if company_news:
        news_lines = []
        for sym, articles in company_news.items():
            for a in articles:
                summary = f" — {a['summary']}" if a.get("summary") else ""
                news_lines.append(f"  {sym}: {a['headline']}{summary}")
        if news_lines:
            sections.append("### Company News (top movers this week)\n" + "\n".join(news_lines))

    # Day-over-day context (NEW — regime/sector shifts from yesterday)
    dod = brief.get("day_over_day", {})
    if dod:
        dod_lines = []
        if "regime_shift" in dod:
            dod_lines.append(f"  Market regime: {dod['regime_shift']}")
        if "spy_momentum_change" in dod:
            change = dod["spy_momentum_change"]
            direction = "accelerating" if change > 0 else "decelerating"
            dod_lines.append(f"  SPY momentum {direction} ({change:+.2f}% shift)")
        if "sector_shifts" in dod:
            for shift in dod["sector_shifts"]:
                dod_lines.append(f"  {shift}")
        if dod_lines:
            sections.append("### DAY-OVER-DAY CHANGES (vs yesterday)\n" + "\n".join(dod_lines))

    return "\n\n".join(sections) if sections else ""


def _compute_portfolio_risk(portfolio: dict, personality_key: str = None) -> str:
    """Compute portfolio risk metrics: sector exposure, concentration, unrealized P&L.
    This gives AIs the self-awareness to manage risk like a professional.
    When personality_key is provided, includes risk rule alerts."""
    positions = portfolio.get("positions", [])
    cash = portfolio.get("cash", 0)

    if not positions:
        return "No positions — you need to build a portfolio. Diversify across sectors."

    total_value = cash + sum(p["market_value"] for p in positions)
    if total_value == 0:
        return "Portfolio value is zero."

    # Get risk params for this personality
    risk_params = None
    if personality_key and personality_key in PERSONALITIES:
        risk_params = PERSONALITIES[personality_key].get("risk_params", {})

    lines = []
    sell_alerts = []

    # Cash allocation
    cash_pct = round(cash / total_value * 100, 1)
    lines.append(f"Cash allocation: {cash_pct}% (${cash:,.2f})")

    # Position concentration + risk alerts
    position_pcts = []
    for p in sorted(positions, key=lambda x: x["market_value"], reverse=True):
        pct = round(p["market_value"] / total_value * 100, 1)
        pnl_pct = ((p["current_price"] / p["avg_cost"]) - 1) * 100 if p["avg_cost"] > 0 else 0
        hold_days = p.get("hold_days", 0)
        position_pcts.append((p["symbol"], pct, pnl_pct, p["asset_type"], hold_days))

    lines.append("\nPosition weights:")
    for sym, pct, pnl, atype, hold_days in position_pcts:
        flags = []
        if pct > 15:
            flags.append("CONCENTRATED")
        if risk_params:
            stop_loss = risk_params.get("stop_loss_pct", -10)
            take_profit = risk_params.get("take_profit_pct", 20)
            max_pos = risk_params.get("max_position_pct", 15)
            max_days = risk_params.get("max_hold_days", 30)

            if pnl <= stop_loss:
                flags.append("STOP-LOSS HIT")
                sell_alerts.append(
                    f"🔴 SELL {sym}: down {pnl:.1f}% (stop-loss trigger at {stop_loss}%). Cut this loss NOW."
                )
            elif pnl >= take_profit:
                flags.append("TAKE-PROFIT HIT")
                sell_alerts.append(
                    f"🟢 SELL {sym}: up {pnl:.1f}% (take-profit trigger at +{take_profit}%). Lock in this gain."
                )
            if pct > max_pos:
                flags.append("OVERWEIGHT")
                sell_alerts.append(
                    f"⚠ TRIM {sym}: {pct}% of portfolio (max allowed: {max_pos}%). Reduce position size."
                )
            if hold_days > max_days and abs(pnl) < 3:
                flags.append("STALE")
                sell_alerts.append(
                    f"⏰ REVIEW {sym}: held {hold_days} days with only {pnl:+.1f}% return. "
                    f"Consider selling to free up capital (max hold: {max_days} days)."
                )

        flag_str = f" ⚠ {', '.join(flags)}" if flags else ""
        age_str = f", held {hold_days}d" if hold_days > 0 else ""
        lines.append(f"  {sym} ({atype}): {pct}% of portfolio, P&L {pnl:+.1f}%{age_str}{flag_str}")

    # Sector exposure
    sector_exposure: dict[str, float] = {}
    crypto_exposure = 0.0
    for p in positions:
        if p["asset_type"] == "crypto":
            crypto_exposure += p["market_value"]
        else:
            sector = STOCK_SECTORS.get(p["symbol"], "Other")
            sector_exposure[sector] = sector_exposure.get(sector, 0) + p["market_value"]

    lines.append("\nSector exposure:")
    all_sectors = {**sector_exposure}
    if crypto_exposure > 0:
        all_sectors["Crypto"] = crypto_exposure
    for sector, value in sorted(all_sectors.items(), key=lambda x: x[1], reverse=True):
        pct = round(value / total_value * 100, 1)
        flag = " ⚠ OVERWEIGHT" if pct > 40 else ""
        lines.append(f"  {sector}: {pct}%{flag}")

    # Overall P&L
    total_invested_cost = sum(p["avg_cost"] * p["quantity"] for p in positions)
    total_market_value = sum(p["market_value"] for p in positions)
    if total_invested_cost > 0:
        overall_pnl = ((total_market_value / total_invested_cost) - 1) * 100
        lines.append(f"\nOverall unrealized P&L: {overall_pnl:+.1f}%")

    # Sell alerts section
    if sell_alerts:
        lines.append("\n" + "=" * 50)
        lines.append("🚨 MANDATORY RISK ACTIONS (you MUST address these):")
        lines.append("=" * 50)
        for alert in sell_alerts:
            lines.append(alert)
        lines.append(
            f"\nYou have {len(sell_alerts)} risk alert(s). "
            "Your trades MUST include sells to address these alerts. "
            "Ignoring risk alerts violates your trading mandate."
        )

    return "\n".join(lines)


def _format_stocks_by_sector() -> str:
    """Format supported stocks grouped by sector for the AI prompt."""
    by_sector: dict[str, list[str]] = {}
    for sym, name in TOP_STOCKS.items():
        sector = STOCK_SECTORS.get(sym, "Other")
        by_sector.setdefault(sector, []).append(f"{sym} ({name})")
    lines = []
    for sector in sorted(by_sector.keys()):
        lines.append(f"  {sector}: {', '.join(by_sector[sector])}")
    return "\n".join(lines)


async def _get_ai_trades(personality_key: str, model_key: str, brief: dict, portfolio: dict, trade_memory: str = "", session: str = "close") -> list[dict]:
    """Ask an AI model for its trading decisions."""
    settings = get_settings()
    personality = PERSONALITIES[personality_key]
    model_cfg = MODELS[model_key]

    # Build the user message
    supported_crypto = [{"symbol": s, "name": c["name"]} for s, c in CRYPTO_MAP.items()]

    enriched_sections = _format_enriched_brief(brief)

    # Format news with summaries (not just headlines)
    news_items = brief.get("news", [])[:10]
    news_text = "\n".join(
        f"  • {n['headline']}\n    {n.get('summary', '')[:200]}"
        if n.get("summary")
        else f"  • {n['headline']}"
        for n in news_items
    ) if news_items else "  No news available."

    # Portfolio risk analysis (with personality-specific risk alerts)
    risk_analysis = _compute_portfolio_risk(portfolio, personality_key)

    # Format risk rules for this personality
    risk_params = personality.get("risk_params", {})
    risk_rules_text = ""
    if risk_params:
        risk_rules_text = f"""
## Your Risk Rules (ENFORCED)
- Stop-loss: sell any position down {risk_params.get('stop_loss_pct', -10)}% or more
- Take-profit: sell any position up +{risk_params.get('take_profit_pct', 20)}% or more
- Max position size: {risk_params.get('max_position_pct', 15)}% of portfolio
- Max hold period: {risk_params.get('max_hold_days', 30)} days for stale positions (<3% move)
- If you have 3+ positions, include at least 1 sell in your trades today
"""

    user_msg = f"""## Your Strategy
{personality['prompt']}
{risk_rules_text}
## Today's Market Brief ({brief.get('date', 'today')})

{enriched_sections}

### Top Gainers
{json.dumps(brief.get('top_gainers', []), indent=2)}

### Top Losers
{json.dumps(brief.get('top_losers', []), indent=2)}

### Market News (headlines + context)
{news_text}

### Supported Stocks (by sector)
{_format_stocks_by_sector()}

### Supported Crypto
{json.dumps(supported_crypto, indent=2)}

## Your Current Portfolio
Cash: ${portfolio['cash']:,.2f}
Total Value: ${portfolio['cash'] + sum(p['market_value'] for p in portfolio['positions']):,.2f}
Positions:
{json.dumps(portfolio['positions'], indent=2) if portfolio['positions'] else 'None — you have no positions yet.'}

## Portfolio Risk Analysis
{risk_analysis}

## Your Trading Memory
{trade_memory}

Based on ALL the data above, what trades do you want to make today? \
Address any MANDATORY RISK ACTIONS first, then follow your strategy's BUY/SELL criteria."""

    # Build system prompt with optional session context
    system_prompt = TRADE_SYSTEM
    if session in SESSION_CONTEXTS:
        system_prompt += SESSION_CONTEXTS[session]

    # Call the right API
    api = model_cfg["api"]
    if api == "gemini":
        if not settings.gemini_api_key:
            raise Exception("GEMINI_API_KEY not configured")
        raw = await _call_gemini(model_cfg["model_id"], system_prompt, user_msg, settings.gemini_api_key)
    elif api == "mistral":
        if not settings.mistral_api_key:
            raise Exception("MISTRAL_API_KEY not configured")
        raw = await _call_mistral(model_cfg["model_id"], system_prompt, user_msg, settings.mistral_api_key)
    elif api == "cerebras":
        if not settings.cerebras_api_key:
            raise Exception("CEREBRAS_API_KEY not configured")
        raw = await _call_cerebras(model_cfg["model_id"], system_prompt, user_msg, settings.cerebras_api_key)
    else:
        raise Exception(f"Unknown API: {api}")

    # Parse response — extract JSON from text that may contain markdown fences
    try:
        text = raw.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            # Remove ```json or ``` prefix and trailing ```
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        parsed = json.loads(text)
        trades = parsed.get("trades", [])
        if not isinstance(trades, list):
            return []
        return trades[:8]  # Max 8 trades (allows rebalancing)
    except json.JSONDecodeError:
        return []


# ---------------------------------------------------------------------------
# Trade execution (bypasses market hours for AI)
# ---------------------------------------------------------------------------

async def _execute_ai_trade(user_id: str, trade: dict) -> dict | None:
    """Execute a single trade for an AI trader. Returns result or None on failure."""
    symbol = trade.get("symbol", "").upper()
    asset_type = trade.get("asset_type", "")
    side = trade.get("side", "")
    quantity = trade.get("quantity", 0)
    reasoning = trade.get("reasoning", "")

    # Validate basics
    if asset_type not in ("stock", "crypto"):
        return None
    if side not in ("buy", "sell"):
        return None
    if not quantity or quantity <= 0:
        return None
    if asset_type == "stock" and symbol not in TOP_STOCKS:
        return None
    if asset_type == "crypto" and symbol not in CRYPTO_MAP:
        return None
    if asset_type == "stock":
        quantity = int(quantity)  # Whole shares only

    # Get current price
    quote = await get_quote(symbol, asset_type)
    if not quote:
        return None

    price = quote["price"]
    total = round(price * quantity, 8)
    db = get_supabase_admin()

    # Get profile
    profile = db.table("profiles").select("cash_balance").eq("id", user_id).single().execute()
    cash = float(profile.data["cash_balance"])

    try:
        if side == "buy":
            if total > cash:
                return None  # Can't afford it
            # Update cash
            db.table("profiles").update({"cash_balance": cash - total}).eq("id", user_id).execute()
            # Update position
            pos_resp = db.table("positions").select("*").eq("user_id", user_id).eq("symbol", symbol).execute()
            if pos_resp.data:
                existing = pos_resp.data[0]
                old_qty = float(existing["quantity"])
                old_cost = float(existing["avg_cost_basis"])
                new_qty = old_qty + quantity
                new_avg = ((old_qty * old_cost) + (quantity * price)) / new_qty
                db.table("positions").update(
                    {"quantity": new_qty, "avg_cost_basis": round(new_avg, 8)}
                ).eq("id", existing["id"]).execute()
            else:
                db.table("positions").insert({
                    "user_id": user_id,
                    "symbol": symbol,
                    "asset_type": asset_type,
                    "quantity": quantity,
                    "avg_cost_basis": price,
                }).execute()

        elif side == "sell":
            pos_resp = db.table("positions").select("*").eq("user_id", user_id).eq("symbol", symbol).execute()
            if not pos_resp.data:
                return None
            existing = pos_resp.data[0]
            held = float(existing["quantity"])
            if quantity > held:
                return None  # Not enough to sell
            db.table("profiles").update({"cash_balance": cash + total}).eq("id", user_id).execute()
            new_qty = held - quantity
            if new_qty == 0:
                db.table("positions").delete().eq("id", existing["id"]).execute()
            else:
                db.table("positions").update({"quantity": new_qty}).eq("id", existing["id"]).execute()

        # Record transaction (reasoning column is nullable — works even before migration)
        tx_data = {
            "user_id": user_id,
            "symbol": symbol,
            "asset_type": asset_type,
            "side": side,
            "quantity": quantity,
            "price": price,
            "total": total,
        }
        if reasoning:
            tx_data["reasoning"] = reasoning[:500]  # Cap at 500 chars
        tx = db.table("transactions").insert(tx_data).execute()

        return tx.data[0] if tx.data else None

    except Exception:
        return None


# ---------------------------------------------------------------------------
# Daily AI trading run
# ---------------------------------------------------------------------------

# Provider-specific rate limit delays (seconds between calls).
# These are tuned for free tier limits:
#   Gemini Pro: 2 RPM → 35s   |  Gemini Flash: 15 RPM → 5s
#   Mistral: generous → 3s    |  Cerebras: generous → 3s
PROVIDER_DELAYS = {
    "gemini-pro": 35,
    "gemini-flash": 5,
    "mistral": 3,
    "llama": 3,
}


async def _run_trader(
    db, brief: dict, profile: dict, session: str = "close"
) -> dict:
    """Run a single AI trader: get portfolio, ask LLM, execute trades."""
    user_id = profile["id"]
    display_name = profile["display_name"]
    model_key = profile.get("ai_model", "")

    # Determine personality from display name
    personality_key = None
    for pkey, pinfo in PERSONALITIES.items():
        if pinfo["name"] in display_name:
            personality_key = pkey
            break

    if not personality_key or model_key not in MODELS:
        return {
            "trader": display_name,
            "status": "skipped",
            "reason": "unknown personality or model",
        }

    try:
        # Get portfolio state
        portfolio = await _get_ai_portfolio(db, user_id)

        # Build trading memory from recent history
        recent_trades = _get_ai_trade_history(db, user_id, limit=15)
        trade_memory = _format_trade_memory(recent_trades, portfolio["positions"])

        # Ask AI for trades
        trades = await _get_ai_trades(personality_key, model_key, brief, portfolio, trade_memory, session=session)

        # Execute trades
        executed = []
        for trade in trades:
            result = await _execute_ai_trade(user_id, trade)
            if result:
                entry = {
                    "symbol": trade["symbol"],
                    "side": trade["side"],
                    "quantity": trade["quantity"],
                }
                if trade.get("reasoning"):
                    entry["reasoning"] = trade["reasoning"]
                executed.append(entry)

        return {
            "trader": display_name,
            "status": "ok",
            "trades_proposed": len(trades),
            "trades_executed": len(executed),
            "trades": executed,
        }

    except Exception as e:
        logger.error("Trader %s failed: %s", display_name, e)
        return {
            "trader": display_name,
            "status": "error",
            "error": str(e)[:200],
        }


async def _run_provider_batch(
    db, brief: dict, profiles: list[dict], delay: int, session: str = "close"
) -> list[dict]:
    """Run a batch of traders that share the same API provider, sequentially
    with the appropriate delay between calls."""
    results = []
    for i, profile in enumerate(profiles):
        result = await _run_trader(db, brief, profile, session=session)
        results.append(result)
        # Delay between calls (skip after last one)
        if i < len(profiles) - 1:
            await asyncio.sleep(delay)
    return results


async def run_ai_trading(session: str = "close") -> dict:
    """Run all AI traders for today, grouped by API provider for optimal speed.

    Old approach: 20 traders × 35s = ~12 min (one-size-fits-all delay).
    New approach: group by provider, use provider-specific delays, run
    Mistral and Cerebras in parallel with each other (different APIs).

    Estimated time: ~4 min (dominated by 5 Gemini Pro calls × 35s).
    """
    brief = await get_latest_brief()
    if not brief:
        return {"error": "No market brief available. Run /api/market/brief/trigger first."}

    db = get_supabase_admin()

    # Get all AI trader profiles
    ai_profiles = (
        db.table("profiles")
        .select("id, display_name, ai_model, is_ai")
        .eq("is_ai", True)
        .execute()
    )

    if not ai_profiles.data:
        return {"error": "No AI traders found. Run /api/ai/setup first."}

    # Group profiles by model key (= API provider)
    by_model: dict[str, list[dict]] = {}
    for profile in ai_profiles.data:
        model_key = profile.get("ai_model", "unknown")
        by_model.setdefault(model_key, []).append(profile)

    # Run Gemini Pro first (slowest — 35s between calls, bottleneck)
    # Then run Gemini Flash (same API, different rate limit — must be sequential with Pro)
    # Meanwhile, Mistral and Cerebras use different APIs and can run in parallel
    all_results = []

    # Phase 1: Gemini calls (must be sequential — same API key)
    gemini_pro = by_model.pop("gemini-pro", [])
    gemini_flash = by_model.pop("gemini-flash", [])

    # Phase 2: Non-Gemini calls (can run in parallel with each other)
    non_gemini_batches = []
    for model_key, profiles in by_model.items():
        delay = PROVIDER_DELAYS.get(model_key, 5)
        non_gemini_batches.append(
            _run_provider_batch(db, brief, profiles, delay, session=session)
        )

    # Run Gemini (sequential) in parallel with all non-Gemini providers
    async def _run_all_gemini():
        results = []
        if gemini_pro:
            results.extend(
                await _run_provider_batch(db, brief, gemini_pro, PROVIDER_DELAYS["gemini-pro"], session=session)
            )
        if gemini_flash:
            results.extend(
                await _run_provider_batch(db, brief, gemini_flash, PROVIDER_DELAYS["gemini-flash"], session=session)
            )
        return results

    # Gather: Gemini batch + all non-Gemini batches run concurrently
    gathered = await asyncio.gather(
        _run_all_gemini(),
        *non_gemini_batches,
    )

    # Flatten results
    for batch_result in gathered:
        if isinstance(batch_result, list):
            all_results.extend(batch_result)

    # Auto-snapshot all portfolios after trading completes
    try:
        from app.services.snapshots import take_all_snapshots
        snapshot_count = await take_all_snapshots()
    except Exception:
        snapshot_count = 0

    return {
        "date": brief.get("date", date.today().isoformat()),
        "session": session,
        "traders_processed": len(all_results),
        "snapshots_created": snapshot_count,
        "results": all_results,
    }
