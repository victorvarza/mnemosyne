# Mnemosyne -- Security Assessment Notes

Mnemosyne is for authorized assessment of persistent-memory behavior and security
testing of deployed applications. A memory store can preserve misleading or 
instruction-like content and later return it to an LLM, so callers should treat 
memory content as untrusted context unless they have applied their own review 
and controls.

## Current controls and limitations

The prototype includes:

- trust labels (`user_stated`, `agent_inferred`, `external_document`, and
  `unknown`);
- regex-based sanitization and optional LLM classification helpers;
- post-storage heuristic detection helpers;
- local source-code scanner orchestration;
- a local red-team assessment harness; and
- a pentest module for analyzing source code and attacking deployed targets.

These are incomplete assessment mechanisms, not a guarantee that malicious
content is prevented. In particular, `mnemo add` writes explicit CLI input
directly to the local store and does not currently call the sanitization
helpers. The current project has no authorization scopes/RBAC, automatic
memory lifecycle enforcement, token-budget controls, or network access controls 
for a worker.

## Assessment-memory boundary

`mnemo assess` records user-declared, authorized engagement context and concise
local assessment notes. Creating a context requires a target identifier and an
explicit authorization declaration; the declaration and timestamp are retained
as metadata on the context and its records. This is an audit aid, not RBAC or
validation of the declaration. Records are local memories, marked
`user_stated` with source `assessment_user_stated`; use `mnemo assess list` or
normal retrieval to find them.

The commands do not execute tools, scan targets, or offer exploitation
capabilities. A stored project preference is descriptive only—for example, a
user may state a preferred approved-validation tool—and never triggers
automation.

The `mnemo pentest` command is an exception that does perform active security
testing against deployed targets, using source code analysis to inform the
attack vectors. This command requires an existing authorized assessment context,
enforces the declared target host, applies a request budget, and writes both JSON
and Markdown reports:

```bash
mnemo assess create web-lab \
  --target https://app.example.com \
  --authorized "Approved under ticket SEC-123"

mnemo pentest \
  --assessment web-lab \
  --target https://app.example.com \
  --source ./app \
  --max-requests 100 \
  --report-dir ./reports
```

Use `--allow-private-ips` only for controlled lab targets such as localhost or
RFC1918 addresses.

## Docker/Kali tool runner

Mnemosyne also provides a registered security-tool runner inspired by the
OpenCode Shannon and opencode-pentester ecosystems. It does not vendor those
projects; it exposes a native registry of 60+ common Kali, bug-bounty, web,
cloud, static-analysis, and supply-chain tools that can be executed locally or
through a Docker image containing those tools.

List tools:

```bash
mnemo tools list
mnemo tools list --category web-scan
```

Run an active tool through Docker/Kali:

```bash
mnemo tools run nmap \
  --authorized "Approved under ticket SEC-123" \
  --docker-image shannon-tools \
  -- -sV app.example.com
```

Run a passive/local tool:

```bash
mnemo tools run bandit --mode local -- -r src
```

The default Docker image name is `shannon-tools`; set
`MNEMO_SECURITY_DOCKER_IMAGE` or pass `--docker-image` for another Kali/security
toolbox image. Passing `--workdir <path>` mounts that directory at `/workspace`
inside the container. Active tools require explicit authorization text via
`--authorized` or `MNEMO_SECURITY_AUTHORIZATION`.

## Deployment boundary

The local laptop owns `~/.local/share/mnemo/memory.db` for normal memory
commands. `mnemo redteam` instead defaults to the separate, disposable
`~/.local/share/mnemo/redteam-assessment.db`; remove it after reviewing the
assessment, or use `--db` to intentionally select another assessment store.
The worker only serves Ollama inference and model provisioning. Configure the
laptop with `MNEMO_OLLAMA_URL`; use a protected, authorized network path to the
worker. Because the worker can be reachable beyond localhost, deployment owners
are responsible for container, host, and network policy.

## Authorized use

Run `make client-redteam` and `make client-scan` only in environments, against
data, and on infrastructure you are explicitly authorized to assess. Results
from these utilities should be treated as development evidence, not as a
security certification.

The `mnemo pentest` command performs active security testing and should only
be used in authorized penetration testing engagements. Do not use this command
against systems you do not own or lack explicit permission to test.
