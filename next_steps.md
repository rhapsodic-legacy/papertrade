# Next Steps — Swarm Intelligence & Exit-Quality Feedback

Date written: 2026-06-14

This document specs three related features aimed at one problem: traders give
back gains on weak exits (attribution shows momentum-driven sells winning ~40%
of the time and optimizer-driven sells running negative). The approach is
**emergent, not enforced** — we change what the traders *know*, never what
they're *allowed* to do. No hard rules in the traders. We then watch whether
behavior adapts.

See also: `docs/handoff-cross-asset-and-next-steps.md` for system state.

---

## ⚠️ Guiding constraints (read first)

1. **No hard/deterministic rules in the traders.** Behavior must be emergent
   from prompts, conviction, and data. Influence via the named-hook pattern;
   never override the LLM's decision in code. ("Phase 2 — enforced exit
   discipline" is dead; enforcement was its entire premise.)
2. **BTC/ETH are conviction holds.** Never design anything that sells BTC/ETH
   into a downturn. Downturns are for accumulating. This lives in the Crypto
   Chad prompts and is working — do not "fix" it with rules.
3. **No quarter awareness in traders.** They optimize for profit on the assets'
   own timescales. Quarter-over-quarter is a yardstick for us only.
4. **8GB local RAM ceiling.** No new local Gemma calls without checking fit.
   The trading phase runs on Cloud Run, so a paid Mistral call there is fine if
   needed; prefer deterministic aggregation where it suffices.

---

## The critical finding that shapes all of this

Injecting reflection lessons into trader prompts was **already tried, per
trader, and got zero genuine citations for 21+ days across multiple
iterations** before being deprecated on 2026-05-17
(`backend/app/services/ai_trader.py:2524`, the comment block in the trading
path). Reflections still run and feed analytics + outcome scores — they're just
no longer injected as a prompt block.

The channel that **does** get cited is `trade_context` — specifically its
pre-synthesized "KEY PATTERN" line (`backend/app/services/rag_toolkit.py:1175`,
`_format_trade_context`). All 7 personalities carry `trade_context` at weight 7,
so it reaches every trader.

**Implication:** a wall of reflective lessons gets ignored; one quotable,
data-anchored line lands. This is the same lesson as the cross_asset saga
(abstract context ignored; labeled per-symbol hooks cited — see
`docs/handoff-cross-asset-and-next-steps.md` and the named-hook pattern). Every
feature below is designed to ride a cited channel, not repeat the dead block.

---

## Feature 1 — Exit-quality feedback (build first; highest confidence)

**Goal:** each trader sees, in the line it already quotes, how often its own
exits were *weak* — so better exit behavior can emerge.

**Definition of a "weak exit" (measurable):** a sell that realized a loss AND
the price rebounded afterward (e.g. within ~5 days). The existing reflection
outcome-scoring already captures the "sold then it bounced" signal
(`trade_reflections.outcome_score`; a sell followed by a price rebound scores
badly). Reuse that rather than inventing a new definition. Take-profit sells and
thesis-based exits are NOT weak.

**Delivery (ride the proven channel):**
- Add a `weak_exit` stat to the per-trader `trade_context` data
  (computed alongside the existing track-record stats — see
  `_compute_trader_intel` / `build_performance_intelligence` in
  `ai_trader.py`, and the `trade_context` dict consumed by
  `_format_trade_context`).
- Surface it in the **KEY PATTERN line** (`rag_toolkit.py:1175-1218`), e.g.:
  > KEY PATTERN: ... 7 of your last 10 exits were weak — you sold into weakness
  > and price rebounded within 5 days (avg exit −2.3%). Stop selling weakness.

**Why high confidence:** it's the one self-feedback channel that demonstrably
changes behavior, carried by all personalities. Small diff.

**Anti-convergence note:** this is each trader's OWN data — no herding risk.

---

## Feature 2 — "No weak exits!" prompt language (build with Feature 1)

**Goal:** the intervention whose effect Feature 1 measures. A clean closed loop:
harsh language in → weak-exit metric out → watch whether traders adapt.

**Placement:** the shared `## Sell Discipline (CRITICAL)` section of the system
prompt (`backend/app/services/ai_trader.py:644`), which all 25 traders see.
There is **no per-trader `memory.md` file** — a trader's "memory" is the
runtime-assembled trade history plus this shared system prompt. This is the
correct home for global, harsh framing.

**Content:** short, blunt, unmistakable — e.g. "NO WEAK EXITS. Selling a
position into weakness and watching it rebound is the most expensive mistake you
make. Do not sell because price is down — sell because the thesis is done or the
gain is realized." (Final wording TBD; keep it sharp.)

**Open question — per-personality?** Default: global only (shared prompt). Could
later add personality-specific phrasing, but global first to keep the experiment
clean. Respect BTC/ETH conviction — the language must not nudge selling
crypto into weakness (it shouldn't, since "don't sell into weakness" aligns).

**Measurement:** the Feature 1 weak-exit rate, tracked per trader before/after.
Cite-rate of the new KEY PATTERN content via `/api/analytics/modules`.

---

## Feature 3 — Shared reflections / swarm intelligence (build second; experimental)

**Goal:** pool what the fleet has learned so each trader benefits from the
swarm's mistakes and wins — humans learn from each other; so should the AIs.

**The hard part is delivery, not aggregation.** The per-trader reflection block
already failed (see critical finding). A naive fleet-wide "FLEET LESSONS" digest
would almost certainly die the same way. To actually change behavior:

- **Deliver as a quotable, situation-attached hook**, not a digest block. Surface
  the single highest-signal fleet lesson *relevant to a symbol or setup in play
  today*, in the named-hook style — not a wall of pooled lessons.
- **Share principles, NEVER trades.** This codebase has heavy anti-convergence
  machinery (independent personalities are the whole point). Pooling "what to
  buy" causes herding — the opposite of the goal. Pool meta-lessons:
  - GOOD (swarm wisdom): "selling BTC into RSI<30 panic has cost the fleet
    repeatedly."
  - BAD (herd): "the fleet is buying NVDA."

**Aggregation (reuse existing code):** `synthesize_personal_rules`
(`backend/app/services/reflection.py:336`) already mines ONE trader's
reflections into a ranked, deduped, quality-filtered rulebook (keeps lessons
with `|outcome_score| >= 0.4` that pass `_is_substantive_rule` — i.e. cite
numbers/named indicators, not platitudes). A fleet version drops the
`.eq("user_id", ...)` filter and ranks across all traders. Prefer deterministic
aggregation (no LLM) to start; a single Cloud-Run Mistral synthesis call is an
option if deterministic ranking proves too noisy.

**Open questions:**
- How tightly to attach a fleet lesson to "today's setup" vs. show the top
  1-2 fleet lessons generally. (Tighter = more likely cited, more work.)
- Whether to tag lessons by source personality/diversity to preserve identity.

**Measurement:** does the shared lesson get cited (cite-rate), and does the
fleet-wide weak-exit / outcome-score trend improve over several runs?

---

## Suggested build order

1. **Features 1 + 2 together** (exit-quality metric + KEY PATTERN line + harsh
   Sell Discipline language). Measurable pair, high confidence, small diff.
2. **Feature 3** (shared reflections via cited-channel/named-hook delivery,
   principles-not-trades). More experimental; build after 1+2 are observed.

## How we'll know it's working

- Per-trader weak-exit rate (Feature 1 metric) trends down after Feature 2 ships.
- New KEY PATTERN / fleet-lesson content shows up in trade reasoning
  (cite-rate on `/api/analytics/modules?cite_days=1`).
- Module attribution: momentum/optimizer SELL win rates improve over time.
- No convergence spike (watch `/api/analytics/convergence-quality`).

## Explicitly out of scope

- Any hard-coded exit rule, forced stop, or sizing override in the traders.
- Any quarter-boundary logic in the traders.
- Anything that could sell BTC/ETH into a downturn.
