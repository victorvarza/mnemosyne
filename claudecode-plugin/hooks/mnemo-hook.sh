#!/usr/bin/env sh
# Mnemosyne UserPromptSubmit hook for Claude Code.
#
# Reads the hook payload from stdin and asks the mnemo CLI to store any
# pattern-matched important information and emit the relevant memories as
# additionalContext. Set MNEMO_BIN to a mnemo executable (for example
# <repo>/.venv/bin/mnemo) when `python3 -m mnemo.cli` cannot import mnemo from
# the session's environment; otherwise the hook is a silent no-op.
if [ -n "${MNEMO_BIN:-}" ]; then
  exec "$MNEMO_BIN" claudecode-hook
fi
exec python3 -m mnemo.cli claudecode-hook
