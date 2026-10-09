#!/usr/bin/env bash
# Generate an OpenCode config that registers the vLLM server as an
# OpenAI-compatible provider. The API key is read from $VLLM_API_KEY at
# OpenCode start-up, so no secret is written to disk.
# Usage: opencode-config.sh <out_file> <base_url> <model_id> <display_name> <context_limit> <output_limit>
set -euo pipefail

OUT="${1:?}"; BASE_URL="${2:?}"; MODEL_ID="${3:?}"; DISPLAY="${4:?}"; CONTEXT="${5:?}"; OUTPUT="${6:?}"

cat > "$OUT" <<EOF
{
  "\$schema": "https://opencode.ai/config.json",
  "provider": {
    "vllm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "vLLM (p4de)",
      "options": {
        "baseURL": "$BASE_URL",
        "apiKey": "{env:VLLM_API_KEY}"
      },
      "models": {
        "$MODEL_ID": {
          "name": "$DISPLAY",
          "tool_call": true,
          "limit": { "context": $CONTEXT, "output": $OUTPUT }
        }
      }
    }
  },
  "model": "vllm/$MODEL_ID",
  "small_model": "vllm/$MODEL_ID",
  "plugins": [
    "./opencode-plugin.js"
  ]
}
EOF
echo ">>> Wrote $OUT (provider vllm -> $BASE_URL, model vllm/$MODEL_ID)"
