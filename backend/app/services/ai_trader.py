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
}

# All 10 AI traders: 5 personalities x 2 models
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
2. Today's market brief (prices, movers, news)
3. Your current portfolio (cash + positions)

Respond with a JSON object containing a list of trades to execute today.
Rules:
- You can buy or sell stocks and crypto from the supported list only.
- You cannot spend more cash than you have.
- You cannot sell more shares/coins than you own.
- Each trade needs: symbol, asset_type ("stock" or "crypto"), side ("buy" or "sell"), quantity (number).
- For stocks, quantity must be a whole number >= 1.
- For crypto, quantity can be a decimal (minimum 0.001).
- You may choose to make 0 trades if you see no good opportunities.
- Maximum 5 trades per day.
- Think about position sizing — don't put everything into one trade.

Respond ONLY with valid JSON in this exact format, no other text:
{"trades": [{"symbol": "AAPL", "asset_type": "stock", "side": "buy", "quantity": 10}]}

If no trades: {"trades": []}
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
            "maxOutputTokens": 1024,
            "responseMimeType": "application/json",
        },
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url,
            params={"key": api_key},
            json=payload,
        )
        if resp.status_code != 200:
            raise Exception(f"Gemini {model_id} error {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]


async def _get_ai_trades(personality_key: str, model_key: str, brief: dict, portfolio: dict) -> list[dict]:
    """Ask an AI model for its trading decisions."""
    settings = get_settings()
    personality = PERSONALITIES[personality_key]
    model_cfg = MODELS[model_key]

    # Build the user message
    supported_stocks = [{"symbol": s, "name": n} for s, n in TOP_STOCKS.items()]
    supported_crypto = [{"symbol": s, "name": c["name"]} for s, c in CRYPTO_MAP.items()]

    user_msg = f"""## Your Strategy
{personality['prompt']}

## Today's Market Brief ({brief.get('date', 'today')})

### Top Gainers
{json.dumps(brief.get('top_gainers', []), indent=2)}

### Top Losers
{json.dumps(brief.get('top_losers', []), indent=2)}

### Market News Headlines
{json.dumps([n['headline'] for n in brief.get('news', [])[:10]], indent=2)}

### Supported Stocks
{json.dumps(supported_stocks, indent=2)}

### Supported Crypto
{json.dumps(supported_crypto, indent=2)}

## Your Current Portfolio
Cash: ${portfolio['cash']:,.2f}
Positions:
{json.dumps(portfolio['positions'], indent=2) if portfolio['positions'] else 'None — you have no positions yet.'}

What trades do you want to make today?"""

    # Call the right API
    if model_cfg["api"] == "gemini":
        if not settings.gemini_api_key:
            raise Exception("GEMINI_API_KEY not configured")
        raw = await _call_gemini(model_cfg["model_id"], TRADE_SYSTEM, user_msg, settings.gemini_api_key)
    else:
        raise Exception(f"Unknown API: {model_cfg['api']}")

    # Parse response
    try:
        parsed = json.loads(raw)
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

            # Ask AI for trades
            trades = await _get_ai_trades(personality_key, model_key, brief, portfolio)

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
