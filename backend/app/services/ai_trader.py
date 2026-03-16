import asyncio
import json
import httpx
from datetime import date

from app.config import get_settings
from app.services.market_brief import get_latest_brief
from app.services.market_data import get_quote, TOP_STOCKS, CRYPTO_MAP
from app.services.supabase_client import get_supabase_admin

# ---------------------------------------------------------------------------
# Personality definitions
# ---------------------------------------------------------------------------

PERSONALITIES = {
    "vanilla": {
        "name": "Vanilla",
        "prompt": (
            "You are an AI trader. Your only goal is to maximize portfolio returns. "
            "Analyze the market data and make the best trading decisions you can. "
            "No specific strategy — just make money."
        ),
    },
    "steady_eddie": {
        "name": "Steady Eddie",
        "prompt": (
            "You are a conservative AI trader called Steady Eddie. "
            "You prefer blue-chip stocks, diversification, and capital preservation. "
            "You trade infrequently and avoid volatile assets. "
            "You'd rather miss a rally than catch a crash."
        ),
    },
    "yolo_bot": {
        "name": "YOLO Bot",
        "prompt": (
            "You are an aggressive momentum trader called YOLO Bot. "
            "You chase trends, trade frequently, and make concentrated bets. "
            "You love volatility and aren't afraid of big swings. "
            "Go big or go home."
        ),
    },
    "contrarian_carl": {
        "name": "Contrarian Carl",
        "prompt": (
            "You are a contrarian AI trader called Contrarian Carl. "
            "You buy when the market is fearful and sell when it's greedy. "
            "You look for oversold stocks to buy and overbought ones to sell. "
            "If everyone is bullish, you get cautious. If everyone is panicking, you buy."
        ),
    },
    "crypto_chad": {
        "name": "Crypto Chad",
        "prompt": (
            "You are a crypto-focused AI trader called Crypto Chad. "
            "You strongly favor cryptocurrency over stocks. "
            "You follow crypto sentiment, narrative cycles, and momentum. "
            "You believe in the long-term potential of digital assets."
        ),
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
        "model_id": "llama-3.3-70b",
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
You are managing a paper trading portfolio. You will receive:
1. Your personality/strategy description
2. Today's market brief (prices, movers, news, fundamentals, technicals)
3. Your current portfolio (cash + positions)
4. Your recent trading history and performance

Use ALL the data provided to make informed decisions:
- Fundamentals (PE ratio, market cap, analyst consensus) tell you about valuation
- Technicals (RSI, SMA, momentum) tell you about price trends and timing
- Earnings calendar warns you about upcoming volatility events
- Your past trade results tell you what's been working or failing

Rules:
- You can buy or sell stocks and crypto from the supported list only.
- You cannot spend more cash than you have.
- You cannot sell more shares/coins than you own.
- Each trade needs: symbol, asset_type ("stock" or "crypto"), side ("buy" or "sell"), quantity (number).
- For stocks, quantity must be a whole number >= 1.
- For crypto, quantity can be a decimal (minimum 0.001).
- Crypto markets are open 24/7 — you can always trade crypto regardless of day or time.
- Stock markets are only open Mon-Fri, but you can still place stock trades here anytime.
- You MUST make at least 1 trade every day. This is paper trading with fake money — there is zero risk. Not trading is the worst outcome.
- Maximum 5 trades per day.
- Think about position sizing — don't put everything into one trade.
- If you have no positions yet, buy something! Spread across 3-5 assets.

Respond ONLY with valid JSON in this exact format, no other text:
{"trades": [{"symbol": "AAPL", "asset_type": "stock", "side": "buy", "quantity": 10}]}
"""


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

    positions = []
    for p in positions_resp.data:
        quote = await get_quote(p["symbol"], p["asset_type"])
        current_price = quote["price"] if quote else float(p["avg_cost_basis"])
        qty = float(p["quantity"])
        positions.append({
            "symbol": p["symbol"],
            "asset_type": p["asset_type"],
            "quantity": qty,
            "avg_cost": float(p["avg_cost_basis"]),
            "current_price": current_price,
            "market_value": round(qty * current_price, 2),
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
        return "No trading history yet. This is your first day."

    lines = ["Recent trades (newest first):"]
    for t in trades[:10]:
        day = t["created_at"][:10] if t.get("created_at") else "?"
        lines.append(
            f"  {day}: {t['side'].upper()} {t['quantity']} {t['symbol']} @ ${t['price']:,.2f}"
        )

    # Summarize position P&L
    if positions:
        lines.append("\nCurrent position performance:")
        for p in positions:
            pnl_pct = ((p["current_price"] / p["avg_cost"]) - 1) * 100
            direction = "up" if pnl_pct >= 0 else "down"
            lines.append(
                f"  {p['symbol']}: {direction} {abs(pnl_pct):.1f}% (bought avg ${p['avg_cost']:,.2f}, now ${p['current_price']:,.2f})"
            )

    return "\n".join(lines)


def _format_enriched_brief(brief: dict) -> str:
    """Format the enriched market brief sections for the AI prompt."""
    sections = []

    # Fundamentals for notable stocks
    fundamentals = brief.get("fundamentals", {})
    if fundamentals:
        fund_lines = []
        for sym, f in list(fundamentals.items())[:15]:
            parts = []
            if f.get("pe_ratio"):
                parts.append(f"PE {f['pe_ratio']:.1f}")
            if f.get("beta"):
                parts.append(f"Beta {f['beta']:.2f}")
            if f.get("dividend_yield"):
                parts.append(f"Div {f['dividend_yield']:.1f}%")
            if f.get("52w_high") and f.get("52w_low"):
                parts.append(f"52w ${f['52w_low']:.0f}-${f['52w_high']:.0f}")
            if parts:
                fund_lines.append(f"  {sym}: {', '.join(parts)}")
        if fund_lines:
            sections.append("### Stock Fundamentals\n" + "\n".join(fund_lines))

    # Analyst recommendations
    recs = brief.get("analyst_recommendations", {})
    if recs:
        rec_lines = []
        for sym, r in list(recs.items())[:15]:
            total = r["buy"] + r["hold"] + r["sell"]
            if total > 0:
                rec_lines.append(
                    f"  {sym}: {r['buy']} Buy / {r['hold']} Hold / {r['sell']} Sell"
                )
        if rec_lines:
            sections.append("### Analyst Consensus\n" + "\n".join(rec_lines))

    # Earnings calendar
    earnings = brief.get("earnings_calendar", [])
    if earnings:
        earn_lines = [f"  {e['symbol']} reports {e['date']}" for e in earnings[:10]]
        sections.append("### Upcoming Earnings (next 7 days)\n" + "\n".join(earn_lines))

    # Technical indicators
    technicals = brief.get("stock_technicals", {})
    if technicals:
        tech_lines = []
        for sym, t in list(technicals.items())[:15]:
            parts = []
            if "rsi_14" in t:
                label = "OVERBOUGHT" if t["rsi_14"] > 70 else "OVERSOLD" if t["rsi_14"] < 30 else ""
                parts.append(f"RSI {t['rsi_14']}{' ' + label if label else ''}")
            if "vs_sma_20" in t:
                parts.append(f"{'above' if t['vs_sma_20'] > 0 else 'below'} SMA20 by {abs(t['vs_sma_20']):.1f}%")
            if "7d_return" in t:
                parts.append(f"7d {t['7d_return']:+.1f}%")
            if parts:
                tech_lines.append(f"  {sym}: {', '.join(parts)}")
        if tech_lines:
            sections.append("### Technical Indicators\n" + "\n".join(tech_lines))

    # Crypto market data
    crypto_data = brief.get("crypto_market_data", {})
    if crypto_data:
        crypto_lines = []
        for sym, c in list(crypto_data.items())[:10]:
            parts = []
            if c.get("market_cap_rank"):
                parts.append(f"Rank #{c['market_cap_rank']}")
            if c.get("market_cap_b"):
                parts.append(f"MCap ${c['market_cap_b']}B")
            if c.get("ath_drop_pct") is not None:
                parts.append(f"{c['ath_drop_pct']}% below ATH")
            if parts:
                crypto_lines.append(f"  {sym}: {', '.join(parts)}")
        if crypto_lines:
            sections.append("### Crypto Market Data\n" + "\n".join(crypto_lines))

    return "\n\n".join(sections) if sections else ""


async def _get_ai_trades(personality_key: str, model_key: str, brief: dict, portfolio: dict, trade_memory: str = "") -> list[dict]:
    """Ask an AI model for its trading decisions."""
    settings = get_settings()
    personality = PERSONALITIES[personality_key]
    model_cfg = MODELS[model_key]

    # Build the user message
    supported_stocks = [{"symbol": s, "name": n} for s, n in TOP_STOCKS.items()]
    supported_crypto = [{"symbol": s, "name": c["name"]} for s, c in CRYPTO_MAP.items()]

    enriched_sections = _format_enriched_brief(brief)

    user_msg = f"""## Your Strategy
{personality['prompt']}

## Today's Market Brief ({brief.get('date', 'today')})

### Top Gainers
{json.dumps(brief.get('top_gainers', []), indent=2)}

### Top Losers
{json.dumps(brief.get('top_losers', []), indent=2)}

### Market News Headlines
{json.dumps([n['headline'] for n in brief.get('news', [])[:10]], indent=2)}

{enriched_sections}

### Supported Stocks
{json.dumps(supported_stocks, indent=2)}

### Supported Crypto
{json.dumps(supported_crypto, indent=2)}

## Your Current Portfolio
Cash: ${portfolio['cash']:,.2f}
Positions:
{json.dumps(portfolio['positions'], indent=2) if portfolio['positions'] else 'None — you have no positions yet.'}

## Your Trading Memory
{trade_memory}

What trades do you want to make today?"""

    # Call the right API
    api = model_cfg["api"]
    if api == "gemini":
        if not settings.gemini_api_key:
            raise Exception("GEMINI_API_KEY not configured")
        raw = await _call_gemini(model_cfg["model_id"], TRADE_SYSTEM, user_msg, settings.gemini_api_key)
    elif api == "mistral":
        if not settings.mistral_api_key:
            raise Exception("MISTRAL_API_KEY not configured")
        raw = await _call_mistral(model_cfg["model_id"], TRADE_SYSTEM, user_msg, settings.mistral_api_key)
    elif api == "cerebras":
        if not settings.cerebras_api_key:
            raise Exception("CEREBRAS_API_KEY not configured")
        raw = await _call_cerebras(model_cfg["model_id"], TRADE_SYSTEM, user_msg, settings.cerebras_api_key)
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
        return trades[:5]  # Max 5 trades
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

        # Record transaction
        tx = db.table("transactions").insert({
            "user_id": user_id,
            "symbol": symbol,
            "asset_type": asset_type,
            "side": side,
            "quantity": quantity,
            "price": price,
            "total": total,
        }).execute()

        return tx.data[0] if tx.data else None

    except Exception:
        return None


# ---------------------------------------------------------------------------
# Daily AI trading run
# ---------------------------------------------------------------------------

async def run_ai_trading() -> dict:
    """Run all AI traders for today. Returns summary."""
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

    results = []
    for profile in ai_profiles.data:
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
            results.append({
                "trader": display_name,
                "status": "skipped",
                "reason": "unknown personality or model",
            })
            continue

        try:
            # Get portfolio state
            portfolio = await _get_ai_portfolio(db, user_id)

            # Build trading memory from recent history
            recent_trades = _get_ai_trade_history(db, user_id, limit=15)
            trade_memory = _format_trade_memory(recent_trades, portfolio["positions"])

            # Ask AI for trades
            trades = await _get_ai_trades(personality_key, model_key, brief, portfolio, trade_memory)

            # Execute trades
            executed = []
            for trade in trades:
                result = await _execute_ai_trade(user_id, trade)
                if result:
                    executed.append({
                        "symbol": trade["symbol"],
                        "side": trade["side"],
                        "quantity": trade["quantity"],
                    })

            results.append({
                "trader": display_name,
                "status": "ok",
                "trades_proposed": len(trades),
                "trades_executed": len(executed),
                "trades": executed,
            })

        except Exception as e:
            results.append({
                "trader": display_name,
                "status": "error",
                "error": str(e)[:200],
            })

        # Rate limit: Gemini Pro allows 2 RPM, Flash 15 RPM.
        # 35s delay keeps us safe for Pro (< 2 per minute).
        await asyncio.sleep(35)

    return {
        "date": brief.get("date", date.today().isoformat()),
        "traders_processed": len(results),
        "results": results,
    }
