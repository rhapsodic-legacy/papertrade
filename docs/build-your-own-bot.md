# Build Your Own Bot

PaperTrade lets you create your own AI trading bot with a custom personality,
strategy, toolkit, and risk profile. This guide walks through what's possible
today and how to use it.

## What you can configure

When you create a custom trader, you choose:

1. **Strategy prompt** — free-form description of how your bot should think
2. **Risk preset** — Conservative / Balanced / Aggressive
3. **Asset focus** — Stocks & Crypto / Stocks Only / Crypto Only
4. **Toolkit modules** — pick from the 12 data modules the AI will see
5. **Name** — appears on the leaderboard alongside other traders

## How to create one

1. Sign in at the top right
2. Go to `/create-trader`
3. Fill in the form, hit Create
4. Your bot enters the daily 5:10 PM ET pipeline starting the next trading day
5. Track its performance under `/my-traders`

---

## Toolkit module reference

The AI receives only the modules you select. Pick fewer modules for a focused
trader; pick more for a comprehensive one (but the prompt gets longer and the
model may attend less to each).

| Module | What the AI sees | Best for |
|---|---|---|
| `technicals` | RSI, SMA20/50, MACD, 7d/30d momentum, Bollinger Bands, relative volume, ATR | Any technical strategy |
| `fundamentals` | PE ratio, market cap, dividend yield, beta, analyst consensus, EPS estimates | Value-based traders |
| `sentiment` | News sentiment scores, market confidence, headline tone | News-reactive traders |
| `momentum` | Crypto-specific momentum + sector flow | Crypto traders, trend-followers |
| `macro` | Sector rotation, market regime, growth-vs-value, safe-haven demand | Top-down strategy |
| `patterns` | Pattern recognition (engulfing, doji, breakouts, support/resistance) | Technical/setup traders |
| `optimizer` | Suggested position sizes accounting for volatility + signal strength + cash | Risk-aware sizing |
| `signal_ranker` | Composite score (-100 to +100) per asset blending multiple factors | Confirmation overlay |
| `trade_context` | Your bot's own historical track record + key patterns | Self-aware traders |
| `dynamic_risk` | Drawdown-aware sizing multiplier (scales down in losing streaks) | Defensive traders |
| `options_flow` | VIX (CBOE Volatility Index) — fear gauge derived from options | Risk-on/risk-off bias |
| `yield_curve` | Treasury yields (2Y/10Y/30Y/Fed Funds) and curve shape | Macro/rate-sensitive bots |
| `expert_opinion` | Daily digest of independent analyst calls (Wolf Street, CoinDesk, Decrypt, etc.) | News + consensus traders |

You can also flag a module as `invert` (currently only via API) — the contrarian
treatment, where bullish consensus becomes a bearish signal and vice versa.

---

## Risk presets

| Preset | Stop-loss | Take-profit | Max position | Max hold | Min sells/day |
|---|---|---|---|---|---|
| Conservative | -6% | +12% | 12% of portfolio | 45 days | 1 |
| Balanced | -8% | +15% | 15% of portfolio | 30 days | 1 |
| Aggressive | -5% | +10% | 20% of portfolio | 14 days | 1 |

Aggressive cuts losses fast and concentrates positions; Conservative holds longer
with smaller bets. Pick based on whether your strategy needs to ride trends
(Aggressive) or wait for reversion (Conservative).

---

## Strategy prompt templates

Drop one of these into the strategy field as a starting point and edit to taste.

### Template: Quality-Momentum Stock Picker
```
You are a quality-momentum trader focused on US large caps.
BUY criteria: PE ratio < sector average + 20%, 30d momentum > 0%, RSI 40-70,
analyst Strong Buy consensus, dividend yield optional.
SELL criteria: 30d momentum turns negative, RSI > 75, PE expands beyond 1.5x sector,
or position has been held 30+ days with <2% return.
TARGET: 8-12 names spread across 4+ sectors. Cash buffer 10-15%.
Avoid: micro-caps, biotech binary events, anything below $5.
```

### Template: Crypto Macro Rotator
```
You are a crypto rotator who shifts between BTC, ETH, and large-cap alts based on
the macro regime.
BUY criteria: BTC dominance is rising → favor BTC and ETH; BTC dominance is falling →
rotate to top-10 alts (SOL, AVAX, LINK). Always require 7d momentum positive.
SELL criteria: BTC trend breaks below SMA50, or any single alt exceeds 25% of crypto
allocation, or RSI > 80 on the held position.
ALLOCATION: 60-80% crypto, 10-20% tech stocks (correlated growth), rest cash.
Watch the yield curve — falling rates favor risk-on crypto exposure.
```

### Template: Mean-Reversion Specialist
```
You are a mean-reversion trader who buys oversold quality and sells overbought
crowded names.
BUY criteria: RSI < 30, 7d return < -5%, PE below 5-year norms, fundamentals
intact (no missed earnings or guidance cuts).
SELL criteria: RSI > 70, 30d return > +15%, or position hits +20% gain.
TARGET: hold 15-25% cash as dry powder for sharp drawdowns. Diversify 6-10 positions.
Never chase momentum — let it come to you.
```

### Template: Earnings-Aware Defensive
```
You are a defensive equity trader prioritizing capital preservation.
BUY criteria: low beta (<1.0), dividend yield > 1%, RSI < 60, no earnings within 14 days.
SELL criteria: position approaches earnings within 7 days (trim 50%), RSI > 75,
or stop-loss hit at -6%.
ALLOCATION: 60% blue chips, 20% defensive sectors (healthcare, staples), 10% bonds (TLT),
10% cash. Shift to 40/30/30 (stocks/TLT/cash) when market regime is bearish.
Avoid all crypto and any beta > 1.5.
```

### Template: News-Driven Event Trader
```
You are an event-driven trader who reacts to news clusters and breaking developments.
BUY criteria: news cluster sentiment > +0.3, sector aligned, 7d momentum confirms,
expert opinion digest cites the ticker positively.
SELL criteria: cluster sentiment flips negative, position approaches earnings,
or stop-loss at -5%.
TARGET: 6-10 tactical positions, max 14-day holds. Heavy cash buffer (20%) to deploy
on sudden opportunities. Cite the cluster theme in every BUY decision.
```

---

## Available LLM models

Currently your custom bot can run on these models:

| Model | Provider | Notes |
|---|---|---|
| Mistral Small | Mistral La Plateforme | Fast, lower quality |
| Mistral Medium | Mistral La Plateforme | Best price/quality balance |
| Mistral Large | Mistral La Plateforme | Highest quality Mistral tier |
| Mistral Large 2 | Mistral La Plateforme | Latest large model |
| DeepSeek V3.2 | NVIDIA NIM | Fast inference, free tier 40 RPM |

The exact model assigned to your bot depends on backend availability; we route to
keep load balanced across the 25 daily traders.

---

## Bring Your Own API Keys (BYO-key)

Today, custom traders run on the shared backend infrastructure (our Mistral and
NVIDIA keys). This is fine for prototyping but has rate-limit and cost
consequences as the fleet grows.

**Status: BYO-key support is on the roadmap.** When it ships, you'll be able to
attach your own API keys to your bot, and your bot's LLM calls will hit your
account rather than ours. Until then, the per-trader rate limits we set apply.

To prepare, get free or low-cost API access from any of these providers:

### Mistral La Plateforme

- **Sign up**: [console.mistral.ai](https://console.mistral.ai)
- **Free tier**: limited rate per minute, generous enough for a personal bot
- **Models**: `mistral-small-latest`, `mistral-medium-latest`, `mistral-large-latest`
- **Where keys live**: API Keys section in the Mistral console
- **Pricing** (as of 2026-04): pay-per-token, a couple of dollars per million tokens for Medium

### NVIDIA NIM

- **Sign up**: [build.nvidia.com](https://build.nvidia.com) (NVIDIA Developer account)
- **Free tier**: 40 requests per minute per model, no credits needed
- **Models**: `deepseek-ai/deepseek-v3.2`, `meta/llama-4-maverick-17b-128e-instruct`,
  `moonshotai/kimi-k2-instruct`, `openai/gpt-oss-120b`, and 80+ others
- **Where keys live**: top-right of the dashboard (`nvapi-...` format)
- **Pricing**: free tier sufficient for a single-bot pipeline; paid tiers for higher RPM

### Anthropic Claude

- **Sign up**: [console.anthropic.com](https://console.anthropic.com)
- **Pricing**: pay-per-token, no free tier; Sonnet is reasonably priced
- **Models we'd support**: `claude-haiku-4-5`, `claude-sonnet-4-6`, `claude-opus-4-7`

### OpenAI

- **Sign up**: [platform.openai.com](https://platform.openai.com)
- **Pricing**: pay-per-token, $5 starter credit on new accounts
- **Models we'd support**: `gpt-4o`, `gpt-4o-mini`

---

## Tips for a successful bot

- **Keep your strategy prompt under 200 words.** Longer prompts crowd out the
  toolkit data the model needs to actually trade.
- **Pick 4-7 modules**, not all 12. The model attends most to the first few
  modules in the prompt; loading every module dilutes attention.
- **Test for a week before tuning**. Daily P&L noise is huge; trust nothing
  before you've seen 5+ pipeline cycles.
- **Track which modules your bot actually cites** in the reasoning view — if a
  module has 0 citations after a week, it's not influencing decisions.
- **Don't fight your risk preset**. If you picked Aggressive, expect drawdowns;
  if you picked Conservative, expect to lag in raging bull markets.

---

## Roadmap

- BYO-key support (per-trader API keys)
- Backtesting against the last 6 months before you commit a bot to live
- Strategy templates accessible directly in the create-trader UI
- Public sharing of bot configurations (community templates)
- Intraday adaptation (today the pipeline runs once at 5:10 PM ET)
