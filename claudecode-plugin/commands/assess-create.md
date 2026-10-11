---
description: Create a local authorized security assessment context
argument-hint: <assessmentId> <target> <authorization text>
---
Create a local authorized-assessment context by running the mnemo CLI
(`${MNEMO_BIN:-python3 -m mnemo.cli} assess create <assessmentId> --target
<target> --authorized "<authorization text>"`) with the Bash tool. Parse the
assessment id, target, and explicit authorization declaration from the input
below; if any are missing, ask for them before running. Confirm creation.

Input:

$ARGUMENTS
