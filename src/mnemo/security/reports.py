from __future__ import annotations

import json
from pathlib import Path

from mnemo.security.findings import AssessmentReport, Finding


def write_json_report(report: AssessmentReport, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return output


def finding_to_markdown(finding: Finding, index: int) -> str:
    lines = [
        f"### {index}. {finding.title}",
        "",
        f"- **Severity:** {finding.severity.value}",
        f"- **Category:** {finding.category}",
        f"- **Target:** {finding.target or 'n/a'}",
        f"- **Verified:** {'yes' if finding.verified else 'no'}",
    ]
    if finding.cwe:
        lines.append(f"- **CWE:** {finding.cwe}")
    if finding.cve:
        lines.append(f"- **CVE:** {finding.cve}")
    if finding.cvss is not None:
        lines.append(f"- **CVSS:** {finding.cvss:.1f}")
    if finding.description:
        lines.extend(["", finding.description])
    if finding.evidence:
        lines.extend(["", "**Evidence**"])
        for evidence in finding.evidence:
            lines.append(f"- `{evidence.tool}`: {evidence.summary}")
            if evidence.request_url:
                lines.append(f"  - Request: {evidence.request_method} {evidence.request_url}")
            if evidence.response_status is not None:
                lines.append(f"  - Response status: {evidence.response_status}")
            excerpt = evidence.output_excerpt or evidence.response_excerpt
            if excerpt:
                lines.append(f"  - Excerpt: `{excerpt[:240]}`")
    if finding.remediation:
        lines.extend(["", "**Remediation**", finding.remediation])
    return "\n".join(lines)


def format_markdown_report(report: AssessmentReport) -> str:
    counts = report.severity_counts()
    lines = [
        f"# Security Assessment Report: {report.assessment_id}",
        "",
        f"- **Target:** {report.target}",
        f"- **Generated:** {report.generated_at.isoformat()}",
        f"- **Findings:** {report.finding_count}",
        "- **Severity counts:** " + ", ".join(f"{k}={v}" for k, v in counts.items()),
        "",
        "## Summary",
        "",
        report.summary,
        "",
        "## Findings",
        "",
    ]
    if not report.findings:
        lines.append("No findings were recorded.")
    else:
        for index, finding in enumerate(report.findings, start=1):
            lines.append(finding_to_markdown(finding, index))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_markdown_report(report: AssessmentReport, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(format_markdown_report(report), encoding="utf-8")
    return output
