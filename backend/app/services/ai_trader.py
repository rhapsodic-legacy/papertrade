import asyncio
import json
import logging
import httpx
from datetime import date

logger = logging.getLogger(__name__)

from app.config import get_settings
from app.services.market_brief import get_latest_brief
from app.services.market_data import get_quote, get_stock_candles, get_crypto_history, TOP_STOCKS, CRYPTO_MAP, STOCK_SECTORS
from app.services.pattern_recognition import analyze_patterns
from app.services.portfolio_optimizer import (
    compute_portfolio_correlations,
    compute_target_allocation,
)
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
        "toolkit": [
            {"module": "macro", "weight": 9},
            {"module": "technicals", "weight": 8},
            {"module": "fundamentals", "weight": 7},
            {"module": "optimizer", "weight": 6},
            {"module": "sentiment", "weight": 5},
            {"module": "signal_ranker", "weight": 4},
            {"module": "expert_opinion", "weight": 8},
            {"module": "trade_context", "weight": 7},
            {"module": "options_flow", "weight": 2},
            {"module": "yield_curve", "weight": 2},
            {"module": "dynamic_risk", "weight": 1},
        ],
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
        "toolkit": [
            {"module": "fundamentals", "weight": 10},
            {"module": "macro", "weight": 9},
            {"module": "optimizer", "weight": 8},
            {"module": "technicals", "weight": 7},
            {"module": "expert_opinion", "weight": 8},
            {"module": "yield_curve", "weight": 5},
            {"module": "options_flow", "weight": 4},
            {"module": "signal_ranker", "weight": 3},
            {"module": "trade_context", "weight": 7},
            {"module": "dynamic_risk", "weight": 1},
        ],
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
        "toolkit": [
            {"module": "momentum", "weight": 10},
            {"module": "technicals", "weight": 9},
            {"module": "patterns", "weight": 8},
            {"module": "sentiment", "weight": 7},
            {"module": "optimizer", "weight": 5},
            {"module": "signal_ranker", "weight": 4},
            {"module": "expert_opinion", "weight": 7},
            {"module": "trade_context", "weight": 7},
        ],
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
        "toolkit": [
            {"module": "sentiment", "weight": 9, "invert": True},
            {"module": "fundamentals", "weight": 8},
            {"module": "expert_opinion", "weight": 9, "invert": True},
            {"module": "patterns", "weight": 7},
            {"module": "macro", "weight": 6},
            {"module": "options_flow", "weight": 5},
            {"module": "optimizer", "weight": 4},
            {"module": "trade_context", "weight": 7},
            {"module": "yield_curve", "weight": 2},
            {"module": "dynamic_risk", "weight": 1},
        ],
    },
    "crypto_chad": {
        "name": "Crypto Chad",
        "prompt": (
            "You are a crypto-native trader called Crypto Chad, inspired by "
            "on-chain analysts and narrative cycle trading. "
            "PRE-BUY DISCIPLINE (apply BEFORE every BUY decision): "
            "(1) If this asset is already >15% of your portfolio, DO NOT add more — rotate or hold. "
            "(2) If your existing position is down >5% from your entry without a thesis change, "
            "DO NOT average down. Averaging down on losers without new information is how losses compound. "
            "(3) If you've already issued 3+ buys this session with 0 sells, you're accumulating "
            "without rotating — actively look for trim candidates before any new buy. "
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
        "toolkit": [
            {"module": "momentum", "weight": 10},
            {"module": "technicals", "weight": 9},
            {"module": "patterns", "weight": 8},
            {"module": "sentiment", "weight": 6},
            {"module": "expert_opinion", "weight": 8},
            {"module": "optimizer", "weight": 5},
            {"module": "yield_curve", "weight": 4},
            {"module": "signal_ranker", "weight": 3},
            {"module": "trade_context", "weight": 7},
        ],
    },
}

# Model configurations
# NOTE: Gemini models disabled (spending cap hit). Swapped to free Groq-hosted
# alternatives. Original Gemini config preserved for re-enablement:
#   "gemini-flash": {"label": "Gemini Flash", "api": "gemini", "model_id": "gemini-2.5-flash"},
#   "gemini-pro": {"label": "Gemini Pro", "api": "gemini", "model_id": "gemini-2.5-pro"},
MODELS = {
    "gemini-flash": {
        "label": "Mistral Small",
        "api": "mistral",
        "api_key_field": "mistral_api_key_2",
        "model_id": "mistral-small-latest",
    },
    "gemini-pro": {
        "label": "Mistral Large 2",
        "api": "mistral",
        "api_key_field": "mistral_api_key_2",
        "model_id": "mistral-large-latest",
    },
    "mistral": {
        "label": "Mistral Large",
        "api": "mistral",
        "api_key_field": "mistral_api_key",
        "model_id": "mistral-large-latest",
    },
    "llama": {
        "label": "Mistral Medium",
        "api": "mistral",
        "api_key_field": "mistral_api_key",
        "model_id": "mistral-medium-latest",
    },
    "nvidia-deepseek-r1": {
        "label": "DeepSeek V3.2 (NVIDIA)",
        "api": "nvidia",
        "api_key_field": "nvidia_api_key",
        "model_id": "deepseek-ai/deepseek-v3.2",
    },
}

# Intra-personality jitter for max_hold_days. Prevents the four same-personality
# traders from all hitting their stale-position trigger on the same day, which
# was driving cross-model herd exits (e.g. 6 AIs all selling WMT on 2026-04-22).
# Values are small deltas — they nudge hold periods apart without changing the
# personality's risk profile meaningfully.
_MODEL_HOLD_JITTER_DAYS = {
    "gemini-flash": 0,        # Mistral Small
    "gemini-pro": 2,          # Mistral Large 2
    "mistral": 4,             # Mistral Large
    "llama": 6,               # Mistral Medium
    "nvidia-deepseek-r1": 8,  # DeepSeek V3.2
}


def _jittered_risk_params(base: dict, model_key: str) -> dict:
    """Return a copy of risk_params with max_hold_days shifted by a model-specific
    offset. Every other parameter is preserved."""
    jitter = _MODEL_HOLD_JITTER_DAYS.get(model_key, 0)
    if jitter == 0:
        return dict(base)
    params = dict(base)
    params["max_hold_days"] = params.get("max_hold_days", 30) + jitter
    return params


# Custom trader model (uses third Mistral API key)
CUSTOM_TRADER_MODEL = {
    "label": "Custom (Mistral)",
    "api": "mistral",
    "api_key_field": "mistral_api_key_3",
    "model_id": "mistral-large-latest",
}

# Risk presets for custom traders
CUSTOM_RISK_PRESETS = {
    "low": {
        "stop_loss_pct": -6.0,
        "take_profit_pct": 12.0,
        "max_position_pct": 12.0,
        "max_hold_days": 45,
        "min_sells_with_positions": 1,
    },
    "medium": {
        "stop_loss_pct": -8.0,
        "take_profit_pct": 15.0,
        "max_position_pct": 15.0,
        "max_hold_days": 30,
        "min_sells_with_positions": 1,
    },
    "high": {
        "stop_loss_pct": -5.0,
        "take_profit_pct": 10.0,
        "max_position_pct": 20.0,
        "max_hold_days": 14,
        "min_sells_with_positions": 1,
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

## Your Data
You receive data from a curated set of analysis modules tailored to your trading strategy.
Your "Data Toolkit" section lists which modules you have and why they were selected for you.
Focus your analysis on the modules provided — they match your strategy's strengths.
You always have: your portfolio state, risk alerts, and supported asset lists.

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

## Conditional Orders (Optional)
You may also place conditional orders that execute automatically when price conditions are met. \
These run between daily sessions — a subagent monitors prices every 5 minutes and executes when triggered. \
Order types:
- **limit_buy**: Buy when price drops to or below trigger_price (buy the dip)
- **stop_loss**: Sell when price drops to or below trigger_price (cut losses)
- **take_profit**: Sell when price rises to or above trigger_price (lock gains)
- **trailing_stop**: Sell when price drops trail_pct% from its high-water mark (dynamic stop-loss)

Conditional orders expire after 5 days. Use them strategically — not every day needs conditional orders. \
Good use cases: protecting a new position with a stop-loss, setting a limit buy at support, \
or trailing a winner. Maximum 3 conditional orders per day.

Respond ONLY with valid JSON in this exact format, no other text:
{"trades": [{"symbol": "AAPL", "asset_type": "stock", "side": "buy", "quantity": 10, "reasoning": "Brief 1-2 sentence explanation of WHY this trade, citing specific data (e.g. RSI, PE, regime, sector rotation). If a news cluster drove this decision, name it.", "modules_used": ["technicals", "fundamentals"], "cluster_ref": "Tech Earnings Beat"}], "conditional_orders": [{"symbol": "AAPL", "asset_type": "stock", "order_type": "stop_loss", "side": "sell", "quantity": 10, "trigger_price": 165.00, "reasoning": "Protect new position"}, {"symbol": "ETH", "asset_type": "crypto", "order_type": "trailing_stop", "side": "sell", "quantity": 0.5, "trail_pct": 8.0, "reasoning": "Ride momentum with 8% trail"}]}
"modules_used" lists which of your Data Toolkit modules informed this trade decision. Use the module names from your toolkit manifest.
"cluster_ref" (optional) — if a headline cluster from Market News influenced this trade, put the EXACT theme name from the clusters listed above. Do NOT invent cluster names. If no cluster is relevant, omit this field entirely. Only use theme names that appear verbatim in your Market News (clustered) section.
"conditional_orders" is optional — omit the field entirely if you have no conditional orders this session.
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
        personality_name = PERSONALITIES[trader["personality_key"]]["name"]
        email = f"ai-{trader['personality_key']}-{trader['model_key']}@papertrade.bot"

        # Check if this AI trader already exists (by model_key + personality in display_name)
        existing = (
            db.table("profiles")
            .select("id, display_name")
            .eq("ai_model", trader["model_key"])
            .eq("is_ai", True)
            .ilike("display_name", f"%{personality_name}%")
            .execute()
        )
        if existing.data:
            # Update display_name in case model labels changed
            if existing.data[0]["display_name"] != display_name:
                db.table("profiles").update(
                    {"display_name": display_name}
                ).eq("id", existing.data[0]["id"]).execute()
                created.append({"display_name": display_name, "status": "exists (renamed)"})
            else:
                created.append({"display_name": display_name, "status": "exists"})
            continue

        # Create auth user (AI traders get random unusable passwords)
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
    """Call Mistral La Plateforme API (OpenAI-compatible) with retry on disconnect."""
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
    last_err = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
                if resp.status_code == 429:
                    wait = 10 * (attempt + 1)
                    print(f"[MISTRAL] {model_id} rate-limited, waiting {wait}s (attempt {attempt + 1}/3)")
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code != 200:
                    raise Exception(f"Mistral {model_id} error {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except (httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            last_err = e
            wait = 8 * (attempt + 1)
            print(f"[MISTRAL] {model_id} connection error: {type(e).__name__}, retrying in {wait}s (attempt {attempt + 1}/3)")
            await asyncio.sleep(wait)
    raise Exception(f"Mistral {model_id} failed after 3 attempts: {last_err}")


async def _call_nvidia_nim(model_id: str, system: str, user_msg: str, api_key: str) -> str:
    """Call NVIDIA NIM (OpenAI-compatible) with retry on rate limit / disconnect.
    Free tier is 40 RPM per model. The endpoint lives at
    https://integrate.api.nvidia.com/v1/chat/completions."""
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.7,
        "max_tokens": 2048,
    }
    last_err = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
                if resp.status_code == 429:
                    wait = 10 * (attempt + 1)
                    print(f"[NVIDIA] {model_id} rate-limited, waiting {wait}s (attempt {attempt + 1}/3)")
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code != 200:
                    raise Exception(f"NVIDIA {model_id} error {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except (httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            last_err = e
            wait = 8 * (attempt + 1)
            print(f"[NVIDIA] {model_id} connection error: {type(e).__name__}, retrying in {wait}s (attempt {attempt + 1}/3)")
            await asyncio.sleep(wait)
    raise Exception(f"NVIDIA {model_id} failed after 3 attempts: {last_err}")


async def _call_groq(model_id: str, system: str, user_msg: str, api_key: str) -> str:
    """Call Groq API (OpenAI-compatible)."""
    url = "https://api.groq.com/openai/v1/chat/completions"
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
            raise Exception(f"Groq {model_id} error {resp.status_code}: {resp.text[:300]}")
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


def _compute_trade_context(db, user_id: str) -> dict | None:
    """Compute historical trade statistics for a trader's own track record.

    Returns win/loss stats by asset type, holding period, sector, and streak.
    """
    # Fetch more history for statistics (up to 100 trades)
    resp = (
        db.table("transactions")
        .select("symbol, asset_type, side, quantity, price, total, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=False)
        .limit(200)
        .execute()
    )
    txs = resp.data if resp.data else []
    if len(txs) < 4:
        return None

    # FIFO matching to get round-trip P&L
    holdings: dict[str, list[tuple[float, float, str, str]]] = {}  # sym -> [(qty, price, date, asset_type)]
    round_trips = []

    for tx in txs:
        sym = tx["symbol"]
        qty = tx["quantity"]
        price = tx["price"]
        atype = tx.get("asset_type", "stock")
        trade_date = tx.get("created_at", "")[:10]

        if tx["side"] == "buy":
            holdings.setdefault(sym, []).append((qty, price, trade_date, atype))
        elif tx["side"] == "sell" and sym in holdings and holdings[sym]:
            remaining = qty
            lots = holdings[sym]
            while remaining > 0 and lots:
                lot_qty, lot_price, buy_date, lot_type = lots[0]
                take = min(remaining, lot_qty)
                if take > 0 and lot_price > 0:
                    pnl_pct = ((price / lot_price) - 1) * 100
                    # Compute holding days
                    try:
                        from datetime import datetime
                        buy_dt = datetime.fromisoformat(buy_date)
                        sell_dt = datetime.fromisoformat(trade_date)
                        hold_days = (sell_dt - buy_dt).days
                    except Exception:
                        hold_days = 0
                    round_trips.append({
                        "symbol": sym,
                        "asset_type": lot_type,
                        "pnl_pct": pnl_pct,
                        "hold_days": hold_days,
                        "sector": STOCK_SECTORS.get(sym, "Other") if lot_type != "crypto" else "Crypto",
                    })
                remaining -= take
                if take >= lot_qty:
                    lots.pop(0)
                else:
                    lots[0] = (lot_qty - take, lot_price, buy_date, lot_type)

    if not round_trips:
        return None

    wins = [r for r in round_trips if r["pnl_pct"] > 0]
    losses = [r for r in round_trips if r["pnl_pct"] <= 0]

    result = {
        "total_round_trips": len(round_trips),
        "win_rate": len(wins) / len(round_trips) * 100,
        "avg_win_pct": sum(r["pnl_pct"] for r in wins) / len(wins) if wins else 0,
        "avg_loss_pct": sum(r["pnl_pct"] for r in losses) / len(losses) if losses else 0,
    }

    # By asset type
    by_type: dict[str, list] = {}
    for r in round_trips:
        by_type.setdefault(r["asset_type"], []).append(r)
    result["by_asset_type"] = {
        atype: {
            "count": len(trades),
            "win_rate": sum(1 for t in trades if t["pnl_pct"] > 0) / len(trades) * 100,
            "avg_pnl": sum(t["pnl_pct"] for t in trades) / len(trades),
        }
        for atype, trades in by_type.items()
    }

    # By holding period
    short = [r for r in round_trips if r["hold_days"] <= 7]
    medium = [r for r in round_trips if 7 < r["hold_days"] <= 21]
    long_hold = [r for r in round_trips if r["hold_days"] > 21]
    by_hold = {}
    for label, group in [("1-7 days", short), ("8-21 days", medium), ("22+ days", long_hold)]:
        if group:
            by_hold[label] = {
                "count": len(group),
                "win_rate": sum(1 for t in group if t["pnl_pct"] > 0) / len(group) * 100,
                "avg_pnl": sum(t["pnl_pct"] for t in group) / len(group),
            }
    result["by_hold_period"] = by_hold

    # By sector
    by_sector: dict[str, list] = {}
    for r in round_trips:
        by_sector.setdefault(r["sector"], []).append(r)
    result["by_sector"] = {
        sector: {
            "count": len(trades),
            "win_rate": sum(1 for t in trades if t["pnl_pct"] > 0) / len(trades) * 100,
            "avg_pnl": sum(t["pnl_pct"] for t in trades) / len(trades),
        }
        for sector, trades in by_sector.items()
    }

    # Recent streak
    recent = round_trips[-10:]
    streak_dir = "winning" if recent[-1]["pnl_pct"] > 0 else "losing"
    streak_len = 1
    for r in reversed(recent[:-1]):
        if (r["pnl_pct"] > 0) == (streak_dir == "winning"):
            streak_len += 1
        else:
            break
    result["streak"] = {"direction": streak_dir, "length": streak_len}

    return result


def _compute_dynamic_risk(db, user_id: str) -> dict | None:
    """Compute drawdown-aware risk adjustments from portfolio snapshots."""
    snap_resp = (
        db.table("portfolio_snapshots")
        .select("snapshot_date, total_value")
        .eq("user_id", user_id)
        .order("snapshot_date", desc=False)
        .execute()
    )
    snaps = snap_resp.data if snap_resp.data else []
    if len(snaps) < 3:
        return None

    values = [s["total_value"] for s in snaps]
    current = values[-1]
    peak = max(values)
    dd_pct = ((peak - current) / peak) * 100 if peak > 0 else 0

    # Find drawdown duration
    peak_idx = values.index(peak)
    dd_days = len(values) - 1 - peak_idx if peak_idx < len(values) - 1 else 0

    # Size multiplier: scale down in drawdown
    if dd_pct < 1:
        multiplier = 1.0
    elif dd_pct < 3:
        multiplier = 0.85
    elif dd_pct < 5:
        multiplier = 0.70
    elif dd_pct < 10:
        multiplier = 0.50
    else:
        multiplier = 0.30

    # Recent 5-day trend
    if len(values) >= 6:
        recent_5d = ((values[-1] / values[-6]) - 1) * 100
    elif len(values) >= 2:
        recent_5d = ((values[-1] / values[0]) - 1) * 100
    else:
        recent_5d = 0

    if recent_5d > 0.5:
        trend = "recovering"
    elif recent_5d < -0.5:
        trend = "declining"
    else:
        trend = "flat"

    return {
        "peak_value": peak,
        "current_value": current,
        "drawdown_pct": round(dd_pct, 1),
        "drawdown_days": dd_days,
        "size_multiplier": round(multiplier, 2),
        "equity_trend": trend,
        "recent_5d_return": round(recent_5d, 1),
    }


def _compute_discipline_score(
    db, user_id: str, personality_key: str, portfolio: dict,
) -> dict | None:
    """Score how well this trader follows their own risk rules.

    Checks: stop-loss adherence, position sizing, hold time limits,
    diversification, and sell discipline. Returns a dict with scores
    and specific violations to include in the prompt.
    """
    if personality_key == "custom" or personality_key not in PERSONALITIES:
        return None

    risk_params = PERSONALITIES[personality_key].get("risk_params", {})
    positions = portfolio.get("positions", [])
    cash = portfolio.get("cash", 0)
    total_value = cash + sum(p.get("market_value", 0) for p in positions)

    if total_value <= 0 or not positions:
        return None

    stop_loss = risk_params.get("stop_loss_pct", -10)
    take_profit = risk_params.get("take_profit_pct", 20)
    max_pos_pct = risk_params.get("max_position_pct", 15)
    max_hold = risk_params.get("max_hold_days", 30)

    violations = []
    scores = {
        "stop_loss": 100,
        "position_sizing": 100,
        "hold_discipline": 100,
        "diversification": 100,
    }

    # Check stop-loss violations (positions past stop-loss still held)
    stop_loss_breaches = 0
    for p in positions:
        pnl_pct = ((p["current_price"] / p["avg_cost"]) - 1) * 100 if p["avg_cost"] > 0 else 0
        if pnl_pct <= stop_loss:
            stop_loss_breaches += 1
            violations.append(
                f"STOP-LOSS IGNORED: {p['symbol']} is at {pnl_pct:+.1f}% "
                f"(stop-loss is {stop_loss}%). You should have sold this already."
            )
    if stop_loss_breaches:
        scores["stop_loss"] = max(0, 100 - stop_loss_breaches * 30)

    # Check position sizing violations
    overweight = 0
    for p in positions:
        pct = p.get("market_value", 0) / total_value * 100
        if pct > max_pos_pct * 1.1:  # 10% grace
            overweight += 1
            violations.append(
                f"OVERWEIGHT: {p['symbol']} is {pct:.1f}% of portfolio "
                f"(limit is {max_pos_pct}%). Trim this position."
            )
    if overweight:
        scores["position_sizing"] = max(0, 100 - overweight * 25)

    # Check hold discipline
    stale = 0
    for p in positions:
        hold_days = p.get("hold_days", 0)
        pnl_pct = ((p["current_price"] / p["avg_cost"]) - 1) * 100 if p["avg_cost"] > 0 else 0
        if hold_days > max_hold and abs(pnl_pct) < 5:
            stale += 1
            violations.append(
                f"STALE POSITION: {p['symbol']} held {hold_days}d "
                f"(limit {max_hold}d) with only {pnl_pct:+.1f}% return. "
                f"Free up this capital."
            )
    if stale:
        scores["hold_discipline"] = max(0, 100 - stale * 20)

    # Check diversification (sector concentration)
    sector_pcts: dict[str, float] = {}
    for p in positions:
        sector = STOCK_SECTORS.get(p["symbol"], "Crypto" if p.get("asset_type") == "crypto" else "Other")
        sector_pcts[sector] = sector_pcts.get(sector, 0) + (p.get("market_value", 0) / total_value * 100)
    for sector, pct in sector_pcts.items():
        if pct > 50:
            scores["diversification"] = max(0, 100 - int((pct - 40) * 2))
            violations.append(
                f"CONCENTRATED: {sector} is {pct:.0f}% of portfolio. Diversify."
            )

    overall = sum(scores.values()) / len(scores)
    grade = (
        "A" if overall >= 90 else
        "B" if overall >= 75 else
        "C" if overall >= 60 else
        "D" if overall >= 40 else
        "F"
    )

    return {
        "overall_score": round(overall),
        "grade": grade,
        "scores": scores,
        "violations": violations,
    }


def _compute_peer_exit_warnings(db, current_user_id: str, lookback_hours: int = 48) -> str:
    """Detect when 3+ other AI traders have exited the same symbol in the recent
    past. Returns formatted warning text (empty string if no herd signals).
    The goal is to flag 'late herd following' before the current trader commits
    to a sell that's just pattern-matching what peers already did."""
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()

    profiles_resp = db.table("profiles").select("id").eq("is_ai", True).execute()
    ai_ids = [p["id"] for p in (profiles_resp.data or []) if p["id"] != current_user_id]
    if not ai_ids:
        return ""

    tx_resp = (
        db.table("transactions")
        .select("user_id, symbol, side, created_at")
        .in_("user_id", ai_ids)
        .eq("side", "sell")
        .gte("created_at", cutoff)
        .execute()
    )

    sellers_by_symbol: dict[str, set] = {}
    for tx in (tx_resp.data or []):
        sellers_by_symbol.setdefault(tx["symbol"], set()).add(tx["user_id"])

    clusters = [(sym, len(uids)) for sym, uids in sellers_by_symbol.items() if len(uids) >= 3]
    if not clusters:
        return ""

    clusters.sort(key=lambda x: -x[1])
    lines = [
        f"## ⚠ Peer Exit Alert (last {lookback_hours}h)",
        "Multiple other AI traders have exited these names recently. If you're",
        "about to sell any of these too, pause and check: is your thesis",
        "independent, or are you pattern-matching what peers already did? Following",
        "the herd late is a known loss pattern (you sell at the bottom of a",
        "sentiment swing, then the name recovers without you).",
        "",
    ]
    for sym, count in clusters[:10]:
        lines.append(f"  {sym}: {count} other AIs sold in the last {lookback_hours}h")

    return "\n".join(lines)


def _format_cross_trader_positions(
    all_ai_positions: list[dict], current_user_id: str, brief: dict,
) -> str:
    """Format what other AI personalities currently hold."""
    # Build price lookup from brief
    prices: dict[str, float] = {}
    for s in brief.get("stocks", []):
        prices[s["symbol"]] = s["price"]
    for c in brief.get("crypto", []):
        prices[c["symbol"]] = c["price"]

    # Group positions by personality (from display_name)
    by_personality: dict[str, list[str]] = {}
    for pos in all_ai_positions:
        if pos["user_id"] == current_user_id:
            continue
        display = pos.get("display_name", "")
        # Extract personality name (before the parenthesis)
        pname = display.split("(")[0].strip() if "(" in display else display
        sym = pos["symbol"]
        qty = float(pos["quantity"])
        price = prices.get(sym, 0)
        value = qty * price
        if value < 100:
            continue
        by_personality.setdefault(pname, []).append(f"{sym}")

    if not by_personality:
        return ""

    lines = []
    for pname, symbols in sorted(by_personality.items()):
        # Deduplicate (multiple models share same personality)
        unique = sorted(set(symbols))
        lines.append(f"  {pname}: {', '.join(unique)}")

    return "## What Other AI Traders Hold\n" + "\n".join(lines)


def build_performance_intelligence(db) -> dict[str, str]:
    """Compute personalized performance intelligence for every AI trader.

    Called once per pipeline run. Returns {user_id: formatted_text}.
    Each trader gets:
    1. Self-assessment: win rate trend, strengths/weaknesses by asset type
    2. Peer comparison: how their same-personality peer (different model) is doing
    3. Specific actionable insights from peer decisions that diverged
    """
    import json

    # Get all AI profiles with personality mapping
    profiles_resp = (
        db.table("profiles")
        .select("id, display_name, ai_model, is_ai")
        .eq("is_ai", True)
        .execute()
    )
    if not profiles_resp.data:
        return {}

    profile_map = {}
    personality_groups: dict[str, list[dict]] = {}
    for p in profiles_resp.data:
        pkey = None
        for k, v in PERSONALITIES.items():
            if v["name"] in p["display_name"]:
                pkey = k
                break
        profile_map[p["id"]] = {
            "display_name": p["display_name"],
            "ai_model": p["ai_model"],
            "personality": pkey,
        }
        if pkey:
            personality_groups.setdefault(pkey, []).append(p)

    trader_ids = [p["id"] for p in profiles_resp.data]

    # Batch fetch recent transactions (last 30 days)
    today = date.today()
    from datetime import timedelta
    cutoff = (today - timedelta(days=30)).isoformat()

    tx_resp = (
        db.table("transactions")
        .select("user_id, symbol, asset_type, side, quantity, price, total, created_at, reasoning, modules_used")
        .in_("user_id", trader_ids)
        .gte("created_at", f"{cutoff}T00:00:00")
        .order("created_at", desc=False)
        .execute()
    )

    # Group transactions by user
    tx_by_user: dict[str, list] = {}
    for tx in tx_resp.data or []:
        tx_by_user.setdefault(tx["user_id"], []).append(tx)

    # Fetch recent reflections
    ref_resp = (
        db.table("trade_reflections")
        .select("user_id, symbol, side, outcome_score, lessons, reflected_at")
        .in_("user_id", trader_ids)
        .order("reflected_at", desc=True)
        .limit(200)
        .execute()
    )
    ref_by_user: dict[str, list] = {}
    for r in ref_resp.data or []:
        ref_by_user.setdefault(r["user_id"], []).append(r)

    # Compute per-trader metrics
    trader_metrics: dict[str, dict] = {}
    for uid in trader_ids:
        txs = tx_by_user.get(uid, [])
        refs = ref_by_user.get(uid, [])
        trader_metrics[uid] = _compute_trader_intel(txs, refs)

    # Build formatted text per trader
    result: dict[str, str] = {}
    for uid in trader_ids:
        info = profile_map.get(uid, {})
        pkey = info.get("personality")
        if not pkey:
            continue

        sections = []

        # --- Self Assessment ---
        metrics = trader_metrics[uid]
        self_lines = _format_self_assessment(metrics)
        if self_lines:
            sections.append("### YOUR PERFORMANCE INTELLIGENCE\n" + self_lines)

        # --- Peer Comparison ---
        peers = personality_groups.get(pkey, [])
        peer_profiles = [p for p in peers if p["id"] != uid]
        if peer_profiles:
            peer_lines = _format_peer_comparison(
                uid, info, metrics, peer_profiles, trader_metrics, tx_by_user,
            )
            if peer_lines:
                sections.append(peer_lines)

        if sections:
            result[uid] = "\n\n".join(sections)

    return result


def _compute_trader_intel(txs: list[dict], reflections: list[dict]) -> dict:
    """Compute intelligence metrics from a trader's recent transactions and reflections."""
    import json

    if not txs:
        return {"total_trades": 0}

    buys = [t for t in txs if t["side"] == "buy"]
    sells = [t for t in txs if t["side"] == "sell"]

    # Replay for P&L per sell
    positions: dict[str, dict] = {}
    sell_pnl: list[dict] = []  # {symbol, asset_type, pnl, modules, date}
    buy_entries: dict[str, dict] = {}  # symbol -> last buy info

    for tx in txs:
        sym = tx["symbol"]
        qty = float(tx["quantity"])
        price = float(tx["price"])

        if tx["side"] == "buy":
            if sym not in positions:
                positions[sym] = {"qty": 0.0, "cost_basis": 0.0}
            pos = positions[sym]
            total_cost = pos["qty"] * pos["cost_basis"] + qty * price
            pos["qty"] += qty
            pos["cost_basis"] = total_cost / pos["qty"] if pos["qty"] > 0 else 0
            buy_entries[sym] = {
                "reasoning": tx.get("reasoning", ""),
                "modules": [],
                "date": tx["created_at"][:10],
            }
            if tx.get("modules_used"):
                try:
                    buy_entries[sym]["modules"] = json.loads(tx["modules_used"])
                except (json.JSONDecodeError, TypeError):
                    pass
        else:
            pos = positions.get(sym)
            if pos and pos["qty"] > 0:
                pnl = (price - pos["cost_basis"]) * qty
                modules = []
                if tx.get("modules_used"):
                    try:
                        modules = json.loads(tx["modules_used"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                sell_pnl.append({
                    "symbol": sym,
                    "asset_type": tx.get("asset_type", "stock"),
                    "pnl": pnl,
                    "pnl_pct": ((price / pos["cost_basis"]) - 1) * 100 if pos["cost_basis"] > 0 else 0,
                    "modules": modules,
                    "date": tx["created_at"][:10],
                    "reasoning": tx.get("reasoning", ""),
                })
                pos["qty"] -= qty
                if pos["qty"] <= 0.001:
                    pos["qty"] = 0

    # Win rate by asset type
    by_asset: dict[str, dict] = {}
    for s in sell_pnl:
        atype = s["asset_type"]
        if atype not in by_asset:
            by_asset[atype] = {"wins": 0, "losses": 0, "total_pnl": 0.0}
        if s["pnl"] > 0:
            by_asset[atype]["wins"] += 1
        else:
            by_asset[atype]["losses"] += 1
        by_asset[atype]["total_pnl"] += s["pnl"]

    # Recent reflection trend
    avg_outcome = 0.0
    outcome_trend = "unknown"
    if reflections:
        scores = [float(r["outcome_score"]) for r in reflections[:20]]
        avg_outcome = sum(scores) / len(scores)
        if len(scores) >= 6:
            first_half = sum(scores[len(scores)//2:]) / (len(scores) - len(scores)//2)
            second_half = sum(scores[:len(scores)//2]) / (len(scores)//2)
            if second_half > first_half + 0.1:
                outcome_trend = "improving"
            elif second_half < first_half - 0.1:
                outcome_trend = "declining"
            else:
                outcome_trend = "stable"

    # Best and worst trades
    best_trade = max(sell_pnl, key=lambda x: x["pnl"]) if sell_pnl else None
    worst_trade = min(sell_pnl, key=lambda x: x["pnl"]) if sell_pnl else None

    # Recent notable buys (last 5)
    recent_buys = [
        {"symbol": b["symbol"], "reasoning": b.get("reasoning", "")[:200], "date": b["created_at"][:10]}
        for b in buys[-5:]
    ]

    total_sells = len(sell_pnl)
    wins = sum(1 for s in sell_pnl if s["pnl"] > 0)

    return {
        "total_trades": len(txs),
        "total_sells": total_sells,
        "win_rate": round(wins / total_sells * 100, 1) if total_sells > 0 else 0,
        "total_pnl": round(sum(s["pnl"] for s in sell_pnl), 2),
        "by_asset": by_asset,
        "avg_outcome_score": round(avg_outcome, 2),
        "outcome_trend": outcome_trend,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "recent_buys": recent_buys,
        "sell_details": sell_pnl,
        "recent_lessons": [r.get("lessons", "") for r in (reflections or [])[:3] if r.get("lessons")],
    }


def _format_self_assessment(metrics: dict) -> str:
    """Format self-assessment section from computed metrics."""
    if metrics.get("total_trades", 0) == 0:
        return ""

    lines = []

    # Overall performance
    wr = metrics.get("win_rate", 0)
    total_pnl = metrics.get("total_pnl", 0)
    sells = metrics.get("total_sells", 0)
    if sells > 0:
        pnl_label = f"+${total_pnl:,.0f}" if total_pnl >= 0 else f"-${abs(total_pnl):,.0f}"
        lines.append(f"30-day record: {sells} closed trades, {wr:.0f}% win rate, {pnl_label} realized P&L")

    # Asset type breakdown
    by_asset = metrics.get("by_asset", {})
    for atype, stats in by_asset.items():
        total = stats["wins"] + stats["losses"]
        if total >= 2:
            awr = round(stats["wins"] / total * 100)
            pnl = stats["total_pnl"]
            if awr < 40:
                lines.append(f"WEAKNESS: {atype} trades have {awr}% win rate ({stats['wins']}W/{stats['losses']}L, ${pnl:+,.0f})")
            elif awr >= 65:
                lines.append(f"STRENGTH: {atype} trades have {awr}% win rate ({stats['wins']}W/{stats['losses']}L, ${pnl:+,.0f})")

    # Reflection trend
    trend = metrics.get("outcome_trend", "unknown")
    avg_score = metrics.get("avg_outcome_score", 0)
    if trend == "declining":
        lines.append(f"WARNING: Your trade quality is declining (avg outcome score {avg_score:+.2f}). Review your recent approach.")
    elif trend == "improving":
        lines.append(f"POSITIVE: Your trade quality is improving (avg outcome score {avg_score:+.2f}). Keep refining.")
    elif trend == "stable" and avg_score < -0.2:
        lines.append(f"CONCERN: Trade outcomes are consistently poor (avg score {avg_score:+.2f}). Consider adjusting strategy.")

    # Recent lessons from reflections
    lessons = metrics.get("recent_lessons", [])
    if lessons:
        lines.append("Your recent lessons (apply these today):")
        for lesson in lessons[:3]:
            lines.append(f"  - {lesson}")

    return "\n".join(lines) if lines else ""


def _format_peer_comparison(
    current_uid: str,
    current_info: dict,
    current_metrics: dict,
    peer_profiles: list[dict],
    all_metrics: dict[str, dict],
    tx_by_user: dict[str, list],
) -> str:
    """Format peer comparison: same personality, different model."""
    lines = []
    current_model = current_info.get("ai_model", "unknown")

    for peer in peer_profiles:
        peer_uid = peer["id"]
        peer_model = peer.get("ai_model", "unknown")
        peer_metrics = all_metrics.get(peer_uid, {})

        if peer_metrics.get("total_trades", 0) < 3:
            continue

        peer_wr = peer_metrics.get("win_rate", 0)
        current_wr = current_metrics.get("win_rate", 0)
        peer_pnl = peer_metrics.get("total_pnl", 0)
        current_pnl = current_metrics.get("total_pnl", 0)

        # Determine who's outperforming
        peer_label = MODELS.get(peer_model, {}).get("label", peer_model)
        you_label = MODELS.get(current_model, {}).get("label", current_model)

        header = (
            f"### PEER INTELLIGENCE: {peer_label} counterpart\n"
            f"Another AI running your EXACT same personality/strategy on the {peer_label} model.\n"
            f"This is a COMPETITION — you are both trying to maximize returns independently.\n"
            f"Their holdings differ from yours, so identical moves rarely make sense.\n"
            f"Learn from their wins and mistakes, but YOU decide what's right for YOUR portfolio."
        )

        comparison = []

        # Win rate comparison
        wr_diff = current_wr - peer_wr
        if abs(wr_diff) >= 10 and current_metrics.get("total_sells", 0) >= 3 and peer_metrics.get("total_sells", 0) >= 3:
            if wr_diff > 0:
                comparison.append(
                    f"You're outperforming this AI: {current_wr:.0f}% vs {peer_wr:.0f}% win rate. "
                    f"Your approach is working — don't abandon what's winning."
                )
            else:
                comparison.append(
                    f"This AI has a higher win rate: {peer_wr:.0f}% vs your {current_wr:.0f}%. "
                    f"Understand WHY, but don't blindly copy — your portfolio context is different."
                )

        # P&L comparison
        pnl_diff = current_pnl - peer_pnl
        if abs(pnl_diff) >= 500:
            if pnl_diff > 0:
                comparison.append(f"Your P&L (${current_pnl:+,.0f}) is ahead of peer (${peer_pnl:+,.0f}).")
            else:
                comparison.append(f"Your peer's P&L (${peer_pnl:+,.0f}) is ahead of yours (${current_pnl:+,.0f}).")

        # Asset type divergence
        peer_by_asset = peer_metrics.get("by_asset", {})
        current_by_asset = current_metrics.get("by_asset", {})
        for atype in set(list(peer_by_asset.keys()) + list(current_by_asset.keys())):
            p_stats = peer_by_asset.get(atype, {"wins": 0, "losses": 0, "total_pnl": 0})
            c_stats = current_by_asset.get(atype, {"wins": 0, "losses": 0, "total_pnl": 0})
            p_total = p_stats["wins"] + p_stats["losses"]
            c_total = c_stats["wins"] + c_stats["losses"]
            if p_total >= 2 and c_total >= 2:
                p_wr = p_stats["wins"] / p_total * 100
                c_wr = c_stats["wins"] / c_total * 100
                if p_wr - c_wr >= 20:
                    comparison.append(
                        f"This AI excels at {atype}: {p_wr:.0f}% win rate (${p_stats['total_pnl']:+,.0f}) "
                        f"vs your {c_wr:.0f}% (${c_stats['total_pnl']:+,.0f}). "
                        f"Consider why — but remember their entry prices and timing differ from yours."
                    )
                elif c_wr - p_wr >= 20:
                    comparison.append(
                        f"YOU outperform this AI at {atype}: {c_wr:.0f}% win rate vs their {p_wr:.0f}%. "
                        f"Trust your {atype} instincts — your approach is working."
                    )

        # Specific recent trades that diverged (one bought, other sold same symbol)
        peer_txs = tx_by_user.get(peer_uid, [])
        current_txs = tx_by_user.get(current_uid, [])

        # Look at last 7 days of trades for divergence
        recent_cutoff = (date.today() - timedelta(days=7)).isoformat()
        peer_recent = {
            (t["symbol"], t["side"]): t.get("reasoning", "")[:150]
            for t in peer_txs if t["created_at"][:10] >= recent_cutoff
        }
        current_recent = {
            (t["symbol"], t["side"]): t.get("reasoning", "")[:150]
            for t in current_txs if t["created_at"][:10] >= recent_cutoff
        }

        divergences = []
        for (sym, side), reasoning in peer_recent.items():
            opposite = "sell" if side == "buy" else "buy"
            if (sym, opposite) in current_recent:
                divergences.append({
                    "symbol": sym,
                    "peer_action": side,
                    "your_action": opposite,
                    "peer_reasoning": reasoning,
                })

        if divergences:
            comparison.append(
                "Recent strategy divergences (this AI made the OPPOSITE call — "
                "understand their reasoning, but their position and timing differ from yours):"
            )
            for d in divergences[:2]:
                # Add staleness warning for trades > 3 days old
                comparison.append(
                    f"  {d['symbol']}: You {d['your_action'].upper()}d, this AI {d['peer_action'].upper()}d. "
                    f"Their reasoning: \"{d['peer_reasoning']}\" "
                    f"(CAUTION: this trade already happened — the opportunity may have passed)"
                )

        # Peer's best trade (to learn from — but not copy blindly)
        peer_best = peer_metrics.get("best_trade")
        if peer_best and peer_best["pnl"] > 500:
            comparison.append(
                f"This AI's best recent trade: {peer_best['symbol']} for ${peer_best['pnl']:+,.0f} "
                f"({peer_best['pnl_pct']:+.1f}%) — note: this trade is ALREADY CLOSED. "
                f"The same setup may not exist today."
            )

        if comparison:
            lines.append(header)
            lines.extend(comparison)
            lines.append(
                "\nREMEMBER: This peer is another AI, not a human expert. "
                "They make mistakes too. You are competing against them. "
                "Learn from their data, but make the best decision for YOUR portfolio, "
                "YOUR current holdings, and TODAY's market conditions. "
                "Copying a trade that already happened days ago is usually WRONG — "
                "the price has already moved. Think independently. Decide for yourself."
            )

    return "\n".join(lines) if lines else ""


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


def _compute_portfolio_risk(portfolio: dict, personality_key: str = None, brief: dict | None = None, override_risk_params: dict | None = None) -> str:
    """Compute portfolio risk metrics: sector exposure, concentration, unrealized P&L.
    This gives AIs the self-awareness to manage risk like a professional.
    When personality_key is provided, includes risk rule alerts.
    When brief is provided, includes ATR-based stop suggestions and earnings warnings.
    override_risk_params can be passed for custom traders whose params aren't in PERSONALITIES."""
    positions = portfolio.get("positions", [])
    cash = portfolio.get("cash", 0)

    if not positions:
        return "No positions — you need to build a portfolio. Diversify across sectors."

    total_value = cash + sum(p["market_value"] for p in positions)
    if total_value == 0:
        return "Portfolio value is zero."

    # Get risk params for this personality
    risk_params = override_risk_params
    if not risk_params and personality_key and personality_key in PERSONALITIES:
        risk_params = PERSONALITIES[personality_key].get("risk_params", {})

    lines = []
    sell_alerts = []

    # Cash allocation + deployment pressure
    cash_pct = round(cash / total_value * 100, 1)
    lines.append(f"Cash allocation: {cash_pct}% (${cash:,.2f})")

    # Personality-specific cash targets — nudge overweight-cash traders to deploy
    cash_targets = {
        "vanilla": (10, 20),
        "steady_eddie": (15, 25),
        "yolo_bot": (0, 10),
        "contrarian_carl": (15, 25),
        "crypto_chad": (5, 20),
    }
    if personality_key and personality_key in cash_targets:
        target_min, target_max = cash_targets[personality_key]
        if cash_pct > target_max + 15:
            deploy_amount = cash - (total_value * target_max / 100)
            sell_alerts.append(
                f"💰 DEPLOY CAPITAL: You have {cash_pct:.0f}% cash — your strategy targets "
                f"{target_min}-{target_max}%. You have ${deploy_amount:,.0f} excess cash sitting idle. "
                f"This is paper trading with zero risk. Find opportunities matching your criteria "
                f"and SIZE UP your positions. Small $1-2k buys won't move the needle — "
                f"allocate 5-10% of portfolio per high-conviction trade."
            )
        elif cash_pct > target_max:
            lines.append(
                f"  ⚠ Above target cash ({target_min}-{target_max}%). "
                f"Look for opportunities to deploy ${cash - total_value * target_max / 100:,.0f}."
            )

    # Crypto-specific allocation pressure for Crypto Chad
    if personality_key == "crypto_chad":
        crypto_val = sum(p["market_value"] for p in positions if p.get("asset_type") == "crypto")
        crypto_pct = round(crypto_val / total_value * 100, 1) if total_value > 0 else 0
        if crypto_pct < 40:
            target_crypto_val = total_value * 0.6
            deficit = target_crypto_val - crypto_val
            sell_alerts.append(
                f"🪙 CRYPTO UNDERWEIGHT: You're at {crypto_pct:.0f}% crypto — your identity is "
                f"60-80% crypto. You need ~${deficit:,.0f} more in crypto (BTC, ETH, SOL, AVAX). "
                f"Buy aggressively — BTC and ETH are your core positions, each should be 15-20% of portfolio."
            )

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

        # Position aging pressure — progressive warnings before max_hold_days
        if risk_params and hold_days > 0 and "STALE" not in flags:
            max_days = risk_params.get("max_hold_days", 30)
            days_remaining = max_days - hold_days
            if days_remaining <= 5 and days_remaining > 0 and abs(pnl) < 5:
                flags.append("EXPIRING SOON")
                sell_alerts.append(
                    f"⏳ {sym}: only {days_remaining} days left before max hold ({max_days}d) "
                    f"with {pnl:+.1f}% return. Decide NOW: has your thesis played out?"
                )
            elif hold_days > max_days * 0.6 and abs(pnl) < 3:
                flags.append("AGING")

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

    # --- ATR-based dynamic stop suggestions ---
    if brief:
        stock_tech = brief.get("stock_technicals", {})
        crypto_tech = brief.get("crypto_technicals", {})
        all_tech = {**stock_tech, **crypto_tech}

        atr_lines = []
        for p in positions:
            sym = p["symbol"]
            t = all_tech.get(sym, {})
            atr = t.get("atr_14")
            if atr and p["current_price"] > 0:
                atr_pct = (atr / p["current_price"]) * 100
                suggested_stop = round(atr_pct * 2, 1)  # 2x ATR stop
                suggested_tp = round(atr_pct * 3, 1)    # 3x ATR target
                vol_label = "volatile" if atr_pct > 3 else "stable" if atr_pct < 1.5 else "moderate"
                atr_lines.append(
                    f"  {sym}: ATR ${atr:.2f} ({atr_pct:.1f}% of price, {vol_label}) "
                    f"→ suggested stop: -{suggested_stop}%, target: +{suggested_tp}%"
                )
        if atr_lines:
            lines.append("\n### ATR-BASED RISK SIZING (volatility-adjusted stops)")
            lines.append("Use these to set smarter stops — volatile assets need wider stops to avoid whipsaws:")
            lines.extend(atr_lines)

    # --- Earnings calendar warnings for held positions ---
    if brief:
        earnings = brief.get("earnings_calendar", [])
        if earnings:
            earning_syms = {e["symbol"]: e for e in earnings}
            earnings_warnings = []
            for p in positions:
                e = earning_syms.get(p["symbol"])
                if e:
                    eps_str = f", est EPS ${e['estimate_eps']:.2f}" if e.get("estimate_eps") else ""
                    earnings_warnings.append(
                        f"  ⚡ {p['symbol']} reports earnings {e['date']}{eps_str} — "
                        f"expect high volatility. You're holding {p.get('quantity', 0)} shares. "
                        f"Decide: take profits before, hold through, or reduce size."
                    )
            if earnings_warnings:
                lines.append("\n### EARNINGS EVENT RISK (positions with upcoming reports)")
                lines.extend(earnings_warnings)

    # --- Position aging summary ---
    aging_positions = [
        (sym, hold_days, pnl)
        for sym, pct, pnl, atype, hold_days in position_pcts
        if risk_params and hold_days > risk_params.get("max_hold_days", 30) * 0.6 and abs(pnl) < 3
    ]
    if aging_positions:
        lines.append("\n### POSITION AGING SUMMARY")
        lines.append("These positions have been held a long time with minimal return. Capital may be better deployed elsewhere:")
        for sym, days, pnl in aging_positions:
            max_days = risk_params.get("max_hold_days", 30) if risk_params else 30
            lines.append(
                f"  {sym}: {days}d held, {pnl:+.1f}% return "
                f"(max hold: {max_days}d, {max_days - days}d remaining). "
                f"Original thesis still valid?"
            )

    return "\n".join(lines)


async def _get_ai_trades(personality_key: str, model_key: str, brief: dict, portfolio: dict, trade_memory: str = "", session: str = "close", agentic_context_data: dict | None = None, custom_personality: dict | None = None) -> list[dict]:
    """Ask an AI model for its trading decisions."""
    settings = get_settings()
    personality = custom_personality if personality_key == "custom" else PERSONALITIES[personality_key]
    model_cfg = CUSTOM_TRADER_MODEL if model_key == "custom" else MODELS[model_key]

    # Portfolio risk analysis (with personality-specific risk alerts + ATR stops + earnings).
    # max_hold_days is jittered per model so same-personality traders don't all hit
    # the stale-position trigger on the same day.
    risk_params = _jittered_risk_params(personality.get("risk_params", {}), model_key)
    risk_analysis = _compute_portfolio_risk(portfolio, personality_key, brief=brief, override_risk_params=risk_params)

    # Build the user message via modular toolkit
    from app.services.rag_toolkit import assemble_toolkit_prompt

    user_msg = assemble_toolkit_prompt(
        personality_key=personality_key,
        personality_prompt=personality["prompt"],
        toolkit_config=personality.get("toolkit", []),
        brief=brief,
        portfolio=portfolio,
        risk_params=risk_params,
        risk_analysis=risk_analysis,
        trade_memory=trade_memory,
        agentic_data=agentic_context_data or {},
    )

    # Log prompt size per model (diagnostic for Issue #4: Mistral Small compliance)
    model_name = model_cfg.get("model_id", "unknown")
    prompt_chars = len(user_msg)
    prompt_tokens_est = prompt_chars // 4  # rough estimate
    print(f"[PROMPT_SIZE] {personality['name']} ({model_name}): {prompt_chars:,} chars (~{prompt_tokens_est:,} tokens), modules: {[t['module'] for t in personality.get('toolkit', [])]}")

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
        key_field = model_cfg.get("api_key_field", "mistral_api_key")
        api_key = getattr(settings, key_field, "") or settings.mistral_api_key
        if not api_key:
            raise Exception(f"{key_field.upper()} not configured")
        raw = await _call_mistral(model_cfg["model_id"], system_prompt, user_msg, api_key)
    elif api == "groq":
        if not settings.groq_api_key:
            raise Exception("GROQ_API_KEY not configured")
        raw = await _call_groq(model_cfg["model_id"], system_prompt, user_msg, settings.groq_api_key)
    elif api == "nvidia":
        if not settings.nvidia_api_key:
            raise Exception("NVIDIA_API_KEY not configured")
        raw = await _call_nvidia_nim(model_cfg["model_id"], system_prompt, user_msg, settings.nvidia_api_key)
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
            logger.warning("AI response 'trades' field is not a list: %s", type(trades))
            return [], []
        # Extract conditional orders (optional field)
        cond_orders = parsed.get("conditional_orders", [])
        if not isinstance(cond_orders, list):
            cond_orders = []
        return trades[:8], cond_orders[:3]  # Max 8 trades, 3 conditional orders
    except json.JSONDecodeError as e:
        logger.error("JSON parse failed for AI response: %s — raw (first 500 chars): %s", e, raw[:500])
        print(f"[PIPELINE ERROR] JSON parse failed: {e} — raw: {raw[:300]}")
        return [], []


# ---------------------------------------------------------------------------
# Trade execution (bypasses market hours for AI)
# ---------------------------------------------------------------------------

async def _execute_ai_trade(
    user_id: str,
    trade: dict,
    active_modules: set[str] | None = None,
    brief: dict | None = None,
    risk_params: dict | None = None,
    optimizer_sizing: dict | None = None,
) -> dict | None:
    """Execute a single trade for an AI trader. Returns result or None on failure.

    ATR-based position cap: For buys, limits dollar exposure so that a 2×ATR
    adverse move loses at most ``risk_per_trade_pct`` of portfolio value.
    Optimizer sizing: Additionally caps buys to the optimizer's suggested dollar amount.
    """
    from app.services.rag_toolkit import RAG_MODULES, detect_modules_from_text

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

    # Get current price
    quote = await get_quote(symbol, asset_type)
    if not quote:
        return None

    price = quote["price"]
    db = get_supabase_admin()

    # Get profile
    profile = db.table("profiles").select("cash_balance").eq("id", user_id).single().execute()
    cash = float(profile.data["cash_balance"])

    # --- ATR-based position cap (buys only) ---
    if side == "buy" and brief and price > 0:
        # Look up ATR for this symbol
        tech_data = brief.get("stock_technicals", {}).get(symbol) or brief.get("crypto_technicals", {}).get(symbol) or {}
        atr = tech_data.get("atr_14")
        if atr and atr > 0:
            atr_pct = atr / price  # ATR as fraction of price
            # Risk budget: lose at most N% of portfolio on a 2×ATR stop
            # Conservative personalities get tighter budgets
            max_position_pct = (risk_params or {}).get("max_position_pct", 15.0) / 100
            risk_per_trade = max_position_pct * 0.2  # risk 20% of max_position as loss budget
            portfolio_value = cash  # approximate (cash is dominant pre-buy)
            # max_dollars = portfolio_value * risk_per_trade / (2 * atr_pct)
            atr_stop_fraction = 2 * atr_pct
            if atr_stop_fraction > 0:
                max_dollars = portfolio_value * risk_per_trade / atr_stop_fraction
                max_dollars = min(max_dollars, portfolio_value * max_position_pct)  # still respect hard cap
                if asset_type == "stock":
                    max_qty = int(max_dollars / price)
                else:
                    max_qty = round(max_dollars / price, 8)
                if max_qty > 0 and quantity > max_qty:
                    original_qty = quantity
                    quantity = max_qty
                    trade["quantity"] = quantity
                    print(
                        f"[ATR_CAP] {symbol}: capped {original_qty} → {quantity} "
                        f"(ATR={atr:.2f}, ATR%={atr_pct*100:.1f}%, "
                        f"max${max_dollars:,.0f}, risk_budget={risk_per_trade*100:.1f}%)"
                    )

    # --- Optimizer-based position sizing cap (buys only) ---
    if side == "buy" and optimizer_sizing and price > 0:
        opt = optimizer_sizing.get(symbol)
        if opt:
            opt_dollars = opt.get("dollar_amount", 0)
            if opt_dollars > 0:
                if asset_type == "stock":
                    opt_qty = int(opt_dollars / price)
                else:
                    opt_qty = round(opt_dollars / price, 8)
                if opt_qty > 0 and quantity > opt_qty:
                    original_qty = quantity
                    quantity = opt_qty
                    trade["quantity"] = quantity
                    print(
                        f"[OPT_SIZE] {symbol}: capped {original_qty} → {quantity} "
                        f"(optimizer suggested ${opt_dollars:,.0f}, "
                        f"{opt.get('suggested_pct', 0)}% of portfolio)"
                    )

    if asset_type == "stock":
        quantity = int(quantity)  # ensure whole shares after cap

    total = round(price * quantity, 8)

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

        # Record transaction (reasoning + modules_used columns are nullable)
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
            # Validate cluster reference against actual brief themes
            cluster_ref = trade.get("cluster_ref", "")
            if cluster_ref and isinstance(cluster_ref, str) and brief:
                valid_themes = {
                    c["theme"] for c in (brief.get("headline_clusters") or [])
                }
                if cluster_ref in valid_themes:
                    reasoning = f"{reasoning} [Cluster: {cluster_ref}]"
                # else: silently drop — the LLM hallucinated a cluster name
            tx_data["reasoning"] = reasoning[:500]  # Cap at 500 chars

        # Determine which toolkit modules informed this trade
        raw_modules = trade.get("modules_used", [])
        if isinstance(raw_modules, list) and all(isinstance(m, str) for m in raw_modules):
            modules_used = [m for m in raw_modules if m in RAG_MODULES]
        else:
            modules_used = []
        # Fallback: detect from reasoning text if LLM omitted the field
        if not modules_used and reasoning:
            modules_used = detect_modules_from_text(reasoning, active_modules)
        # Filter to only modules this personality actually has
        if active_modules and modules_used:
            modules_used = [m for m in modules_used if m in active_modules]
        if modules_used:
            tx_data["modules_used"] = json.dumps(modules_used)

        tx = db.table("transactions").insert(tx_data).execute()

        return tx.data[0] if tx.data else None

    except Exception:
        return None


# ---------------------------------------------------------------------------
# Daily AI trading run
# ---------------------------------------------------------------------------

# Provider-specific rate limit delays (seconds between calls).
# All models now on Mistral API (2 keys, 10 traders each).
#   mistral (key 1): Mistral Large + Mistral Medium = 10 traders
#   mistral (key 2): Mistral Small + Mistral Large 2 = 10 traders
PROVIDER_DELAYS = {
    "gemini-pro": 3,
    "gemini-flash": 3,
    "mistral": 3,
    "llama": 3,
    "custom": 3,
}


def _record_pipeline_timing(
    db, *, phase: str, user_id: str | None, display_name: str | None,
    model_key: str | None, personality_key: str | None,
    started_at, completed_at, status: str, trades_executed: int | None = None,
    error_message: str | None = None,
) -> None:
    """Insert a row into pipeline_timings. Swallows exceptions so timing
    failures never break the pipeline."""
    try:
        duration = (completed_at - started_at).total_seconds()
        db.table("pipeline_timings").insert({
            "run_date": started_at.date().isoformat(),
            "phase": phase,
            "trader_id": user_id,
            "trader_name": display_name,
            "model_key": model_key,
            "personality_key": personality_key,
            "duration_seconds": round(duration, 2),
            "trades_executed": trades_executed,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "status": status,
            "error_message": error_message[:500] if error_message else None,
        }).execute()
        print(f"[TIMING] {phase} {display_name or 'n/a'}: {duration:.1f}s ({status})")
    except Exception as e:
        print(f"[TIMING] record failed: {e}")


async def _run_trader(
    db, brief: dict, profile: dict, session: str = "close",
    all_ai_positions: list[dict] | None = None,
    performance_intel: dict[str, str] | None = None,
) -> dict:
    """Run a single AI trader: get portfolio, ask LLM, execute trades."""
    from datetime import datetime, timezone
    started_at = datetime.now(timezone.utc)
    user_id = profile["id"]
    display_name = profile["display_name"]
    model_key = profile.get("ai_model", "")
    print(f"[PIPELINE] Starting trader: {display_name} (model={model_key})")

    # Determine personality from display name (or custom trader config)
    personality_key = None
    custom_personality = None
    for pkey, pinfo in PERSONALITIES.items():
        if pinfo["name"] in display_name:
            personality_key = pkey
            break

    if not personality_key and model_key == "custom":
        # Load custom trader config from DB
        try:
            ct = db.table("custom_traders").select("*").eq("profile_id", user_id).eq("is_active", True).single().execute()
            if ct.data:
                cfg = ct.data
                personality_key = "custom"
                # Build asset focus instruction
                focus_text = ""
                if cfg["asset_focus"] == "stocks":
                    focus_text = "You ONLY trade stocks. Do NOT buy or sell any crypto. "
                elif cfg["asset_focus"] == "crypto":
                    focus_text = "You ONLY trade crypto. Do NOT buy or sell any stocks. "

                custom_personality = {
                    "name": cfg["name"],
                    "prompt": focus_text + cfg["strategy_prompt"],
                    "risk_params": CUSTOM_RISK_PRESETS.get(cfg["risk_level"], CUSTOM_RISK_PRESETS["medium"]),
                    "toolkit": [
                        {"module": m, "weight": 10 - i}
                        for i, m in enumerate(cfg["toolkit_modules"])
                    ],
                }
        except Exception as e:
            print(f"[PIPELINE SKIP] {display_name}: failed to load custom config: {e}")

    if not personality_key or (model_key not in MODELS and model_key != "custom"):
        print(f"[PIPELINE SKIP] {display_name}: unknown personality or model ({model_key})")
        _record_pipeline_timing(
            db, phase="trading", user_id=user_id, display_name=display_name,
            model_key=model_key, personality_key=personality_key,
            started_at=started_at, completed_at=datetime.now(timezone.utc),
            status="skipped", error_message="unknown personality or model",
        )
        return {
            "trader": display_name,
            "status": "skipped",
            "reason": "unknown personality or model",
        }

    # Guard: skip if this trader already traded today
    today_str = date.today().isoformat()
    existing = (
        db.table("transactions")
        .select("id")
        .eq("user_id", user_id)
        .gte("created_at", f"{today_str}T00:00:00")
        .limit(1)
        .execute()
    )
    if existing.data:
        print(f"[PIPELINE SKIP] {display_name}: already traded today")
        _record_pipeline_timing(
            db, phase="trading", user_id=user_id, display_name=display_name,
            model_key=model_key, personality_key=personality_key,
            started_at=started_at, completed_at=datetime.now(timezone.utc),
            status="skipped", error_message="already traded today",
        )
        return {
            "trader": display_name,
            "status": "skipped",
            "reason": "already traded today",
        }

    try:
        # Get portfolio state
        portfolio = await _get_ai_portfolio(db, user_id)

        # Build trading memory from recent history
        recent_trades = _get_ai_trade_history(db, user_id, limit=15)
        trade_memory = _format_trade_memory(recent_trades, portfolio["positions"])

        # Append reflection lessons if available
        try:
            from app.services.reflection import get_reflection_memory
            reflections = get_reflection_memory(db, user_id, limit=5)
            if reflections:
                trade_memory += "\n\n" + reflections
        except Exception:
            pass

        # Inject conditional order context (pending + recently resolved)
        try:
            from app.services.conditional_orders import get_pending_orders, get_recent_triggered_orders
            pending_conds = get_pending_orders(user_id)
            if pending_conds:
                lines = ["\n\n## Your Pending Conditional Orders"]
                for co in pending_conds:
                    if co["order_type"] == "trailing_stop":
                        lines.append(
                            f"  {co['order_type'].upper()} {co['side']} {co['quantity']} {co['symbol']} "
                            f"(trail {co['trail_pct']}%, HWM: ${float(co['high_water_mark'] or 0):.2f}) — {co['reasoning']}"
                        )
                    else:
                        lines.append(
                            f"  {co['order_type'].upper()} {co['side']} {co['quantity']} {co['symbol']} "
                            f"@ ${float(co['trigger_price']):.2f} — {co['reasoning']}"
                        )
                lines.append("These are still live. Don't duplicate them with new orders on the same symbol.")
                trade_memory += "\n".join(lines)

            recent_conds = get_recent_triggered_orders(user_id, limit=5)
            if recent_conds:
                lines = ["\n\n## Recently Resolved Conditional Orders"]
                for co in recent_conds:
                    status = co["status"].upper()
                    if co["status"] == "executed":
                        lines.append(
                            f"  {status}: {co['order_type'].upper()} {co['side']} {co['symbol']} "
                            f"@ ${float(co['execution_price']):.2f} — {co['reasoning']}"
                        )
                    elif co["status"] == "expired":
                        lines.append(
                            f"  {status}: {co['order_type'].upper()} {co['symbol']} never triggered — "
                            f"was your target realistic?"
                        )
                    else:
                        lines.append(
                            f"  {status}: {co['order_type'].upper()} {co['symbol']} — {co['reasoning']}"
                        )
                trade_memory += "\n".join(lines)
        except Exception:
            pass

        # --- Agentic Pipeline Steps 3 & 4 (conditional on toolkit) ---
        personality = custom_personality if personality_key == "custom" else PERSONALITIES[personality_key]
        model_cfg = CUSTOM_TRADER_MODEL if model_key == "custom" else MODELS[model_key]
        toolkit_modules = {t["module"] for t in personality.get("toolkit", [])}

        held_symbols = [p["symbol"] for p in portfolio["positions"]]
        candle_data: dict[str, list[dict]] = {}
        pattern_results: dict[str, dict] = {}
        correlations: list[dict] = []
        allocation: dict = {}

        # Step 3: Pattern Recognition (only if "patterns" in toolkit)
        if "patterns" in toolkit_modules:
            for sym in held_symbols[:10]:
                candles = await get_stock_candles(sym, days=60)
                if not candles:
                    candles = await get_crypto_history(sym, days=60)
                if candles and len(candles) >= 5:
                    candle_data[sym] = candles
                    pattern_results[sym] = analyze_patterns(candles, symbol=sym)

        # Step 4: Portfolio Optimizer (only if "optimizer" in toolkit)
        if "optimizer" in toolkit_modules:
            # Need candle data for correlations even if patterns not in toolkit
            if not candle_data:
                for sym in held_symbols[:10]:
                    candles = await get_stock_candles(sym, days=60)
                    if not candles:
                        candles = await get_crypto_history(sym, days=60)
                    if candles and len(candles) >= 5:
                        candle_data[sym] = candles

            all_signals = {}
            for sym, tech in brief.get("stock_technicals", {}).items():
                if tech.get("signal"):
                    all_signals[sym] = tech["signal"]
            for sym, tech in brief.get("crypto_technicals", {}).items():
                if tech.get("signal"):
                    all_signals[sym] = tech["signal"]

            correlations = compute_portfolio_correlations(portfolio["positions"], candle_data)

            risk_params = personality.get("risk_params", {})
            total_value = portfolio["cash"] + sum(p.get("market_value", 0) for p in portfolio["positions"])
            allocation = compute_target_allocation(
                all_signals, personality_key, risk_params,
                portfolio["positions"], portfolio["cash"], total_value,
            )

        # Confidence-weighted position sizing (only if optimizer in toolkit)
        sizing: dict = {}
        if "optimizer" in toolkit_modules and all_signals:
            from app.services.portfolio_optimizer import compute_position_sizes
            stock_vol = brief.get("stock_volatility", {})
            sizing = compute_position_sizes(
                all_signals, stock_vol, personality_key, risk_params, total_value, portfolio["cash"],
            )

        # Cross trader awareness + peer exit warnings
        cross_trader_text = ""
        if all_ai_positions:
            cross_trader_text = _format_cross_trader_positions(all_ai_positions, user_id, brief)
        try:
            peer_exit = _compute_peer_exit_warnings(db, user_id)
            if peer_exit:
                cross_trader_text = f"{cross_trader_text}\n\n{peer_exit}" if cross_trader_text else peer_exit
        except Exception as e:
            print(f"[PEER_EXIT] {user_id}: warning computation failed: {e}")

        # Performance intelligence (self-assessment + peer learning)
        perf_intel_text = ""
        if performance_intel:
            perf_intel_text = performance_intel.get(user_id, "")

        # Trade context (historical track record — only if module active)
        trade_context = None
        if "trade_context" in toolkit_modules:
            try:
                trade_context = _compute_trade_context(db, user_id)
            except Exception:
                pass

        # Dynamic risk (drawdown-aware sizing — only if module active)
        dynamic_risk = None
        if "dynamic_risk" in toolkit_modules:
            try:
                dynamic_risk = _compute_dynamic_risk(db, user_id)
            except Exception:
                pass

        # Trade discipline scoring (always computed if positions exist)
        discipline = None
        try:
            discipline = _compute_discipline_score(db, user_id, personality_key, portfolio)
        except Exception:
            pass

        # Ask AI for trades (with modular toolkit prompt)
        agentic_data = {
            "pattern_results": pattern_results,
            "correlations": correlations,
            "allocation": allocation,
            "sizing": sizing,
            "cross_trader_text": cross_trader_text,
            "performance_intel": perf_intel_text,
            "trade_context": trade_context,
            "dynamic_risk": dynamic_risk,
            "discipline": discipline,
        }
        trades, cond_orders = await _get_ai_trades(personality_key, model_key, brief, portfolio, trade_memory, session=session, agentic_context_data=agentic_data, custom_personality=custom_personality)

        # Execute trades (with ATR-based position cap + optimizer sizing)
        trade_risk_params = _jittered_risk_params(personality.get("risk_params", {}), model_key)
        executed = []
        for trade in trades:
            result = await _execute_ai_trade(
                user_id, trade, active_modules=toolkit_modules,
                brief=brief, risk_params=trade_risk_params,
                optimizer_sizing=sizing,
            )
            if result:
                entry = {
                    "symbol": trade["symbol"],
                    "side": trade["side"],
                    "quantity": trade["quantity"],
                }
                if trade.get("reasoning"):
                    entry["reasoning"] = trade["reasoning"]
                executed.append(entry)

        # Save conditional orders (if any)
        saved_conds = []
        if cond_orders:
            try:
                from app.services.conditional_orders import save_conditional_orders
                saved_conds = save_conditional_orders(user_id, cond_orders)
                if saved_conds:
                    print(f"[PIPELINE] {display_name}: saved {len(saved_conds)} conditional orders")
            except Exception as e:
                print(f"[PIPELINE] {display_name}: conditional order save failed: {e}")

        print(f"[PIPELINE OK] {display_name}: {len(trades)} proposed, {len(executed)} executed, {len(saved_conds)} conditional")
        _record_pipeline_timing(
            db, phase="trading", user_id=user_id, display_name=display_name,
            model_key=model_key, personality_key=personality_key,
            started_at=started_at, completed_at=datetime.now(timezone.utc),
            status="ok", trades_executed=len(executed),
        )
        return {
            "trader": display_name,
            "status": "ok",
            "trades_proposed": len(trades),
            "trades_executed": len(executed),
            "conditional_orders_saved": len(saved_conds),
            "trades": executed,
        }

    except Exception as e:
        logger.error("Trader %s failed: %s", display_name, e)
        print(f"[PIPELINE ERROR] Trader {display_name} failed: {e}")
        _record_pipeline_timing(
            db, phase="trading", user_id=user_id, display_name=display_name,
            model_key=model_key, personality_key=personality_key,
            started_at=started_at, completed_at=datetime.now(timezone.utc),
            status="error", error_message=str(e),
        )
        return {
            "trader": display_name,
            "status": "error",
            "error": str(e)[:200],
        }


async def _run_provider_batch(
    db, brief: dict, profiles: list[dict], delay: int, session: str = "close",
    all_ai_positions: list[dict] | None = None,
    performance_intel: dict[str, str] | None = None,
) -> list[dict]:
    """Run a batch of traders that share the same API provider, sequentially
    with the appropriate delay between calls."""
    model_key = profiles[0].get("ai_model", "unknown") if profiles else "empty"
    print(f"[PIPELINE BATCH] Starting {len(profiles)} traders for provider={model_key}, delay={delay}s")
    results = []
    for i, profile in enumerate(profiles):
        result = await _run_trader(db, brief, profile, session=session, all_ai_positions=all_ai_positions, performance_intel=performance_intel)
        results.append(result)
        # Delay between calls (skip after last one)
        if i < len(profiles) - 1:
            await asyncio.sleep(delay)
    return results


async def run_ai_trading(session: str = "close") -> dict:
    """Run all AI traders for today, grouped by API provider for optimal speed.

    Groups traders by model key and runs batches with provider-specific delays.
    Currently all models use Groq/Mistral APIs (~3s delay each).
    NOTE: When Gemini is re-enabled, restore the phased scheduling
    (Gemini Pro at 35s delay was the bottleneck).
    """
    print(f"[PIPELINE START] AI trading session={session}")
    brief = await get_latest_brief()
    if not brief:
        print("[PIPELINE ERROR] No market brief available")
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

    # Fetch all AI positions once for cross trader awareness (1 DB query)
    all_ai_positions = []
    try:
        ai_user_ids = [p["id"] for p in ai_profiles.data]
        pos_resp = (
            db.table("positions")
            .select("user_id, symbol, quantity")
            .gt("quantity", 0)
            .execute()
        )
        # Attach display_name to each position
        name_map = {p["id"]: p["display_name"] for p in ai_profiles.data}
        for pos in pos_resp.data:
            if pos["user_id"] in name_map:
                pos["display_name"] = name_map[pos["user_id"]]
                all_ai_positions.append(pos)
    except Exception:
        all_ai_positions = []

    # Build performance intelligence once for all traders (1 batch of DB queries)
    performance_intel: dict[str, str] = {}
    try:
        performance_intel = build_performance_intelligence(db)
        if performance_intel:
            print(f"[PIPELINE] Built performance intelligence for {len(performance_intel)} traders")
    except Exception as e:
        print(f"[PIPELINE] Performance intel failed (non-blocking): {e}")
        performance_intel = {}

    # Group profiles by model key (= API provider)
    by_model: dict[str, list[dict]] = {}
    for profile in ai_profiles.data:
        model_key = profile.get("ai_model", "unknown")
        by_model.setdefault(model_key, []).append(profile)

    # NOTE: gemini-flash and gemini-pro keys are now routed to Groq.
    # When Gemini is re-enabled, restore sequential phasing for its API.
    all_results = []

    # Pop gemini-keyed models (run sequentially for historical reasons / future Gemini re-enable)
    gemini_pro = by_model.pop("gemini-pro", [])
    gemini_flash = by_model.pop("gemini-flash", [])

    # Remaining models run in parallel batches
    non_gemini_batches = []
    for model_key, profiles in by_model.items():
        delay = PROVIDER_DELAYS.get(model_key, 5)
        non_gemini_batches.append(
            _run_provider_batch(db, brief, profiles, delay, session=session, all_ai_positions=all_ai_positions, performance_intel=performance_intel)
        )

    # Run Gemini (sequential) in parallel with all non-Gemini providers
    async def _run_all_gemini():
        results = []
        if gemini_pro:
            results.extend(
                await _run_provider_batch(db, brief, gemini_pro, PROVIDER_DELAYS["gemini-pro"], session=session, all_ai_positions=all_ai_positions, performance_intel=performance_intel)
            )
        if gemini_flash:
            results.extend(
                await _run_provider_batch(db, brief, gemini_flash, PROVIDER_DELAYS["gemini-flash"], session=session, all_ai_positions=all_ai_positions, performance_intel=performance_intel)
            )
        return results

    # Gather: Gemini batch + all non-Gemini batches run concurrently
    # return_exceptions=True prevents one batch failure from cancelling others
    gathered = await asyncio.gather(
        _run_all_gemini(),
        *non_gemini_batches,
        return_exceptions=True,
    )

    print(f"[PIPELINE] All batches complete. Flattening results.")
    # Flatten results
    for batch_result in gathered:
        if isinstance(batch_result, BaseException):
            print(f"[PIPELINE ERROR] Batch failed with: {batch_result}")
        elif isinstance(batch_result, list):
            all_results.extend(batch_result)

    # Auto-snapshot all portfolios after trading completes
    try:
        from app.services.snapshots import take_all_snapshots
        snapshot_count = await take_all_snapshots()
    except Exception:
        snapshot_count = 0

    # Notify users who follow AI traders
    try:
        from app.services.notifications import notify_ai_trades
        notify_ai_trades(all_results)
    except Exception as e:
        logger.error("Failed to send AI trade notifications: %s", e)

    return {
        "date": brief.get("date", date.today().isoformat()),
        "session": session,
        "traders_processed": len(all_results),
        "snapshots_created": snapshot_count,
        "results": all_results,
    }
