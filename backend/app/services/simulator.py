"""Historical Replay Simulator.

Replays AI traders through stored market briefs to A/B test prompt changes,
module weights, risk parameters, and model swaps without affecting production.

Virtual portfolios are tracked in sim_ tables. Real market briefs from
the market_briefs table provide the data — no live API calls needed.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import date, timedelta

import httpx

from app.config import get_settings
from app.services.supabase_client import get_supabase_admin
from app.services.ai_trader import (
    MODELS,
    PERSONALITIES,
    TRADE_SYSTEM,
    SESSION_CONTEXTS,
    _call_mistral,
    _compute_portfolio_risk,
    _format_trade_memory,
)
from app.services.market_data import TOP_STOCKS, CRYPTO_MAP
from app.services.rag_toolkit import assemble_toolkit_prompt, detect_modules_from_text, RAG_MODULES


# ---------------------------------------------------------------------------
# Price resolution from stored briefs (no live API calls)
# ---------------------------------------------------------------------------

def _get_price_from_brief(brief: dict, symbol: str, asset_type: str) -> float | None:
    """Look up a symbol's price from a stored market brief."""
    if asset_type == "stock":
        for stock in brief.get("stocks", []):
            if stock.get("symbol") == symbol:
                return stock.get("price")
    elif asset_type == "crypto":
        for coin in brief.get("crypto", []):
            if coin.get("symbol") == symbol:
                return coin.get("price")
    return None


# ---------------------------------------------------------------------------
# Virtual portfolio (in-memory, mirrors _get_ai_portfolio output)
# ---------------------------------------------------------------------------

class VirtualPortfolio:
    """In-memory portfolio that mirrors the real portfolio structure."""

    def __init__(self, cash: float = 100_000.0):
        self.cash = cash
        self.positions: dict[str, dict] = {}  # symbol -> {asset_type, quantity, avg_cost, first_buy_date}
        self.trade_log: list[dict] = []

    def snapshot(self, brief: dict) -> dict:
        """Compute total value using prices from the brief."""
        invested = 0.0
        for sym, pos in self.positions.items():
            price = _get_price_from_brief(brief, sym, pos["asset_type"])
            if price is None:
                price = pos["avg_cost"]  # fallback to cost basis
            invested += pos["quantity"] * price
        return {
            "cash": round(self.cash, 2),
            "invested": round(invested, 2),
            "total": round(self.cash + invested, 2),
        }

    def to_prompt_format(self, brief: dict, sim_date: str) -> dict:
        """Format portfolio like _get_ai_portfolio() output for prompt building."""
        positions = []
        for sym, pos in self.positions.items():
            price = _get_price_from_brief(brief, sym, pos["asset_type"])
            if price is None:
                price = pos["avg_cost"]
            qty = pos["quantity"]
            hold_days = 0
            if pos.get("first_buy_date"):
                try:
                    hold_days = (date.fromisoformat(sim_date) - date.fromisoformat(pos["first_buy_date"])).days
                except ValueError:
                    pass
            positions.append({
                "symbol": sym,
                "asset_type": pos["asset_type"],
                "quantity": qty,
                "avg_cost": pos["avg_cost"],
                "current_price": price,
                "market_value": round(qty * price, 2),
                "hold_days": hold_days,
            })
        return {"cash": self.cash, "positions": positions}

    def execute_trade(self, trade: dict, brief: dict, sim_date: str) -> dict | None:
        """Execute a trade against this virtual portfolio. Returns trade record or None."""
        symbol = trade.get("symbol", "").upper()
        asset_type = trade.get("asset_type", "")
        side = trade.get("side", "")
        quantity = trade.get("quantity", 0)
        reasoning = trade.get("reasoning", "")

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
            quantity = int(quantity)

        price = _get_price_from_brief(brief, symbol, asset_type)
        if price is None:
            return None

        total = round(price * quantity, 8)

        if side == "buy":
            if total > self.cash:
                return None
            self.cash -= total
            if symbol in self.positions:
                pos = self.positions[symbol]
                old_qty = pos["quantity"]
                new_qty = old_qty + quantity
                pos["avg_cost"] = ((old_qty * pos["avg_cost"]) + (quantity * price)) / new_qty
                pos["quantity"] = new_qty
            else:
                self.positions[symbol] = {
                    "asset_type": asset_type,
                    "quantity": quantity,
                    "avg_cost": price,
                    "first_buy_date": sim_date,
                }

        elif side == "sell":
            if symbol not in self.positions:
                return None
            pos = self.positions[symbol]
            if quantity > pos["quantity"]:
                return None
            self.cash += total
            pos["quantity"] -= quantity
            if pos["quantity"] <= 0:
                del self.positions[symbol]

        record = {
            "sim_date": sim_date,
            "symbol": symbol,
            "asset_type": asset_type,
            "side": side,
            "quantity": quantity,
            "price": price,
            "total": total,
            "reasoning": reasoning[:500] if reasoning else "",
            "modules_used": trade.get("modules_used", []),
        }
        self.trade_log.append(record)
        return record


# ---------------------------------------------------------------------------
# Core simulation runner
# ---------------------------------------------------------------------------

async def run_simulation(
    run_id: str,
    start_date: str,
    end_date: str,
    trader_configs: list[dict],
    overrides: dict | None = None,
) -> dict:
    """Run a historical replay simulation.

    Parameters
    ----------
    run_id : str
        UUID for this simulation run.
    start_date, end_date : str
        ISO date range to replay (must have stored market briefs).
    trader_configs : list[dict]
        Each entry: {"personality_key": str, "model_key": str, "label": str}
        If empty, defaults to all 20 production AI traders.
    overrides : dict | None
        Optional config overrides to A/B test:
        - "toolkit": list[dict] — override module weights
        - "risk_params": dict — override risk parameters
        - "temperature": float — override LLM temperature
        - "system_prompt_append": str — append to system prompt
    """
    db = get_supabase_admin()
    settings = get_settings()
    overrides = overrides or {}

    try:
        # Load market briefs for the date range
        briefs_resp = (
            db.table("market_briefs")
            .select("brief_date, brief_data")
            .gte("brief_date", start_date)
            .lte("brief_date", end_date)
            .order("brief_date")
            .execute()
        )
        briefs = briefs_resp.data
        if not briefs:
            _update_run(db, run_id, "failed", {"error": f"No market briefs found for {start_date} to {end_date}"})
            return {"error": "No market briefs found"}

        _update_run(db, run_id, "running", None)
        print(f"[SIM] Run {run_id[:8]}: {len(briefs)} days, {len(trader_configs)} traders, overrides: {list(overrides.keys())}")

        # Default to all 20 AI traders if none specified
        if not trader_configs:
            trader_configs = [
                {
                    "personality_key": pkey,
                    "model_key": mkey,
                    "label": f"{pinfo['name']} ({minfo['label']})",
                }
                for pkey, pinfo in PERSONALITIES.items()
                for mkey, minfo in MODELS.items()
            ]

        # Initialize virtual portfolios
        portfolios: dict[str, VirtualPortfolio] = {}
        for tc in trader_configs:
            portfolios[tc["label"]] = VirtualPortfolio(cash=100_000.0)

        # Rate limiter
        semaphore = asyncio.Semaphore(3)  # conservative to stay within Mistral rate limits
        all_daily_results = []

        # Replay each day
        for day_idx, brief_row in enumerate(briefs):
            sim_date = brief_row["brief_date"]
            brief = brief_row["brief_data"]
            if isinstance(brief, str):
                brief = json.loads(brief)

            day_results = {"date": sim_date, "traders": []}

            # Run each trader for this day
            async def _run_sim_trader(tc: dict) -> dict:
                label = tc["label"]
                personality_key = tc["personality_key"]
                model_key = tc["model_key"]
                portfolio = portfolios[label]

                personality = PERSONALITIES.get(personality_key)
                model_cfg = MODELS.get(model_key)
                if not personality or not model_cfg:
                    return {"trader": label, "status": "skipped", "reason": "unknown config"}

                # Apply overrides
                toolkit = overrides.get("toolkit", personality.get("toolkit", []))
                risk_params = overrides.get("risk_params", personality.get("risk_params", {}))

                # Build portfolio prompt format
                portfolio_data = portfolio.to_prompt_format(brief, sim_date)

                # Build trade memory from virtual trade log (last 15)
                recent = portfolio.trade_log[-15:]
                trade_memory = _format_sim_trade_memory(recent, portfolio_data["positions"])

                # Compute risk analysis
                risk_analysis = _compute_portfolio_risk(portfolio_data, personality_key, brief=brief)

                # Build prompt
                user_msg = assemble_toolkit_prompt(
                    personality_key=personality_key,
                    personality_prompt=personality["prompt"],
                    toolkit_config=toolkit,
                    brief=brief,
                    portfolio=portfolio_data,
                    risk_params=risk_params,
                    risk_analysis=risk_analysis,
                    trade_memory=trade_memory,
                    agentic_data={},  # skip patterns/optimizer in sim
                )

                # Build system prompt
                system_prompt = TRADE_SYSTEM
                if "close" in SESSION_CONTEXTS:
                    system_prompt += SESSION_CONTEXTS["close"]
                if overrides.get("system_prompt_append"):
                    system_prompt += "\n" + overrides["system_prompt_append"]

                # Call Mistral
                key_field = model_cfg.get("api_key_field", "mistral_api_key")
                api_key = getattr(settings, key_field, "") or settings.mistral_api_key
                if not api_key:
                    return {"trader": label, "status": "skipped", "reason": "no API key"}

                temperature = overrides.get("temperature", 0.7)
                use_local = overrides.get("use_local", False)

                async with semaphore:
                    try:
                        if use_local:
                            from app.services.llm import call_llm
                            raw = await call_llm(
                                system=system_prompt,
                                user_msg=user_msg,
                                tier="local",
                                temperature=temperature,
                                max_tokens=2048,
                            )
                        else:
                            raw = await _call_mistral_with_temp(
                                model_cfg["model_id"], system_prompt, user_msg, api_key, temperature
                            )
                    except Exception as e:
                        return {"trader": label, "status": "error", "error": str(e)[:200]}

                # Parse trades
                trades = _parse_sim_trades(raw)

                # Execute against virtual portfolio
                executed = []
                toolkit_modules = {t["module"] for t in toolkit}
                for trade in trades:
                    # Detect modules from reasoning
                    raw_modules = trade.get("modules_used", [])
                    if isinstance(raw_modules, list) and all(isinstance(m, str) for m in raw_modules):
                        modules_used = [m for m in raw_modules if m in RAG_MODULES]
                    else:
                        modules_used = []
                    if not modules_used and trade.get("reasoning"):
                        modules_used = detect_modules_from_text(trade.get("reasoning", ""), toolkit_modules)
                    trade["modules_used"] = modules_used

                    result = portfolio.execute_trade(trade, brief, sim_date)
                    if result:
                        executed.append(result)

                snap = portfolio.snapshot(brief)
                return {
                    "trader": label,
                    "status": "ok",
                    "trades_proposed": len(trades),
                    "trades_executed": len(executed),
                    "trades": executed,
                    "portfolio_value": snap["total"],
                }

            # Run traders for this day (with rate limiting via semaphore)
            tasks = [_run_sim_trader(tc) for tc in trader_configs]
            trader_results = await asyncio.gather(*tasks)

            for tr in trader_results:
                day_results["traders"].append(tr)

            # Store daily snapshots
            for tc in trader_configs:
                label = tc["label"]
                snap = portfolios[label].snapshot(brief)
                db.table("sim_snapshots").insert({
                    "run_id": run_id,
                    "trader_label": label,
                    "sim_date": sim_date,
                    "total_value": snap["total"],
                    "cash_balance": snap["cash"],
                    "invested_value": snap["invested"],
                }).execute()

            all_daily_results.append(day_results)
            print(f"[SIM] Run {run_id[:8]} day {day_idx + 1}/{len(briefs)}: {sim_date}")

        # Store all trades
        all_trades = []
        for tc in trader_configs:
            label = tc["label"]
            for trade in portfolios[label].trade_log:
                all_trades.append({
                    "run_id": run_id,
                    "trader_label": label,
                    "sim_date": trade["sim_date"],
                    "symbol": trade["symbol"],
                    "asset_type": trade["asset_type"],
                    "side": trade["side"],
                    "quantity": trade["quantity"],
                    "price": trade["price"],
                    "total": trade["total"],
                    "reasoning": trade["reasoning"],
                    "modules_used": json.dumps(trade["modules_used"]),
                })
        if all_trades:
            chunk_size = 100
            for i in range(0, len(all_trades), chunk_size):
                db.table("sim_trades").insert(all_trades[i : i + chunk_size]).execute()

        # Compute summary
        summary = _compute_sim_summary(trader_configs, portfolios, briefs)
        _update_run(db, run_id, "complete", summary)
        print(f"[SIM] Run {run_id[:8]} complete: {len(all_trades)} total trades across {len(briefs)} days")
        return summary

    except Exception as e:
        print(f"[SIM] Run {run_id[:8]} failed: {e}")
        _update_run(db, run_id, "failed", {"error": str(e)[:500]})
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _update_run(db, run_id: str, status: str, summary: dict | None):
    update = {"status": status}
    if summary is not None:
        update["summary"] = summary
    db.table("sim_runs").update(update).eq("id", run_id).execute()


async def _call_mistral_with_temp(
    model_id: str, system: str, user_msg: str, api_key: str, temperature: float
) -> str:
    """Call Mistral with configurable temperature."""
    url = "https://api.mistral.ai/v1/chat/completions"
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "temperature": temperature,
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


def _parse_sim_trades(raw: str) -> list[dict]:
    """Parse LLM response into trade list (same logic as production)."""
    try:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        parsed = json.loads(text)
        trades = parsed.get("trades", [])
        if not isinstance(trades, list):
            return []
        return trades[:8]
    except json.JSONDecodeError:
        return []


def _format_sim_trade_memory(trades: list[dict], positions: list[dict]) -> str:
    """Format virtual trade log as trade memory for the prompt."""
    if not trades:
        return "No trades yet — this is a fresh portfolio."

    held_symbols = {p["symbol"] for p in positions}
    lines = ["Recent trades:"]
    for t in trades[-15:]:
        side_emoji = "BUY" if t["side"] == "buy" else "SELL"
        held = " (still held)" if t["symbol"] in held_symbols and t["side"] == "buy" else ""
        lines.append(
            f"  {t['sim_date']}: {side_emoji} {t['quantity']} {t['symbol']} "
            f"@ ${t['price']:.2f}{held}"
        )
        if t.get("reasoning"):
            lines.append(f"    Reason: {t['reasoning'][:100]}")

    return "\n".join(lines)


def _compute_sim_summary(
    trader_configs: list[dict],
    portfolios: dict[str, VirtualPortfolio],
    briefs: list[dict],
) -> dict:
    """Compute aggregate simulation results."""
    trader_results = []

    for tc in trader_configs:
        label = tc["label"]
        pf = portfolios[label]
        last_brief = briefs[-1]["brief_data"]
        if isinstance(last_brief, str):
            last_brief = json.loads(last_brief)
        snap = pf.snapshot(last_brief)

        # Trade stats
        total_trades = len(pf.trade_log)
        buys = [t for t in pf.trade_log if t["side"] == "buy"]
        sells = [t for t in pf.trade_log if t["side"] == "sell"]

        # Win rate on sells (compare sell price to avg cost of position)
        wins = 0
        total_pnl = 0.0
        for sell in sells:
            # Find matching buy(s) to estimate cost basis
            sym_buys = [b for b in buys if b["symbol"] == sell["symbol"] and b["sim_date"] <= sell["sim_date"]]
            if sym_buys:
                avg_buy_price = sum(b["price"] * b["quantity"] for b in sym_buys) / sum(b["quantity"] for b in sym_buys)
                pnl_pct = (sell["price"] / avg_buy_price - 1) * 100
                total_pnl += pnl_pct
                if sell["price"] > avg_buy_price:
                    wins += 1

        win_rate = round(wins / max(len(sells), 1) * 100, 1)

        # Module usage
        module_counts: dict[str, int] = defaultdict(int)
        for t in pf.trade_log:
            for m in t.get("modules_used", []):
                module_counts[m] += 1

        trader_results.append({
            "trader": label,
            "personality": tc["personality_key"],
            "model": tc["model_key"],
            "final_value": snap["total"],
            "return_pct": round((snap["total"] / 100_000 - 1) * 100, 2),
            "total_trades": total_trades,
            "buys": len(buys),
            "sells": len(sells),
            "win_rate": win_rate,
            "avg_sell_pnl": round(total_pnl / max(len(sells), 1), 2),
            "module_usage": dict(module_counts),
        })

    # Aggregate
    avg_return = sum(t["return_pct"] for t in trader_results) / max(len(trader_results), 1)
    best = max(trader_results, key=lambda t: t["return_pct"]) if trader_results else None
    worst = min(trader_results, key=lambda t: t["return_pct"]) if trader_results else None

    return {
        "days_simulated": len(briefs),
        "date_range": f"{briefs[0]['brief_date']} to {briefs[-1]['brief_date']}",
        "traders": len(trader_results),
        "avg_return_pct": round(avg_return, 2),
        "best_trader": best,
        "worst_trader": worst,
        "results": trader_results,
    }
