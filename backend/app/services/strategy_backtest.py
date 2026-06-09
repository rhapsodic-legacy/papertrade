"""Strategy backtesting framework.

Replays a candidate strategy against the historical `market_briefs` table
to estimate how it would have performed. The strategy is expressed as
deterministic Python rules (not an LLM prompt) — the whole point is to
validate that rules cohere before we ask a model to follow them.

Key features:
  - Conflict detection: flags when a strategy emits a BUY and a SELL
    signal for the same symbol on the same brief. This is the bug class
    that hurt the original Crypto Chad strategy on 2026-06-03 (RSI 13.2
    triggered both "buy oversold" AND "trim on SMA50 break").
  - Mark-to-market valuation each day from brief price data.
  - Standard metrics: total return, max drawdown, Sharpe ratio, win rate
    on closed round-trips.

Usage:
    from app.services.strategy_backtest import BacktestEngine, Strategy
    from app.services.strategies_library import CryptoChadConflicting, CryptoChadBuyLow

    engine = BacktestEngine(start="2026-04-01", end="2026-06-08")
    result_a = await engine.run(CryptoChadConflicting())
    result_b = await engine.run(CryptoChadBuyLow())
    print(result_a.summary())
    print(result_b.summary())
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

from app.services.supabase_client import get_supabase_admin


# ---------------------------------------------------------------------------
# Trade + state types
# ---------------------------------------------------------------------------

@dataclass
class TradeSignal:
    """A single buy or sell signal emitted by a strategy."""
    symbol: str
    side: str   # "buy" or "sell"
    asset_type: str  # "stock" or "crypto"
    quantity: float
    reasoning: str = ""


@dataclass
class Position:
    """Open position with FIFO cost basis tracking."""
    symbol: str
    asset_type: str
    quantity: float = 0.0
    cost_basis: float = 0.0  # avg cost per unit

    def add(self, qty: float, price: float) -> None:
        total_cost = self.cost_basis * self.quantity + price * qty
        self.quantity += qty
        self.cost_basis = total_cost / self.quantity if self.quantity > 0 else 0.0

    def remove(self, qty: float) -> None:
        # FIFO removal preserves the avg cost basis on the remaining shares
        self.quantity = max(0.0, self.quantity - qty)
        if self.quantity == 0:
            self.cost_basis = 0.0


@dataclass
class BacktestState:
    """Mutable account state during a backtest run."""
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    transactions: list[dict] = field(default_factory=list)
    equity_curve: list[tuple[str, float]] = field(default_factory=list)  # (date_iso, total_value)
    conflicts: list[dict] = field(default_factory=list)  # logged strategy bugs

    def mark_to_market(self, prices: dict[str, float]) -> float:
        positions_value = 0.0
        for sym, pos in self.positions.items():
            price = prices.get(sym)
            if price and pos.quantity > 0:
                positions_value += pos.quantity * price
        return self.cash + positions_value


# ---------------------------------------------------------------------------
# Strategy protocol
# ---------------------------------------------------------------------------

class Strategy(Protocol):
    """A strategy is just a function from (brief, state) to a list of signals.
    Implementations should be pure — no external state, no side effects."""

    name: str

    def evaluate(self, brief: dict, state: BacktestState) -> list[TradeSignal]:
        ...


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class BacktestResult:
    strategy_name: str
    start_date: str
    end_date: str
    starting_capital: float
    ending_value: float
    equity_curve: list[tuple[str, float]]
    transactions: list[dict]
    conflicts: list[dict]

    @property
    def total_return_pct(self) -> float:
        return (self.ending_value / self.starting_capital - 1) * 100

    @property
    def max_drawdown_pct(self) -> float:
        if not self.equity_curve:
            return 0.0
        peak = self.equity_curve[0][1]
        max_dd = 0.0
        for _, val in self.equity_curve:
            peak = max(peak, val)
            dd = (peak - val) / peak * 100
            max_dd = max(max_dd, dd)
        return max_dd

    @property
    def sharpe_ratio(self) -> float:
        """Daily Sharpe (no risk-free adjustment) — purely informational."""
        if len(self.equity_curve) < 2:
            return 0.0
        rets = []
        for i in range(1, len(self.equity_curve)):
            prev = self.equity_curve[i-1][1]
            cur = self.equity_curve[i][1]
            if prev > 0:
                rets.append((cur / prev) - 1)
        if not rets:
            return 0.0
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        std = math.sqrt(var)
        if std == 0:
            return 0.0
        # annualize (assume ~252 trading days)
        return (mean / std) * math.sqrt(252)

    @property
    def num_trades(self) -> int:
        return len(self.transactions)

    @property
    def num_conflicts(self) -> int:
        return len(self.conflicts)

    def summary(self) -> str:
        lines = [
            f"=== Backtest: {self.strategy_name} ===",
            f"Period: {self.start_date} → {self.end_date}",
            f"Starting capital: ${self.starting_capital:,.0f}",
            f"Ending value: ${self.ending_value:,.0f}",
            f"Total return: {self.total_return_pct:+.2f}%",
            f"Max drawdown: {self.max_drawdown_pct:.2f}%",
            f"Sharpe (annualized): {self.sharpe_ratio:.2f}",
            f"Number of trades: {self.num_trades}",
        ]
        if self.conflicts:
            lines.append("")
            lines.append(f"⚠ STRATEGY CONFLICTS DETECTED: {self.num_conflicts}")
            lines.append("  (BUY and SELL signals on the same symbol on the same brief — usually means contradictory rules in the prompt)")
            for c in self.conflicts[:5]:
                lines.append(f"    {c['date']}  {c['symbol']}  BUY reason: {c['buy_reason'][:60]}  SELL reason: {c['sell_reason'][:60]}")
            if len(self.conflicts) > 5:
                lines.append(f"    ... and {len(self.conflicts) - 5} more")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class BacktestEngine:
    """Replays a strategy against historical market_briefs."""

    def __init__(self, start: str, end: str, starting_capital: float = 100_000.0):
        self.start = start
        self.end = end
        self.starting_capital = starting_capital
        self._briefs: list[dict] | None = None

    async def _load_briefs(self) -> list[dict]:
        """Fetch all briefs in the date range, sorted ascending."""
        if self._briefs is not None:
            return self._briefs
        db = get_supabase_admin()
        resp = (
            db.table("market_briefs")
            .select("brief_date, brief_data")
            .gte("brief_date", self.start)
            .lte("brief_date", self.end)
            .order("brief_date", desc=False)
            .execute()
        )
        self._briefs = [
            {"brief_date": r["brief_date"], "data": r["brief_data"]}
            for r in (resp.data or [])
            if r.get("brief_data")
        ]
        return self._briefs

    @staticmethod
    def _extract_prices(brief: dict) -> dict[str, float]:
        """Build a {symbol: price} map from a brief's stocks + crypto blocks."""
        prices: dict[str, float] = {}
        for s in (brief.get("stocks") or []):
            if s.get("price"):
                prices[s["symbol"]] = float(s["price"])
        for c in (brief.get("crypto") or []):
            if c.get("price"):
                prices[c["symbol"]] = float(c["price"])
        return prices

    @staticmethod
    def _detect_conflicts(signals: list[TradeSignal], brief_date: str) -> list[dict]:
        """Flag same-symbol BUY+SELL pairs from a single brief — the canonical
        bug class that hurt the original Crypto Chad."""
        by_symbol: dict[str, dict[str, TradeSignal]] = {}
        conflicts = []
        for sig in signals:
            entry = by_symbol.setdefault(sig.symbol, {})
            existing = entry.get("buy" if sig.side == "sell" else "sell")
            if existing:
                conflicts.append({
                    "date": brief_date,
                    "symbol": sig.symbol,
                    "buy_reason": existing.reasoning if existing.side == "buy" else sig.reasoning,
                    "sell_reason": existing.reasoning if existing.side == "sell" else sig.reasoning,
                })
            entry[sig.side] = sig
        return conflicts

    async def run(self, strategy: Strategy) -> BacktestResult:
        briefs = await self._load_briefs()
        state = BacktestState(cash=self.starting_capital)
        last_known_prices: dict[str, float] = {}

        for brief_entry in briefs:
            brief_date = brief_entry["brief_date"]
            brief = brief_entry["data"]
            todays_prices = self._extract_prices(brief)
            # Carry forward last-known prices for symbols missing from today's brief
            # — otherwise mark-to-market drops the position to zero on a stale day,
            # which masks real strategy performance.
            last_known_prices.update(todays_prices)
            prices = dict(last_known_prices)

            # Strategy emits signals from the brief alone (no peer / cross-trader
            # context for now — that's a future extension).
            signals = strategy.evaluate(brief, state)

            # Conflict detection BEFORE execution
            conflicts = self._detect_conflicts(signals, brief_date)
            state.conflicts.extend(conflicts)

            # Execute signals in emission order
            for sig in signals:
                price = prices.get(sig.symbol)
                if not price or price <= 0:
                    continue  # missing price — skip silently
                if sig.side == "buy":
                    cost = price * sig.quantity
                    if cost > state.cash:
                        continue  # insufficient funds
                    state.cash -= cost
                    pos = state.positions.setdefault(
                        sig.symbol, Position(symbol=sig.symbol, asset_type=sig.asset_type)
                    )
                    pos.add(sig.quantity, price)
                else:  # sell
                    pos = state.positions.get(sig.symbol)
                    if not pos or pos.quantity <= 0:
                        continue
                    qty = min(sig.quantity, pos.quantity)
                    proceeds = price * qty
                    state.cash += proceeds
                    pos.remove(qty)
                state.transactions.append({
                    "date": brief_date,
                    "side": sig.side,
                    "symbol": sig.symbol,
                    "quantity": sig.quantity,
                    "price": price,
                    "reasoning": sig.reasoning,
                })

            # Mark to market at end of day
            ev = state.mark_to_market(prices)
            state.equity_curve.append((brief_date, ev))

        final_value = state.equity_curve[-1][1] if state.equity_curve else self.starting_capital
        return BacktestResult(
            strategy_name=strategy.name,
            start_date=self.start,
            end_date=self.end,
            starting_capital=self.starting_capital,
            ending_value=final_value,
            equity_curve=state.equity_curve,
            transactions=state.transactions,
            conflicts=state.conflicts,
        )
