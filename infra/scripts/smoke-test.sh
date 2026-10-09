#!/usr/bin/env bash
# Smoke-test a vLLM OpenAI-compatible endpoint: list models, plain chat, and a
# tool call (OpenCode depends on tool calling via the qwen3_coder parser).
# Usage: [VLLM_API_KEY=...] [PYTHON=python3] smoke-test.sh <base_url> <served_model_name>
set -euo pipefail

BASE_URL="${1:?base url required}"
MODEL="${2:?model name required}"
PYTHON="${PYTHON:-python3}"

headers=(-H "Content-Type: application/json")
[ -n "${VLLM_API_KEY:-}" ] && headers+=(-H "Authorization: Bearer ${VLLM_API_KEY}")

post() { curl -sS --fail-with-body -m 300 "${headers[@]}" "$BASE_URL$1" -d "$2"; }

echo ">>> GET /v1/models"
curl -sS --fail-with-body -m 30 "${headers[@]}" "$BASE_URL/v1/models" \
  | "$PYTHON" -c 'import json,sys; print("    served:", [m["id"] for m in json.load(sys.stdin)["data"]])'

echo ">>> Chat completion"
post /v1/chat/completions "$(cat <<EOF
{"model": "$MODEL",
 "messages": [{"role": "user", "content": "Write a Python one-liner that reverses a string s. Reply with code only."}],
 "max_tokens": 64, "temperature": 0.2}
EOF
)" | "$PYTHON" -c '
import json, sys
r = json.load(sys.stdin)
print("    reply:", r["choices"][0]["message"]["content"].strip()[:200])
print("    usage:", r["usage"])'

echo ">>> Tool call"
post /v1/chat/completions "$(cat <<EOF
{"model": "$MODEL",
 "messages": [{"role": "user", "content": "Read the file src/main.py"}],
 "tools": [{"type": "function", "function": {
    "name": "read_file", "description": "Read a file from the workspace",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}],
 "tool_choice": "auto", "max_tokens": 128, "temperature": 0.2}
EOF
)" | "$PYTHON" -c '
import json, sys
calls = json.load(sys.stdin)["choices"][0]["message"].get("tool_calls") or []
if not calls:
    sys.exit("    FAIL: no tool_calls returned (check --enable-auto-tool-choice / --tool-call-parser qwen3_coder)")
for c in calls:
    print("    tool_call:", c["function"]["name"], c["function"]["arguments"])'

echo ">>> Smoke test passed"
