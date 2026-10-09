# Mnemo Authorized Security Assessment

Use this skill when the user asks to scan source code, create an authorized
assessment, record findings, or run Mnemo's active pentest workflow.

## Safety rule

Active testing must only run against targets the user owns or is explicitly
authorized to assess. Require an assessment context before active pentesting.

## Assessment workflow

Create an authorization record:

```bash
mnemo assess create web-lab \
  --target https://app.example.com \
  --authorized "Approved under ticket SEC-123"
```

Record observations or findings:

```bash
mnemo assess record web-lab \
  "Observed missing rate limit on login" \
  --kind finding \
  --severity medium \
  --evidence reports/login-rate-limit.md \
  --verification verified
```

List records:

```bash
mnemo assess list web-lab
```

Run local source scanning:

```bash
mnemo scan --path .
mnemo assess source-scan web-lab --path .
```

Run active pentest with scope enforcement:

```bash
mnemo pentest \
  --assessment web-lab \
  --target https://app.example.com \
  --source ./app \
  --max-requests 100 \
  --report-dir ./reports
```

Use `--allow-private-ips` only for controlled lab targets such as localhost or
RFC1918 addresses.

## OpenCode plugin tools

When the plugin is loaded, prefer these tools if available:

- `assessCreate`
- `assessRecord`
- `scan`
- `pentest`

## Expected outputs

`mnemo pentest` writes:

- `<assessment-id>-pentest.json`
- `<assessment-id>-pentest.md`
- `<assessment-id>-pentest-legacy.json`

Summarize the report path and high-level counts for the user; do not overstate
unverified issues as confirmed vulnerabilities.
