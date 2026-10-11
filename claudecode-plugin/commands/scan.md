---
description: Scan source code for security vulnerabilities (bandit, semgrep, trivy)
argument-hint: [project path, default .]
---
Run the Mnemosyne source-code security scanners by invoking the mnemo CLI
(`${MNEMO_BIN:-python3 -m mnemo.cli} scan --path "<path>"`) with the Bash tool,
using the path below when given and `.` otherwise, then summarize the findings.

Project path:

$ARGUMENTS
