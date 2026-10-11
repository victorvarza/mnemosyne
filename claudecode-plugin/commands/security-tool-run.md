---
description: Run a registered security tool locally or in a Docker/Kali image
argument-hint: <toolName> [-- tool args]
---
Run a registered Mnemo security tool by invoking the mnemo CLI
(`${MNEMO_BIN:-python3 -m mnemo.cli} tools run <toolName> --mode <mode>
[--authorized "<authorization>"] -- <tool args>`) with the Bash tool. Parse the
tool name and any tool arguments (after `--`) from the input below. Active tools
require an explicit `--authorized` declaration; if one is needed and not
provided, ask for it before running.

Input:

$ARGUMENTS
