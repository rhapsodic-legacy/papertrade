# Trader Improvements Roadmap

A working list of ideas to expand what the AI trader fleet can do, organized
by leverage and grouped into themes. Items marked **[NEXT]** are queued for
the current execution pass; **[DONE]** means shipped; everything else is
parked for future sessions.

## Currently executing (in this order)

1. **On-chain crypto data** — Glassnode/IntoTheBlock/CryptoQuant-class metrics
   surfaced to Crypto Chad and Crypto Chad New. The BTC drawdown that started
   2026-06-03 exposed how thin our crypto data is. **[NEXT — 1 of 4]**
2. **Real backtesting framework** — Strategy simulation against historical
   regimes. Would have caught the "buy oversold + trim on SMA50 break"
   conflict before it shipped. **[NEXT — 2 of 4]**
3. **Cross-trader signal aggregation** — Surface "8 of 25 traders flagged
   TICKER as BUY today" as a fleet-conviction meta-signal. Free and
   immediate; traders currently discard this aggregate information.
   **[NEXT — 3 of 4]**
4. **Cross-asset signals: DXY, Gold, real yields** — Crypto and tech inversely
   correlated with DXY strength. We track yield curve but not the dollar.
   Cheap via FRED. **[NEXT — 4 of 4]**

---

## Tier 1 — Information sources

External data we don't currently feed traders. Highest signal-per-dollar tier.

- **On-chain crypto data** — exchange reserves, miner-to-exchange flow,
  MVRV-Z, NUPL, active addresses, hash rate. Sources: Glassnode (paid),
  IntoTheBlock (mostly free metrics), CryptoQuant (mixed), Blockchain.com
  Charts API (free, basic), Alternative.me (already used). **[NEXT]**
- **Perpetual futures funding rates + liquidation data** — Coinglass, Binance
  and Bybit APIs. Tells us whether a drawdown is real selling or leveraged
  shake-out. Free.
- **Cross-asset signals: DXY, Gold, real yields** — FRED has all of these.
  Crypto and tech almost always inversely correlated with DXY. **[NEXT]**
- **13F flow analysis** — WhaleWisdom free tier or direct SEC filings.
  Quarterly position changes from named hedge funds are publicly disclosed
  and predictive when aggregated. Stronger than the analyst RSS commentary
  we currently surface.
- **Earnings call sentiment shifts** — AlphaSense, Earnings Call Transcripts.
  Management tone change Q/Q often leads price by 1-2 weeks.
- **Short interest data** — Finra-published twice a month. High short
  interest + RSI <30 often signals squeeze setups for individual stocks.
- **Economic surprise indices (Citi ESI)** — when economic surprises turn
  positive after a negative streak, equities rally. Not free but cheap.
- **Cross-exchange spread anomalies** — for crypto, large spreads between
  Coinbase / Binance / Kraken sometimes signal regulatory or liquidity events
  that lead price.
- **Insider buying enrichment** — we have Finnhub basic data; Form 4 filings
  on EDGAR + clustering by industry would catch broader sector signals.

## Tier 2 — Code / architectural improvements

- **Real backtesting framework** — strategy simulator, not just benchmark
  comparison. **[NEXT]**
- **Cross-trader signal aggregation** — fleet conviction meta-module.
  **[NEXT]**
- **Multi-timeframe technicals** — currently everything is daily. Adding 4h
  and weekly RSI/SMA would catch setups that don't show up on the daily
  chart. Real swing traders look at multiple timeframes; ours look at one.
- **Risk-parity / portfolio-level risk** — currently traders manage positions
  in isolation. Portfolio-level VaR and inter-asset correlation analysis
  would let them size into uncorrelated risks rather than overweighting
  correlated ones.
- **Regime detection** — current "market regime" is rule-based and simple.
  A proper HMM or scored classifier (bull / bear / range / crash / recovery)
  would let personalities adapt their parameters automatically.
- **Position lifecycle dashboard** — visualize each trade from entry through
  exit, see exactly when stops, targets, aging, or thesis-break triggered.
- **Conditional order types** — add OCO (one-cancels-other), bracket orders,
  scaled entries / scaled exits. Currently limited to stop-loss / take-profit
  / trailing-stop / limit-buy.
- **Better intraday triggers** — current intraday subagent only handles
  conditional orders. Could expand to: price-level alerts, news event
  triggers, breakout / breakdown detection on shorter timeframes.
- **Live data feeds** — currently relying on Finnhub free tier. Real-time
  price and L2 data would change what's possible (esp. for the intraday
  subagent), but ongoing cost.
- **Cross-personality learning** — when one trader has a good setup, share
  the *pattern* (anonymized) with others so 25 minds work on it. Different
  from the current cross_trader text which only shows positions.

## Tier 3 — ML / AI heavier lifts

- **Embedding-based trade memory** — replace the failed text-reflection
  injection with vector-search over past trades. "Here are 8 prior trades
  that matched this setup, win rate 67%, avg held 22 days." This is the
  actual "self-recursive learning" we tried and failed at with text injection.
- **Devil's advocate / adversarial pre-trade pass** — second LLM critiques
  each proposed trade before execution: "Counter-thesis: here's why this
  might be wrong." Doubles inference cost but probably the single most
  powerful quality-control mechanism we could add.
- **Anomaly detection on trader reasoning** — flag when a trade's reasoning
  statistically deviates from the trader's stated strategy. Would have
  caught the original Chad's "death spiral" framing before the trade went
  through.
- **Domain-specific sentiment classifier** — fine-tune a small model on
  financial Twitter / news rather than relying on generic LLM sentiment.
- **Pattern recognition via CNN on price charts** — formal head-and-shoulders,
  cup-and-handle, etc. We already have a `pattern_recognition.py` but a
  CNN-based approach would catch patterns the rule-based version misses.
- **Reinforcement learning** — let the AI explore strategies in a simulated
  environment with reward = P&L. Research-frontier problem for trading;
  success not guaranteed. Save for a "do once" experiment, not as a primary
  bet.
- **Time-series forecasting models** — Prophet / Chronos / Tsfm for price
  forecasts to feed traders. Modest utility but additive signal.
- **Causal inference on signal effectiveness** — instead of correlating
  module use with win rate, counterfactual analysis on which modules
  actually moved decisions.

## Tier 4 — Process / operational

- **Strategy versioning + A/B tests** — formal mechanism to test strategy
  variants on subsets of traders, with statistical comparison.
- **Confidence calibration tracking** — track when traders are confident vs
  wrong; train them to be calibrated over time.
- **Better "thesis broken" taxonomy** — current prompt says "named exploit,
  named regulation, named structural change" but doesn't tell traders what
  counts. A concrete taxonomy with examples would help.
- **Position size optimization** — Kelly criterion based sizing rather than
  fixed percentages of portfolio.
- **Trade journal that traders actually read** — we deprecated this but with
  a better delivery mechanism (e.g., required write-step in the response
  schema) it could come back productively.

## Done (in this session's broader scope)

- Tier framework for BTC/ETH vs utility plays vs meme coins **[DONE 2026-06-03]**
- buy-low-sell-high primary directive across Chad strategies **[DONE 2026-06-03]**
- Tier-1 STOP_LOSS conditional ban **[DONE 2026-06-08]**
- session_decision_rationale required field **[DONE 2026-06-02]**
- Reserved digest slots for institutional sources **[DONE 2026-06-01]**
- Reflection-into-prompt deprecation **[DONE 2026-05-17]**
- NVIDIA circuit breaker + walk-back yield curve fallback **[DONE 2026-05-14]**
