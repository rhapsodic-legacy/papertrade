# Local Gemma Preprocessing — DISABLED (2026-06-23)

**Status:** The daily local Gemma preprocessing job is **disabled** on the
8GB Mac Mini. Traders run on raw market-brief data (no Gemma enrichment).
**This is reversible** — see "How to re-enable" below. Re-enable once on
hardware with more RAM (16GB+).

---

## What was disabled

The launchd job **`com.papertrade.gemma-preprocess`**, which fired daily at
**5:05 PM local** and ran `backend/scripts/local_preprocess.py`. That script
loads Gemma 4 e2b via Ollama and runs the preprocessors in
`backend/app/services/gemma_preprocess.py`:

- `cluster_headlines` — groups headlines into themed clusters (16k-token call)
- `summarize_analyst_consensus` — per-symbol analyst narrative (~20 calls)
- `summarize_insider_flow` — per-symbol insider patterns (~8 calls)
- `narrate_movers` — why each gainer/loser moved (~10 calls)
- analyst blog scraping + `summarize_analyst_article` / `compress_analyst_digest`

These write enrichment fields back into the day's `market_briefs` row
(`headline_clusters`, `analyst_consensus`, `insider_summary`, movers narrative,
analyst digest), which the RAG toolkit surfaces to traders.

**The scripts themselves are untouched** — only the OS-level launchd trigger
was disabled. `local_preprocess.py` and `gemma_preprocess.py` remain fully
intact so re-enabling is a one-step OS change, not a code restore.

## Why (the decision)

- The Mac Mini has **8GB RAM**. Gemma 4 e2b is **~7GB**. Loading it at 5:05 PM
  leaves almost no headroom; under any memory pressure the box **OOMs, freezes,
  and forces a hard reboot.** This has recurred (e.g. 2026-06-12, and again
  **2026-06-23 ~17:05 EDT** — the crash that prompted this change). See
  `CLAUDE.md` ⚠️ HARD CONSTRAINT and `memory/feedback_hardware_8gb_ram.md`.
- A job that crashes the machine mid-run **doesn't deliver the enrichment
  anyway** — so disabling it loses nothing in practice while ending the crashes.
- The enrichment has a **graceful fallback already built in**: when the
  preprocessing is absent, traders simply use raw brief data (quotes, news,
  fundamentals, technicals, sentiment). Nothing breaks.

### Why not re-host it in the cloud instead (Option B, deferred)

Re-hosting as-is is **~39+ LLM calls/day** (the preprocessors loop per symbol:
~20 analyst + ~8 insider + ~10 movers + a 16k-token headline call), roughly
double the daily trading volume. The preprocessors are written `tier="local_only"`
specifically because doing this on a paid API is expensive — it runs on free
local Gemma for a reason. On the current strained Mistral free tier (key 1 was
exhausted mid-June), porting it to Mistral would worsen the budget crunch, and
the prompts are tuned for Gemma's thinking-model `<think>` format so they'd need
re-tuning for another model. That's a real project, not a safe toggle — see
"Future: proper cloud re-host" below.

## What traders lose while disabled

The Gemma-derived enrichment in the daily brief:
headline clusters, per-symbol analyst-consensus narratives, insider-flow
summaries, movers narratives, and the analyst-blog digest. Traders still receive
all **raw** data and trade normally — they just don't get the pre-synthesized
Gemma layer on top.

---

## How it was disabled (exact mechanism)

```bash
# 1. Stop the running/loaded job
launchctl bootout gui/$(id -u)/com.papertrade.gemma-preprocess
#    (older macOS fallback: launchctl unload ~/Library/LaunchAgents/com.papertrade.gemma-preprocess.plist)

# 2. Prevent it returning on reboot/login — rename the plist (kept for restore)
mv ~/Library/LaunchAgents/com.papertrade.gemma-preprocess.plist \
   ~/Library/LaunchAgents/com.papertrade.gemma-preprocess.plist.disabled
```

The `com.papertrade.intraday` job (deterministic conditional-order checks, no
Gemma) was **left running** — it doesn't touch Ollama and protects positions.

The Ollama `serve` daemon may keep running idle (harmless — it only consumes
significant RAM when a *model* is loaded, which no longer happens). To remove
even that footprint: `brew services stop ollama`.

---

## How to RE-ENABLE (once on better hardware — 16GB+ RAM)

```bash
# 0. Prereqs: Ollama installed and the model pulled
ollama --version
ollama pull gemma4:e2b          # ~7GB; only safe with comfortable RAM headroom

# 1. Restore the plist name
mv ~/Library/LaunchAgents/com.papertrade.gemma-preprocess.plist.disabled \
   ~/Library/LaunchAgents/com.papertrade.gemma-preprocess.plist

# 2. Load it back into launchd
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.papertrade.gemma-preprocess.plist
#    (older macOS fallback: launchctl load ~/Library/LaunchAgents/com.papertrade.gemma-preprocess.plist)

# 3. Verify it's registered (fires daily at 5:05 PM local)
launchctl list | grep gemma-preprocess

# 4. Smoke-test a manual run on the NEW hardware and WATCH MEMORY:
cd /Users/jessepassmore/Desktop/Programming_Pizazz/fintech_support/backend
./venv/bin/python3 scripts/local_preprocess.py
#    watch RAM in Activity Monitor; check the log:
cat /tmp/gemma-preprocess.log

# 5. Confirm the enrichment landed in today's brief (these should be non-null):
#    headline_clusters, analyst_consensus, insider_summary, movers narrative
```

If the manual run is stable and the brief gets enriched, the daily 5:05 PM job
will keep it current. If the box still struggles, prefer Option B below.

---

## Future: proper cloud re-host (Option B, if you want enrichment without local Gemma)

Do this *after* the Mistral monthly reset and with quality validation — not in a
budget crunch. Sketch:

1. **Batch the per-symbol loops** so each preprocessor is ONE call covering all
   symbols, not one-per-symbol. This collapses ~39 calls/day → ~4/day, making
   cloud cost trivial. (Edit `gemma_preprocess.py`: `summarize_analyst_consensus`,
   `summarize_insider_flow`, `narrate_movers` to accept the full set and return
   a keyed result; update parsers.)
2. **Route those few calls to a provider with headroom** — NVIDIA (separate
   quota from the strained Mistral keys) is the natural choice. Change the
   `tier="local_only"` calls to a cloud path, or add a `tier="cloud"` route in
   `app/services/llm.py`.
3. **Re-tune the prompts** for the target model — the current prompts assume
   Gemma's `<think>` thinking-model format and large `max_tokens` budgets.
4. **Run it in Cloud Run Phase 1** (`market_brief.py` already has the hook —
   today it skips because Ollama is unavailable on Cloud Run).
5. Validate output parity against the old Gemma enrichment before relying on it.

---

## Related references
- `CLAUDE.md` — ⚠️ HARD CONSTRAINT (8GB RAM) and the pipeline architecture
- `docs/handoff-cross-asset-and-next-steps.md` — hardware constraint history
- `memory/feedback_hardware_8gb_ram.md`
- Disabled plist: `~/Library/LaunchAgents/com.papertrade.gemma-preprocess.plist.disabled`
- Scripts (intact): `backend/scripts/local_preprocess.py`, `backend/app/services/gemma_preprocess.py`
