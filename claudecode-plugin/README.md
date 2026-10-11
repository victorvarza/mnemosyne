# Mnemosyne Claude Code Plugin

> ⚠️ **Educational Purpose Only**: This plugin is designed for educational and
> research purposes only. Any security testing capabilities should only be used
> in controlled environments with explicit authorization.

The Claude Code counterpart to the [OpenCode plugin](../docs/plugin.md). It
gives [Claude Code](https://claude.com/claude-code) the same Mnemosyne
capabilities: automatic memory capture and retrieval, plus manual memory and
authorized security-assessment commands. All memory operations run locally
through the `mnemo` CLI.

## Layout

```text
claudecode-plugin/
  .claude-plugin/plugin.json   # plugin manifest
  hooks/hooks.json             # UserPromptSubmit hook wiring
  hooks/mnemo-hook.sh          # hook entrypoint (calls `mnemo claudecode-hook`)
  commands/*.md                # /mnemosyne:* slash commands
```

## What it does

- **Automatic memory** — a `UserPromptSubmit` hook runs `mnemo claudecode-hook`,
  which stores pattern-matched important info (e.g. "user prefers …", "remember
  … for later") and injects the memories relevant to the prompt as additional
  context. This mirrors the OpenCode plugin's prompt/context hooks and shares
  its retrieval and usefulness filtering (via `mnemo context`).
- **Slash commands** — manual tools namespaced under `/mnemosyne:`:

  | Command | Purpose |
  |---|---|
  | `/mnemosyne:remember` | Store a fact in memory |
  | `/mnemosyne:recall` | Search memories by semantic similarity |
  | `/mnemosyne:scan` | Scan source code (bandit, semgrep, trivy) |
  | `/mnemosyne:assess-create` | Create an authorized assessment context |
  | `/mnemosyne:assess-record` | Record an observation/finding |
  | `/mnemosyne:pentest` | Authorized pentest of source + deployed target |
  | `/mnemosyne:security-tools-list` | List registered security tools |
  | `/mnemosyne:security-tool-run` | Run a tool locally or in Docker/Kali |

## Installation

The plugin shells out to the `mnemo` CLI, so install the client first (see the
repository [README](../README.md)): `make client-setup`.

Then make the plugin available to Claude Code. From this repository's root you
can add it as a local marketplace/plugin, or copy `claudecode-plugin/` into your
own project and load it. A minimal `settings.json` reference:

```jsonc
{
  "plugins": ["/absolute/path/to/mnemosyne/claudecode-plugin"]
}
```

### Environment

The hook invokes `python3 -m mnemo.cli` by default. Set `MNEMO_BIN` to a `mnemo`
executable (for example `<repo>/.venv/bin/mnemo`) when `mnemo` is not importable
by the system `python3`; otherwise the hook is a silent no-op. The same
`MNEMO_DB`, `MNEMO_OLLAMA_URL`, and related variables used by the CLI apply. See
[docs/plugin.md](../docs/plugin.md) for the full table.

The hook is best-effort: if the `mnemo` CLI or the Ollama worker is unavailable,
it exits cleanly without blocking the prompt.
