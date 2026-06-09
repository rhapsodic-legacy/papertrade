"""Strategy implementations for backtesting.

Each strategy is a deterministic Python translation of the rules we'd
otherwise express in an LLM prompt. The point: catch logical conflicts
(e.g. buy and sell signals firing simultaneously on the same name)
before shipping a prompt that contains them.
"""

from __future__ import annotations

from app.services.strategy_backtest import Strategy, TradeSignal, BacktestState


# ---------------------------------------------------------------------------
# Helper: extract per-symbol technical indicators from a brief
# ---------------------------------------------------------------------------

def _crypto_tech(brief: dict, symbol: str) -> dict | None:
    return (brief.get("crypto_technicals") or {}).get(symbol)


def _crypto_data(brief: dict, symbol: str) -> dict | None:
    for c in (brief.get("crypto") or []):
        if c.get("symbol") == symbol:
            return c
    return None


def _portfolio_weight(state: BacktestState, symbol: str, price: float, total_value: float) -> float:
    pos = state.positions.get(symbol)
    if not pos or total_value <= 0:
        return 0.0
    return (pos.quantity * price) / total_value


# ---------------------------------------------------------------------------
# Strategy 1: BuyHoldBTC — naive control
# ---------------------------------------------------------------------------

class BuyHoldBTC:
    name = "Buy & Hold BTC (control)"

    def evaluate(self, brief: dict, state: BacktestState) -> list[TradeSignal]:
        btc = _crypto_data(brief, "BTC")
        if not btc or state.cash < 1000:
            return []
        # Deploy 95% of starting capital on first day, then hold
        if not state.positions and state.cash > 50000:
            qty = round((state.cash * 0.95) / btc["price"], 4)
            return [TradeSignal(symbol="BTC", side="buy", asset_type="crypto",
                                quantity=qty, reasoning="Initial BTC deployment")]
        return []


# ---------------------------------------------------------------------------
# Strategy 2: CryptoChadConflicting — the OLD version that hurt the original
# Chad on 2026-06-03. Translates the prompt rules into deterministic code so
# the conflict between BUY criteria and SELL criteria is visible.
# ---------------------------------------------------------------------------

class CryptoChadConflicting:
    name = "Crypto Chad ORIGINAL (conflicting rules)"

    def evaluate(self, brief: dict, state: BacktestState) -> list[TradeSignal]:
        signals: list[TradeSignal] = []
        btc = _crypto_data(brief, "BTC")
        btc_tech = _crypto_tech(brief, "BTC")
        if not btc or not btc_tech:
            return []
        prices = {"BTC": btc["price"]}
        total_value = state.mark_to_market(prices)

        rsi = btc_tech.get("rsi_14")
        vs_sma50 = btc_tech.get("vs_sma_50")
        pos = state.positions.get("BTC")

        # OLD strategy seeded an initial BTC position when it saw bullish
        # tape — translated here as a one-time initial buy on day 1 so the
        # subsequent SELL rules have something to fire on.
        if not pos and state.cash > 50000:
            qty = round((state.cash * 0.70) / btc["price"], 4)
            signals.append(TradeSignal(
                symbol="BTC", side="buy", asset_type="crypto", quantity=qty,
                reasoning="Initial BTC deployment (70% cash)"
            ))
            return signals  # seeded, evaluate next brief

        # OLD SELL criterion #1: "if BTC breaks below SMA50, regime change"
        # — this is the rule that hurt the original Chad on 2026-06-03.
        if vs_sma50 is not None and vs_sma50 < 0 and pos and pos.quantity > 0:
            signals.append(TradeSignal(
                symbol="BTC", side="sell", asset_type="crypto",
                quantity=pos.quantity * 0.30,
                reasoning="BTC broke below SMA50 — regime change, trim 30% (OLD RULE)"
            ))

        # OLD SELL criterion #2: "When BTC bearish, reduce exposure"
        # — panic sells the same brief the BUY rule below tries to fire on.
        if rsi is not None and rsi < 30 and pos and pos.quantity > 0:
            signals.append(TradeSignal(
                symbol="BTC", side="sell", asset_type="crypto",
                quantity=pos.quantity * 0.20,
                reasoning="BTC death spiral (RSI <30) — reduce exposure (OLD RULE)"
            ))

        # OLD BUY criterion: "buy oversold + cash overweight" — fires on the
        # SAME brief where the SELL rules above also fire. This is the bug
        # the backtester is meant to surface.
        if (
            rsi is not None and rsi < 40
            and state.cash > total_value * 0.10
        ):
            qty = round((state.cash * 0.10) / btc["price"], 4)
            if qty > 0:
                signals.append(TradeSignal(
                    symbol="BTC", side="buy", asset_type="crypto", quantity=qty,
                    reasoning="BTC RSI<40 + cash overweight — buy oversold (OLD RULE)"
                ))

        return signals


# ---------------------------------------------------------------------------
# Strategy 3: CryptoChadBuyLow — the REWRITTEN version with tier framework
# ---------------------------------------------------------------------------

class CryptoChadBuyLow:
    name = "Crypto Chad REWRITTEN (buy-low, tier framework)"

    def evaluate(self, brief: dict, state: BacktestState) -> list[TradeSignal]:
        signals: list[TradeSignal] = []
        btc = _crypto_data(brief, "BTC")
        eth = _crypto_data(brief, "ETH")
        btc_tech = _crypto_tech(brief, "BTC")
        if not btc or not btc_tech:
            return []
        prices = {"BTC": btc["price"]}
        if eth:
            prices["ETH"] = eth["price"]
        total_value = state.mark_to_market(prices)

        rsi = btc_tech.get("rsi_14")
        btc_weight = _portfolio_weight(state, "BTC", btc["price"], total_value)
        btc_pos = state.positions.get("BTC")

        # Tier-1 BUY/SELL is governed by a single weight-based decision tree.
        # BUY when under cap and RSI says undervalued. SELL only meaningfully
        # over cap, or on take-profit. The cap/deadband makes these mutually
        # exclusive — same-brief BUY+SELL is treated as a strategy bug.
        CAP = 0.20
        TRIM_THRESHOLD = 0.25   # 5-pt deadband above cap to avoid churn

        position_return = 0.0
        if btc_pos and btc_pos.cost_basis > 0:
            position_return = ((btc["price"] / btc_pos.cost_basis) - 1) * 100

        # Take-profit fires first — independent of weight.
        if (
            btc_pos and btc_pos.quantity > 0
            and rsi is not None and rsi > 75
            and position_return > 25
        ):
            signals.append(TradeSignal(
                symbol="BTC", side="sell", asset_type="crypto",
                quantity=btc_pos.quantity * 0.50,
                reasoning=f"TIER 1 take-profit: +{position_return:.1f}% gain, RSI {rsi:.1f}"
            ))
        # Concentration trim — only when meaningfully over cap.
        elif btc_pos and btc_weight > TRIM_THRESHOLD:
            excess_weight = btc_weight - CAP
            qty_to_trim = btc_pos.quantity * (excess_weight / btc_weight)
            signals.append(TradeSignal(
                symbol="BTC", side="sell", asset_type="crypto",
                quantity=qty_to_trim,
                reasoning=f"TIER 1 concentration trim: {btc_weight*100:.1f}% > {TRIM_THRESHOLD*100:.0f}% deadband"
            ))
        # Scale-in BUY — only when under cap AND oversold AND cash heavy.
        elif (
            rsi is not None and rsi < 40
            and state.cash > total_value * 0.30
            and btc_weight < CAP
        ):
            cash_to_deploy = state.cash * 0.20
            qty = round(cash_to_deploy / btc["price"], 4)
            if qty > 0:
                signals.append(TradeSignal(
                    symbol="BTC", side="buy", asset_type="crypto", quantity=qty,
                    reasoning=f"TIER 1 buy: RSI {rsi:.1f}, weight {btc_weight*100:.1f}% < cap"
                ))

        return signals
