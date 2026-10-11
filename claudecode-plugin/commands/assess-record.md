---
description: Record an observation or finding under an authorized assessment
argument-hint: <assessmentId> <observation or finding>
---
Record an observation under an existing authorized assessment by running the
mnemo CLI (`${MNEMO_BIN:-python3 -m mnemo.cli} assess record <assessmentId>
"<content>" --kind <kind> --severity <severity>`) with the Bash tool. Parse the
assessment id and content from the input below; default `--kind observation` and
`--severity info` unless the user specifies otherwise. If the assessment id or
content is missing, ask for it before running.

Input:

$ARGUMENTS
