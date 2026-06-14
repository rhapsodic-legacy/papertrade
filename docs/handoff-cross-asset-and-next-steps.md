# Handoff — cross_asset adoption + open issues

Date written: 2026-06-12

> **UPDATE (2026-06-13):** Plan A is VERIFIED working. On the first live
> run with the new code (6/13, 76 trades), the DXY->BTC bullet — the only
> macro channel that crossed its threshold that day — was cited 3 times,
> all by crypto-line traders quoting the "DXY headwind / valuation channel"
> framing verbatim. cross_asset cite-rate went 0% -> 4.8% (3/62), which
> understates it because only 1 of 4 channels was active. The named-hook
> diagnosis was correct.
>
> Pattern extended to the two other dead modules the cite-rate tracker
> surfaced (options_flow 0.9%, yield_curve 1.1%) — commit d2d3584 — but
> framed around RISK POSTURE not new trades, since both run PnL-negative.
> Watch their cite-rate AND outcome over the next week; if citations rise
> but PnL stays negative, the hooks are driving the wrong behavior and
> should be pulled. Verify with `?cite_days=1` on /api/analytics/modules.
>
> Two bugs found and fixed while verifying the above:
> - **V2 personalities had no discipline rules** (crypto_chad_swing,
>   contrarian_carl_patient) — added in d2d3584.
> - **Naive personality resolver** (commit 71a91d3): 15 call sites matched
>   display name → personality key by FIRST substring, so "Crypto Chad New"
>   mis-routed to base crypto_chad everywhere in analytics/attribution/
>   backtest/commentary (NOT trading — that path was already longest-match).
>   All now route through `resolve_personality_key()` in ai_trader.py.
>   This means historical by_personality analytics before 6/13 lumped the
>   "New" variants under their base line — re-read any such analysis.
>
> **Original update (2026-06-12):** Plan A shipped and deployed
> (revision papertrade-backend-00041-rfc, commits 9479a63 + 5a9bdc8).
> `_compute_macro_implications()` renders "FOR YOUR BOOK" per-personality
> bullets at the top of the cross_asset section.
>
> Cite-rate tracking added to `/api/analytics/modules` (`cite_rate_recent`
> per module + `low_adoption` list). First run flags cross_asset 0.1%,
> **options_flow 0.9%, yield_curve 1.1%** — two more dead modules that
> likely need the same named-hook treatment.
>
> Also discovered and fixed: Supabase silently caps every `.execute()` at
> 1000 rows. The leaderboard, module attribution, regime analysis, and the
> 30d peer-intelligence feed were all computing on truncated (oldest-first)
> data. This fully explains the "New variants 0.00%" mystery and the
> leaderboard numbers below — the REAL standings have YOLO Bot Mistral
> Medium at +17.6% 90d (not -10%) and Crypto Chad family as the main drag.
> Use `fetch_all_rows()` from `app/services/supabase_client.py` for any
> query that can exceed 1000 rows. The "Llama 4 Maverick (NVIDIA)" traders
> are a real 5th model slot (meta/llama-4-maverick via NVIDIA API) — 25
> active traders total, not 20; CLAUDE.md is stale on this.

This doc is a state-of-the-system snapshot for whoever picks up next. The
central unsolved problem is at the top. Other open work is below it.

---

## ⚠️ Hardware constraint — read first

The user's local Mac Mini has **8GB RAM**. Gemma 4 e2b is ~7GB.

- Running a long Gemma prompt locked the machine on 2026-06-12 and forced a
  hard reboot. Do not run new local LLM calls without confirming with the user.
- Existing Gemma preprocessors (`cluster_headlines`, `summarize_analyst_consensus`,
  `summarize_insider_flow`, `narrate_movers`, `compress_analyst_digest`) work
  because they each fit. New ones aren't safe by default.
- For new LLM work, prefer Cloud Run + paid API (Mistral via the existing
  `MISTRAL_API_KEY` / `MISTRAL_API_KEY_2`) over local Gemma.
- Hardcoded deterministic logic is the safest option when it suffices.

This is also captured in:
- `CLAUDE.md` (top of file, ⚠️ HARD CONSTRAINT block)
- `~/.claude/projects/-Users-jessepassmore-Desktop-Programming-Pizazz-fintech-support/memory/feedback_hardware_8gb_ram.md`

---

## Core problem — cross_asset module is not being cited

### What it is
A RAG module added 2026-06-09 that surfaces DXY, gold, 10Y real yields,
breakeven inflation, and WTI to traders. Code:
- Data fetch: `backend/app/services/market_brief.py` — `_fetch_cross_asset()`
  (FRED for 4 series, Yahoo `GC=F` for gold)
- RAG module registration: `backend/app/services/rag_toolkit.py` —
  `RAG_MODULES["cross_asset"]`, `MODULE_KEYWORDS["cross_asset"]`,
  `_format_cross_asset()`, `_MODULE_FORMATTERS["cross_asset"]`
- Toolkit weights: `backend/app/services/ai_trader.py` — added to
  Vanilla (6), Steady Eddie (7), Contrarian Carl (7), Crypto Chad (8),
  Crypto Chad New (8), Contrarian Carl New (7). YOLO Bot intentionally
  excluded.

### Adoption data (two consecutive 5PM ET pipelines)

| Date | Trades | cross_asset cites | fleet_conviction cites | btc_onchain cites |
|------|--------|-------------------|------------------------|-------------------|
| 2026-06-09 | 134 | **0** | 15 (9 traders) | 5 (4 traders) |
| 2026-06-11 | 69  | **0** | 6 (4 traders)  | 3 (3 traders) |

The other two modules shipped in the same wave are healthy. Cross_asset
is stuck at zero.

### What's been verified
- The 6/9, 6/10, 6/11 briefs all have a populated `cross_asset` block
  with real numbers and regime labels
- The formatter renders the section correctly when called directly
- The section appears in the assembled prompt at character ~19,495 of
  ~39,260 (Crypto Chad New) — mid-prompt, not at the end
- All 6 personality toolkits have `cross_asset` at weight 6-8
- Both Mistral Small and Mistral Large 2 traders ignore it equally — not
  a model-size issue

### What's been tried
1. **Initial copy (shipped 6/9)** — generic QUOTABLE with numbers, neutral
   NOTE block, SYNTHESIS line that in MIXED regimes said "Don't over-weight
   macro framing; lean on bottom-up signals." → 0/134 trades cited it.

2. **Rewrite (shipped 6/10)** — QUOTABLE now explicitly says "Cite these
   numbers directly in your reasoning whenever you trade crypto, growth
   equities, gold-sensitive names, or energy." MIXED-regime SYNTHESIS
   now lists active tilts as bullet points instead of telling models to
   ignore. → 0/69 trades cited it on 6/11.

3. **Gemma per-personality implications (attempted 6/12, REVERTED)** —
   tried to have Gemma 4 e2b translate macro signals into named-symbol
   bullets per personality, prepend them to the section. The single
   ~2,500-token structured-JSON prompt with `max_tokens=4096` crashed the
   8GB box. Code reverted before commit; production never touched.

### Diagnosis (best current theory)

The modules that ARE being cited share a property cross_asset lacks:
they surface **per-symbol named signals** the LLM can drop into reasoning
verbatim.

- `fleet_conviction` produces labels like `STRONG_DISTRIBUTION on GS`,
  `accumulation on JNJ`. The trader literally pastes that in: *"Fleet
  shows STRONG_DISTRIBUTION (flow=-0.50)."*
- `btc_onchain` produces `ACCUMULATION_ZONE`, `CONTRARIAN_BUY_ZONE`,
  `MVRV-Z 0.34`. Quotable: *"BTC remains in ACCUMULATION_ZONE (MVRV-Z 0.29,
  Puell 0.58)."*
- `trade_context` produces personalized win-rate by sector. Quotable:
  *"Your historical track record shows 83% win rate in Crypto (vs 51% in
  stocks)."*

Cross_asset gives **portfolio-context macro** ("DXY +1%"). The trading
LLMs don't translate "DXY +1%" → "I shouldn't buy BTC" on their own.
They want the implication served as a labeled per-symbol hook.

### Proposed next step (Plan A — hardcoded mapping)

Build `_compute_macro_implications(cross_asset, personality_key) -> list[str]`
in `backend/app/services/rag_toolkit.py`. Deterministic lookup, no LLM.

The mapping table (channel × tilt × personality → bullet):

| Channel | Tilt | Vanilla | Steady Eddie | YOLO Bot | Contrarian Carl | Crypto Chad / Chad New |
|---|---|---|---|---|---|---|
| DXY | strengthening | BTC headwind | (low impact) | tech/momentum headwind | watch crypto dislocations | **direct BTC/ETH headwind via valuation channel** |
| DXY | weakening | BTC tailwind | (low impact) | risk-on tailwind | fade rallies | **BTC/ETH tailwind, favor adds** |
| Real 10Y | rising (≥+10bps) | growth multiples compress | TLT pain — defer adds | growth momentum pressure | gold-sensitive names cheaper to fade | (modest BTC drag) |
| Real 10Y | falling (≤-10bps) | growth lift | TLT lift, lock in | growth momentum lift | unwind defensives | (modest BTC lift) |
| Breakevens | rising (>2.6%) | cyclicals tailwind | NUE/X/CAT cyclicals lift | momentum into materials | take profit on disinflation trades | (low impact) |
| Breakevens | falling (<1.8%) | TLT favored | TLT favored | defensives rotate in | accumulate quality bond proxies | (low impact) |
| WTI | up (≥+3%) | XOM/CVX lift, transport drag | XOM/CVX lift | energy momentum lift | take profits if held energy | (low impact) |
| WTI | down (≤-3%) | XOM/CVX drag, transport lift | XOM/CVX drag | rotate from energy | accumulate energy on dislocation | (low impact) |

Each bullet should bake in the live numeric: "BTC: DXY +1.0% / 5d
strengthening — direct headwind through valuation channel; favor
scaling-in over fresh aggressive buys."

Render at the **top** of the cross_asset section, before the existing
QUOTABLE block. Keeps the per-personality lift cheap and deterministic.

Wiring: pass `personality_key` through `ctx` in
`assemble_toolkit_prompt`; the dispatch lambda already supports it from
my reverted attempt — the diff is small.

### Proposed next step (Plan B — accept the zero)

The data is in the prompt at decent weight. If a future trading model
wants it, it can read it. Move on; revisit if a model upgrade changes
attention patterns.

### Recommendation
Plan A. Two reasons: (1) the channel × personality lookup is well-defined
and doesn't need creativity; (2) the same hook pattern already works for
the three cited modules — there's evidence the LLMs engage with labeled
per-symbol bullets, just not with abstract context.

---

## Other open work

### Roadmap status (`docs/trader-improvements-roadmap.md`)

| # | Item | Status |
|---|---|---|
| 1 | BTC on-chain & derivatives | Done (shipped earlier) |
| 6 | Backtesting framework + conflict detection | Done (caught 11 conflicts) |
| 7 | Fleet conviction module | Done, adopted |
| 3 | Cross-asset macro | Shipped but unused — see above |

Everything else in the roadmap is parked. The full list is in
`docs/trader-improvements-roadmap.md` under Tiers 1-4.

### Adoption-monitoring gap
The `/api/analytics/modules` endpoint tracks per-module win rate and PnL,
but doesn't surface low-adoption modules. Cross_asset isn't even in the
attribution table because no trade has cited it. A "cite-rate" column
would catch this class of failure earlier.

### Module attribution highlights (all-time, as of 2026-06-11)
- `signal_ranker`: 69% buy win rate on 55 trades, $20k PnL — strongest
  buy-quality signal
- `technicals`: 58% / $44.7k — biggest cumulative PnL on volume
- `fundamentals`: 63% / $19.5k
- `momentum`: 48.6% — weakest buy quality, propped up by YOLO Bot
- `optimizer`: 45.3% sell win rate, –$2.3k combined — sells timing badly
- `trade_context`: 1 buy + 21 sells (71% sell win) — used to exit, not enter

### Leaderboard (2026-06-11 close)
- Top: YOLO Bot Mistral Medium +15.98%, YOLO Bot Mistral Large +8.25%,
  Vanilla Mistral Medium +6.69%
- Bottom: Crypto Chad Mistral Large 2 –7.20%, Crypto Chad New variants
  clustered –2% to –4% (still scaling in through the BTC drawdown)
- 23-point spread top to bottom

### Other things worth knowing
- Crypto Chad's tier framework is working: trims only on concentration
  cap, never on weakness alone. Original Chad on 2026-06-11 sold BTC at
  20.3%→25% (concentration), holding the thesis intact per
  ACCUMULATION_ZONE.
- Peer learning is live via four mechanisms: `_format_cross_trader_positions`,
  `_compute_peer_exit_warnings`, `build_performance_intelligence`, and
  `fleet_conviction`. Reflections are NOT shared across traders yet — a
  natural extension if anyone wants to add it.
- Prompt size is real: Crypto Chad New's assembled prompt is ~39k chars.
  Mistral Large handles it. Mistral Small probably attends less to
  mid-prompt content — that's part of why cross_asset (mid-prompt) is
  ignored.

---

## Critical file references

| File | Purpose |
|---|---|
| `backend/app/services/market_brief.py:1612-1742` | `_fetch_cross_asset()` |
| `backend/app/services/rag_toolkit.py:_format_cross_asset` | The render — needs `_compute_macro_implications` added in front |
| `backend/app/services/rag_toolkit.py:_MODULE_FORMATTERS` | Dispatch table — already wires `cross_asset` |
| `backend/app/services/rag_toolkit.py:assemble_toolkit_prompt` | Where `ctx` is built — needs `personality_key` added |
| `backend/app/services/ai_trader.py` | Per-personality toolkit configs around lines 41-449 |
| `backend/app/services/fleet_signals.py` | Pattern to mirror for any cross-trader/cross-module aggregation |

## Test pattern

To verify adoption after any change:

```bash
curl -s "https://papertrade-backend-333762334828.us-east1.run.app/api/analytics/reasoning?days=1" \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
trades = []
for date, ts in (d.get('dates') or {}).items():
    for t in ts: t['date'] = date; trades.append(t)
keywords = ['dxy', 'dollar', 'real yield', 'breakeven', 'wti', 'crude']
hits = [t for t in trades if any(k in (t.get('reasoning') or '').lower() for k in keywords)]
print(f'{len(hits)}/{len(trades)} trades cite cross_asset language')
"
```

Pipeline runs at 5:00 PM ET (brief), 5:05 PM ET (local Gemma), 5:10 PM ET
(trading + commentary). Adoption visible ~5:15 PM ET.

---

## What NOT to do

- Don't add a new Gemma preprocessor without confirming prompt size and
  parallelism shape against the 8GB ceiling
- Don't push to main without explicit user authorization; the user's
  workflow is local commits + direct Cloud Run deploys, not PR-based
- Don't suggest Gemini as an LLM replacement — free tier is too limited
  for traders (see `memory/feedback_no_gemini.md`)
- Don't mock the database in tests — integration tests must hit a real
  DB (existing convention)
