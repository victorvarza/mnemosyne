# opencode-bench A/B: Mnemosyne plugin off vs. on

[opencode-bench](https://github.com/anomalyco/opencode-bench) runs a coding
agent on real GitHub commits. Three LLM judges then score the agent's diff on
API signature, logic equivalence, integration points, test coverage and project
checks. It is not a memory QA benchmark, so the fitting validation is an A/B
run: the same tasks and model with the plugin off and on.

**Status: not run yet.** No results in this directory are real until
`results/` exists and `summarize.py` has been run on it.

## Arms

| Arm | Plugin | Retrieval | Memory DB |
|---|---|---|---|
| `off` | not loaded | — | — |
| `on` | loaded | similarity + Phase 2 usefulness model (the shipped system) | fresh, seeded |
| `on-sim` | loaded | similarity only (`MNEMO_USEFULNESS_MODEL` points at a missing file) | fresh, seeded |

Each run gets fresh, isolated OpenCode config and data directories, so runs
don't share sessions and your own OpenCode setup is untouched.

## Tasks and seed memories

`seeds/<task>.txt` holds what an earlier session on that repository would
plausibly have remembered: conventions, commands and layout. Every seed comes
from the repository **at the task's starting commit** (docs, build and test
config, the file tree). None comes from the task's `diff.patch` or target
commit. Each seed file lists its sources.

| Task | Seeds | Injected for the task prompt (`on` / `on-sim`) | Note |
|---|---|---|---|
| `datadog-lambda-python` | 6 | 5 / 5 | No `AGENTS.md` in the repo, so memory is the only source of these conventions. The task where memory should matter most. |
| `sst-opencode-formatting` | 6 | **0** / 5 | Prompt is one short sentence; the usefulness model rejects every seed. Repo `AGENTS.md` already covers most seeds. |
| `sst-opencode-session-rename` | 7 | **0** / 5 | Same as above. |

The "injected" counts come from `mnemo context` on the task prompt with
the current model (each run saves its own preview in
`injection-preview.txt`). For both sst/opencode tasks the `on` arm is
effectively the `off` arm. That is a real property of the system, which
`on-sim` makes measurable.

## Prerequisites

- [Bun](https://bun.sh) ≥ 1.2.21 and an opencode-bench checkout:
  `git clone https://github.com/anomalyco/opencode-bench && cd opencode-bench && bun install`
- `OPENCODE_API_KEY`: an OpenCode Zen key. The agent model **and** the three
  judges (Claude Sonnet 4.5, GPT-5 Codex, Kimi K2) run through it, so every run
  costs money.
- In this repo: `uv sync`, `npm install`, and a trained usefulness model
  (`make train`).
- Ollama with `nomic-embed-text` for the plugin's embeddings (`MNEMO_OLLAMA_URL`).

The runner installs OpenCode 1.18.34 under `results/.opencode-v1/` and puts it
first on `PATH`. opencode-bench's SDK spawns `opencode serve` and speaks the V1
server API, and the plugin uses the V1 plugin API, so an OpenCode 2 install on
your `PATH` must not be used.

## Run

Start small to check the setup and cost, then scale up:

```bash
export OPENCODE_BENCH_DIR=~/src/opencode-bench OPENCODE_API_KEY=...

# smoke test: one task, one run per arm
TASKS=datadog-lambda-python RUNS=1 bench/opencode-bench/run-ab.sh

# full A/B: 3 tasks × 3 arms × 3 runs = 27 evaluations
bench/opencode-bench/run-ab.sh

python3 bench/opencode-bench/summarize.py bench/opencode-bench/results
```

Options are environment variables: `MODEL` (default `opencode/qwen3-coder`;
must be one registered in opencode-bench's `src/agents/opencode.ts`), `TASKS`,
`RUNS` (default 3, as in opencode-bench's CI), `ARMS` (default
`off on on-sim`) and `RESULTS`. Finished runs are skipped on re-run, so an
interrupted run can be resumed.

## Outputs

`results/<task>/<arm>/run<N>/` contains:

- `bench.log`: opencode-bench output (final score, per-criterion judge scores, cost)
- `plugin.log`: Mnemosyne log lines from the OpenCode server log (initialized, injections)
- `injection-preview.txt`: what `mnemo context` returns for the task prompt (`on` arms)

`summarize.py` prints final score mean ± sd per task and arm, the difference
from `off`, per-criterion averages, and how many runs injected memories. A run
is excluded as invalid if the plugin initialized in `off`, or didn't in an `on`
arm.

## Reading the result

- With 3 runs per arm, judge variance is large. Report the mean ± sd and treat
  a difference smaller than about one sd as no effect.
- A positive Δ on `datadog-lambda-python` alongside ≈0 on the sst/opencode
  tasks fits the hypothesis "memory helps where the repo doesn't document its
  conventions for agents".
- `on-sim` vs. `on` is the end-to-end test of the Phase 2 model.
