# Mnemo Docker/Kali Security Tools

Use this skill when the user wants to list or run Mnemo's registered Kali,
bug-bounty, web, cloud, source-analysis, or supply-chain tools.

## Tool model

Mnemo exposes a registry of 60+ tools through:

```bash
mnemo tools list
mnemo tools list --category web-scan
mnemo tools run <tool> [runner options] -- <tool args>
```

Tools can run locally or through Docker. The default Docker image is
`shannon-tools`; override it with `--docker-image` or
`MNEMO_SECURITY_DOCKER_IMAGE`.

## Common commands

List categories/tools:

```bash
mnemo tools list
mnemo tools list --category network-recon
mnemo tools list --category web-scan
```

Run an active tool through Docker:

```bash
mnemo tools run nmap \
  --authorized "Approved under ticket SEC-123" \
  --docker-image shannon-tools \
  -- -sV app.example.com
```

Run a passive local scanner:

```bash
mnemo tools run bandit --mode local -- -r src
mnemo tools run semgrep --mode local -- scan --config auto src --json
mnemo tools run trivy --mode local -- fs . --format json
```

Mount a working directory into Docker at `/workspace`:

```bash
mnemo tools run nuclei \
  --authorized "Approved under ticket SEC-123" \
  --workdir . \
  -- -u https://app.example.com
```

## OpenCode plugin tools

When the plugin is loaded, prefer these tools if available:

- `securityToolsList`
- `securityToolRun`

## Guardrails

- Active tools require explicit authorization text.
- Never run exploitation, password, network attack, or scanning tools against
  third-party systems without written permission.
- Prefer passive/local tools for source-code-only analysis.
- Use `mnemo assess create` and `mnemo assess record` to preserve the approved
  target and evidence trail.
