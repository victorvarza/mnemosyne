#!/usr/bin/env bash
# Reproduce the live-session evidence: OpenCode V1 headless, local Ollama, the
# Mnemosyne plugin on (two turns) and off (control). Everything runs in an
# isolated temp directory, so your own OpenCode config and data are untouched.
#
# Requires: Ollama with qwen2.5:7b + nomic-embed-text, Node (npx), `uv sync`.
# Usage: bench/live-session/run.sh [output-dir]
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
LIVE="$(mktemp -d "${TMPDIR:-/tmp}/mnemo-live.XXXXXX")"
OUT="${1:-$REPO/bench/live-session/logs}"
OPENCODE="npx -y opencode-ai@1.18.34"
MODEL="qwen2.5:7b-16k"

# OpenCode's system prompt is larger than Ollama's default context window,
# which would truncate it (and the injected memories). This tag shares the
# qwen2.5:7b weights; remove it with `ollama rm qwen2.5:7b-16k`.
printf 'FROM qwen2.5:7b\nPARAMETER num_ctx 16384\n' > "$LIVE/Modelfile"
ollama create "$MODEL" -f "$LIVE/Modelfile" >/dev/null

write_config() { # $1 = config dir, $2 = "on" to load the plugin
  mkdir -p "$1/opencode"
  local plugin=""
  [ "$2" = on ] && plugin=", \"plugin\": [\"file://$REPO/opencode-plugin.js\"]"
  cat > "$1/opencode/opencode.json" <<EOF
{
  "\$schema": "https://opencode.ai/config.json",
  "model": "ollama/$MODEL",
  "autoupdate": false,
  "share": "disabled",
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama (local)",
      "options": { "baseURL": "http://localhost:11434/v1" },
      "models": { "$MODEL": { "name": "qwen2.5 7b (16k ctx)", "tool_call": true } }
    }
  }$plugin
}
EOF
}
write_config "$LIVE/config-on" on
write_config "$LIVE/config-off" off
mkdir -p "$LIVE/project" "$OUT" && git -C "$LIVE/project" init -q

export MNEMO_DB="$LIVE/memory.db" MNEMO_BIN="$REPO/.venv/bin/mnemo"
"$MNEMO_BIN" add "Our production database is PostgreSQL 16 running on AWS RDS in eu-west-1."
"$MNEMO_BIN" add "I prefer pytest for tests and ruff for linting."

oc() { # $1 = config dir, $2 = log name, rest = opencode run args
  local cfg="$1" log="$2"; shift 2
  (cd "$LIVE/project" && env XDG_CONFIG_HOME="$cfg" XDG_DATA_HOME="$LIVE/data" \
    XDG_CACHE_HOME="$LIVE/cache" XDG_STATE_HOME="$LIVE/state" \
    $OPENCODE run --print-logs --log-level DEBUG "$@" 2>&1) \
    | grep -v "duplicate skill" | sed -e "s#$LIVE#\$LIVE#g" -e "s#$HOME#~#g" > "$OUT/$log.log"
}
Q1="Which database do we run in production, and in which AWS region? Answer in one sentence, without using tools."
Q2="Which tools do I prefer for testing and linting? Answer in one sentence, without using tools."
oc "$LIVE/config-on" turn1 "$Q1"
oc "$LIVE/config-on" turn2 --continue "$Q2"
oc "$LIVE/config-off" control "$Q1"

for log in turn1 turn2 control; do
  echo "=== $log"
  grep -v '^timestamp' "$OUT/$log.log" | grep -v '^\s*$' || true
  grep -E 'Mnemosyne plugin initialized|Injected|No relevant|injection failed' "$OUT/$log.log" \
    | sed -E 's/^timestamp=([^ ]+) level=([A-Z]+) run=[a-f0-9]+ /  \1 \2 /' || echo "  (no plugin log lines)"
done
