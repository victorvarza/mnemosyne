---
description: Search Mnemosyne memories by semantic similarity
argument-hint: <query>
---
Search Mnemosyne for memories relevant to the query below by running the mnemo
CLI (`${MNEMO_BIN:-python3 -m mnemo.cli} search --top-k 5 -- "<query>"`) with the
Bash tool, then summarize the matches. If no query is provided, ask what to
recall.

Query:

$ARGUMENTS
