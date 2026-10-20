# Mnemosyne — Demo Walkthrough

A self-contained script for presenting Mnemosyne to an audience. It takes you
from a cold machine to the project's headline result: **memory makes an AI
assistant ~6.6× more accurate, but naive memory is actively harmful, and
lifecycle management fixes it.**

> ⚠️ Educational / research prototype. The security tooling is for authorized,
> controlled environments only.

**Total time:** ~15 min after model downloads. Budget an extra ~5 min the first
time for the `qwen2.5:7b` pull (~4.7 GB).

---

## The one-sentence pitch

> Mnemosyne gives an AI assistant persistent, personalized memory that lives
> **locally** on your laptop (SQLite + `sqlite-vec`), while only the model
> inference runs on a worker. It retrieves the memories relevant to each
> prompt, filters them with a trained model, keeps the store healthy, and
> measures exactly when memory helps versus when it introduces bias.

Keep this diagram on screen while you talk:

```
  Laptop (owns the data)                 Worker (stateless)
  ┌───────────────────────┐              ┌────────────────────┐
  │ mnemo CLI / OpenCode   │   HTTP       │ Ollama             │
  │ plugin                 │ ───────────► │  qwen2.5:7b (LLM)  │
  │ SQLite + sqlite-vec    │ ◄─────────── │  nomic-embed-text  │
  │ memory.db              │  embeddings  │                    │
  └───────────────────────┘   + answers  └────────────────────┘
```

---

## 0. One-time setup

Run these once before the audience arrives (the model pull is the slow part).

```bash
# From the repo root: /Users/vvarza/git/work/reskilling/mnemosyne

# 1. Start the inference worker and pull the two models
ollama serve &                      # leave running in the background
ollama pull nomic-embed-text        # embeddings (~140M, instant on Metal)
ollama pull qwen2.5:7b              # LLM (~4.7 GB)

# 2. Point the client at the worker
export MNEMO_OLLAMA_URL=http://localhost:11434
export MNEMO_EMBED_MODEL=nomic-embed-text
export MNEMO_LLM_MODEL=qwen2.5:7b

# 3. Make the `mnemo` CLI available on PATH for this shell
source .venv/bin/activate            # the venv already has mnemo installed
#   (if the venv is missing: `make client-setup`)

# 4. Start from a clean memory store so the demo is reproducible
rm -f ~/.local/share/mnemo/memory.db

# 5. Smoke test
mnemo stats                          # should print "Total memories: 0"
```

> If `mnemo: command not found`, you skipped step 3. Alternatively prefix every
> command with `uv run` (e.g. `uv run mnemo stats`).

---

## Act 1 — "It remembers you" (the hook)

**Goal:** show memory changing an answer, in under 2 minutes.

The repo ships a ready-made demo that stores 7 sample memories and runs 3
queries, printing the retrieved memories, the injected context block, and the
personalized LLM answer.

```bash
make demo        # == uv run python demo.py
```

**What to say while it runs:**
- "It embeds each memory and stores it locally — nothing left the laptop except
  the embedding request."
- When the query results print: "For *'what programming language does the user
  prefer?'* it pulled back the Python memory by **semantic** similarity, not a
  keyword match."
- Point at the `## Remembered Context` block: "This is literally what gets
  appended to the system prompt. Provenance-labelled — every line carries its
  memory type and trust level."

---

## Act 2 — Drive it yourself (make it tangible)

**Goal:** let the audience see the full round-trip with live commands.

```bash
# Store a few memories (semantic by default, trust = user_stated)
mnemo add "User prefers Python over Java for backend services"
mnemo add "Production database is PostgreSQL 16 in eu-west-1"
mnemo add "Always use type hints in function signatures" --type procedural

# Semantic retrieval — note the query words don't appear in the memory
mnemo search "what database do we run in prod?"

# Show the EXACT block the OpenCode plugin injects into the prompt
mnemo context "what database do we use?"

# Inventory + provenance
mnemo list
mnemo stats
```

**Talking points:**
- `search` prints a ranked table *and* the injectable block. Columns show
  **score**, **type** (semantic/episodic/procedural), and **trust**
  (user_stated/agent_inferred/…).
- `mnemo context` is the plugin's integration point — bare stdout, empty when
  nothing is relevant. "This is what the AI assistant sees automatically on
  every turn."
- `--db` keeps stores isolated; the default is `~/.local/share/mnemo/memory.db`.

---

## Act 3 — The money shot: when memory *hurts*

**Goal:** the result that makes Mnemosyne more than a RAG toy.

This is the Phase 4 ablation. It runs a synthetic multi-session dataset under
four configurations and reports QA F1, Recall@5, and the **stale-bias rate** —
the fraction of "the fact changed" questions answered with the *old* value.

The results are already committed in `data/benchmark-report.json`, so you can
**present the table without waiting** (the live run takes a few minutes):

| Configuration    | Mean F1   | Recall@5 | Stale-bias rate |
|------------------|-----------|----------|-----------------|
| no-memory        | 0.091     | —        | — (3/10 by chance) |
| memory-only      | 0.599     | 1.00     | 1.00 (10/10)    |
| memory+selection | 0.575     | 1.00     | 1.00 (10/10)    |
| memory+lifecycle | **0.652** | 1.00     | **0.00** (0/10) |

**The three-beat story — say these in order:**
1. **Memory helps — a lot.** `memory-only` is **6.6×** the F1 of the stateless
   baseline (0.599 vs 0.091). Retrieval is perfect (Recall@5 = 1.00).
2. **But naive memory is biased.** `memory-only` answers **10/10** update
   questions with the *superseded* value ("You live in Bucharest" after the user
   moved). Both the old and new fact come back with the same
   `[semantic|user_stated]` tag and no date — the LLM can't tell which is
   current.
3. **Lifecycle fixes it.** Conflict resolution (`memory+lifecycle`) drops stale
   bias **1.00 → 0.00** *and* raises F1 to the best of all configs (0.652).

**The honest nuance (great for a sharp audience):** the learned Phase 2
selection model *doesn't* fix the bias — it keeps every gold fact but can't tell
stale from fresh, so F1 even dips slightly. An earlier 9-feature version learned
a spurious negative weight on access count and stopped injecting a memory after
3 uses. That's why the live model uses only similarity + recency + trust. (Full
analysis in `docs/evaluation.md`.)

**Optional — run it live** (temperature 0, so it reproduces the table):

```bash
# Train the Phase 2 model first so the +selection row isn't skipped
make train        # generate-dataset → label-usefulness → train-usefulness
make benchmark    # writes data/benchmark-report.json and prints the table
```

---

## Act 4 — Lifecycle, live (optional, ~2 min)

**Goal:** show *how* Phase 3 kills the stale fact, not just that it does.

```bash
# Create a genuine conflict in the store
mnemo add "User lives in Bucharest"
mnemo add "User lives in Amsterdam"

# Preview what lifecycle would do — nothing is deleted
mnemo lifecycle --dry-run --resolve-conflicts
```

Point at the **"Conflicts found"** section: it pairs the two near-identical
memories, keeps the fresher one, and marks the older one stale. Drop `--dry-run`
to actually apply it. Also mention: `lifecycle` runs **decay** (exponential by
last-access) and **dedup** (merges cosine-near-duplicates) in the same pass.

---

## Act 5 — The real integration: OpenCode plugin (optional, strongest close)

**Goal:** show memory working inside an actual AI assistant, not just a CLI.

The plugin lives at `.opencode/plugins/mnemosyne/index.js` and OpenCode 2 loads
it automatically for this repo. On every turn it:
1. **Captures** pattern-matched preferences from your prompt (`prompt` hook).
2. **Injects** relevant memories into the system prompt (`context` hook → the
   same `mnemo context` you ran in Act 2).
3. **Re-injects** on window compaction so memory survives long sessions.

The committed live-session evidence (`docs/plugin.md`) makes the point cleanly —
read it aloud:

```text
# plugin ON
> Our production database runs on PostgreSQL 16 in the eu-west-1 region of AWS.

# plugin OFF, same question
> The production database is PostgreSQL running in the us-east-1 AWS region.
```

"Same model, same question. Without memory it guesses a plausible default and
gets the region wrong. With Mnemosyne it answers with the stored truth."

To reproduce headlessly: `bash bench/live-session/run.sh` (uses OpenCode 1.18.x
against local Ollama in an isolated temp config; logs land in
`bench/live-session/logs/`).

---

## Act 6 — Security assessment angle (optional, 1 min)

Mnemosyne reuses the same local-memory engine to retain **authorized**
engagement context across sessions. Everything is gated behind an explicit
authorization record.

```bash
# Scan THIS project's source with Bandit/Semgrep/Trivy (whichever are installed)
mnemo scan

# Authorized-assessment memory workflow (local-only; never contacts a target)
mnemo assess create demo-lab --target demo-app \
  --authorized "I confirm approval ticket SEC-123"
mnemo assess record demo-lab "Reviewed auth config" --kind observation
mnemo assess list demo-lab
```

**Be explicit for the audience:** the authorization string is an *audit note*,
not RBAC or proof of approval. `assess source-scan` only reads **local** source
and never connects to the declared target. This is educational tooling.

---

## Cleanup

```bash
rm -f ~/.local/share/mnemo/memory.db       # reset the demo store
# (ollama serve keeps running; stop it however you started it)
```

---

## Cheat sheet — if something breaks

| Symptom | Fix |
|---|---|
| `mnemo: command not found` | `source .venv/bin/activate`, or prefix with `uv run` |
| `Ollama not reachable at …` | `ollama serve &`, then re-check `MNEMO_OLLAMA_URL` |
| `memory+selection … skipped` | `make train` first (it needs the Phase 2 model) |
| Weird results from old data | `rm -f ~/.local/share/mnemo/memory.db` and restart |
| Want a throwaway store | add `--db /tmp/demo.db` to any memory command |

## The 15-second takeaway to leave them with

> Local-first memory makes the assistant dramatically more accurate (6.6× F1),
> but memory without hygiene silently serves stale facts 100% of the time.
> Mnemosyne's contribution is measuring that bias and fixing it — lifecycle
> management takes stale bias to zero while improving accuracy.
