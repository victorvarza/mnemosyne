#!/usr/bin/env bash
# opencode-bench A/B: the same tasks and model with the Mnemosyne plugin off vs. on.
#
# Each run gets fresh, isolated OpenCode config/data dirs (your own OpenCode
# setup is untouched) and, for the "on" arm, a fresh memory DB seeded from
# seeds/<task>.txt. Results land in $RESULTS/<task>/<arm>/run<N>/; summarize
# them with summarize.py.
#
# Required:
#   OPENCODE_BENCH_DIR  clone of https://github.com/anomalyco/opencode-bench with `bun install` done
#   OPENCODE_API_KEY    OpenCode Zen key; used by the agent model and the three LLM judges (costs money)
# Optional:
#   MODEL     agent model, one registered in opencode-bench's src/agents/opencode.ts (default opencode/qwen3-coder)
#   TASKS     space-separated task IDs (default: the three tasks that have seed files)
#   RUNS      runs per task and arm (default 3, as in opencode-bench's CI)
#   ARMS      any of: off (no plugin), on (plugin + usefulness model),
#             on-sim (plugin, similarity-only retrieval). Default "off on on-sim".
#   RESULTS   output dir (default bench/opencode-bench/results)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
: "${OPENCODE_BENCH_DIR:?set OPENCODE_BENCH_DIR to an opencode-bench checkout}"
: "${OPENCODE_API_KEY:?set OPENCODE_API_KEY (OpenCode Zen) for the agent and the judges}"
MODEL="${MODEL:-opencode/qwen3-coder}"
TASKS="${TASKS:-datadog-lambda-python sst-opencode-formatting sst-opencode-session-rename}"
RUNS="${RUNS:-3}"
ARMS="${ARMS:-off on on-sim}"
RESULTS="${RESULTS:-$HERE/results}"
OPENCODE_V1_VERSION="1.18.34"
MNEMO_BIN="$REPO/.venv/bin/mnemo"

command -v bun >/dev/null || { echo "bun is required (opencode-bench runs on Bun >= 1.2.21)" >&2; exit 1; }
[ -x "$MNEMO_BIN" ] || { echo "run 'uv sync' in $REPO first ($MNEMO_BIN missing)" >&2; exit 1; }
[ -d "$REPO/node_modules/@opencode-ai/plugin" ] || { echo "run 'npm install' in $REPO first" >&2; exit 1; }
[ -f "${MNEMO_USEFULNESS_MODEL:-$HOME/.local/share/mnemo/usefulness-model.json}" ] \
  || echo "warning: no usefulness model; 'mnemo context' will use similarity only" >&2

# opencode-bench's SDK spawns `opencode serve` from PATH and speaks the V1
# server API. Pin a local OpenCode 1.x so a system-wide OpenCode 2 is not used.
V1_PREFIX="$RESULTS/.opencode-v1"
if [ ! -x "$V1_PREFIX/node_modules/.bin/opencode" ]; then
  npm install --silent --prefix "$V1_PREFIX" "opencode-ai@$OPENCODE_V1_VERSION"
fi
export PATH="$V1_PREFIX/node_modules/.bin:$PATH"
echo ">>> opencode $(opencode --version) | model $MODEL | runs $RUNS | arms: $ARMS"

task_prompt() { # first prompt of a task, from its prompt.yml
  python3 - "$OPENCODE_BENCH_DIR/src/tasks/$1/prompt.yml" <<'EOF'
import re, sys
text = open(sys.argv[1]).read()
m = re.search(r'^\s*prompt:\s*(.+)$', text, re.M)
value = m.group(1).strip() if m else ""
if value[:1] in "\"'":
    value = value[1:-1]
print(value)
EOF
}

write_config() { # $1 = config dir, $2 = arm
  mkdir -p "$1/opencode"
  if [ "$2" != off ]; then
    printf '{\n  "$schema": "https://opencode.ai/config.json",\n  "autoupdate": false,\n  "plugin": ["file://%s/opencode-plugin.js"]\n}\n' "$REPO" \
      > "$1/opencode/opencode.json"
  else
    printf '{\n  "$schema": "https://opencode.ai/config.json",\n  "autoupdate": false\n}\n' \
      > "$1/opencode/opencode.json"
  fi
}

for task in $TASKS; do
  [ -d "$OPENCODE_BENCH_DIR/src/tasks/$task" ] || { echo "unknown task $task" >&2; exit 1; }
  seeds="$HERE/seeds/$task.txt"
  prompt="$(task_prompt "$task")"
  for arm in $ARMS; do
    for n in $(seq 1 "$RUNS"); do
      work="$RESULTS/$task/$arm/run$n"
      if [ -f "$work/done" ]; then echo ">>> skip $task/$arm/run$n (done)"; continue; fi
      rm -rf "$work" && mkdir -p "$work"
      write_config "$work/config" "$arm"
      export MNEMO_DB="$work/memory.db"
      # on-sim: no usefulness model, so `mnemo context` falls back to similarity.
      model_file="${MNEMO_USEFULNESS_MODEL:-$HOME/.local/share/mnemo/usefulness-model.json}"
      [ "$arm" = on-sim ] && model_file="$work/no-usefulness-model.json"
      export MNEMO_USEFULNESS_MODEL="$model_file"

      if [ "$arm" != off ]; then
        [ -f "$seeds" ] || { echo "no seed file for $task: $seeds" >&2; exit 1; }
        grep -v '^\s*#' "$seeds" | grep -v '^\s*$' | while IFS= read -r memory; do
          "$MNEMO_BIN" add -- "$memory" >/dev/null
        done
        # What the plugin would inject for the task prompt. A preview, not a
        # guarantee: the plugin retrieves with the live user message.
        "$MNEMO_BIN" context -- "$prompt" > "$work/injection-preview.txt" || true
      fi

      echo ">>> $task / $arm / run $n"
      (
        cd "$OPENCODE_BENCH_DIR"
        env XDG_CONFIG_HOME="$work/config" XDG_DATA_HOME="$work/data" \
          XDG_STATE_HOME="$work/state" XDG_CACHE_HOME="$RESULTS/.cache" \
          MNEMO_DB="$MNEMO_DB" MNEMO_BIN="$MNEMO_BIN" MNEMO_USEFULNESS_MODEL="$MNEMO_USEFULNESS_MODEL" \
          bun run dev -- opencode --model "$MODEL" --task "$task"
      ) > "$work/bench.log" 2>&1 || echo "    opencode-bench exited non-zero (see $work/bench.log)"

      grep -h -E 'Mnemosyne plugin initialized|Injected [0-9]+ memories|No relevant memories|injection failed' \
        "$work"/data/opencode/log/*.log > "$work/plugin.log" 2>/dev/null || true
      if [ "$arm" != off ] && ! grep -q 'Mnemosyne plugin initialized' "$work/plugin.log"; then
        echo "    WARNING: plugin did not initialize in this run; it will be reported as invalid" >&2
      fi
      grep -E 'Final score:' "$work/bench.log" | tail -1 | sed 's/^/    /' || true
      touch "$work/done"
    done
  done
done

echo ">>> summarize: python3 $HERE/summarize.py $RESULTS"
