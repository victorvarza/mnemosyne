from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class ScanFindings:
    tool: str
    available: bool
    findings: list[dict] = field(default_factory=list)
    error: str = ""
    failed: bool = False

    @property
    def count(self) -> int:
        return len(self.findings)


@dataclass(frozen=True)
class _ToolRun:
    available: bool
    succeeded: bool
    stdout: str = ""
    error: str = ""


@dataclass
class SecurityReport:
    bandit: ScanFindings = field(default_factory=lambda: ScanFindings(tool="bandit", available=False))
    semgrep: ScanFindings = field(default_factory=lambda: ScanFindings(tool="semgrep", available=False))
    trivy: ScanFindings = field(default_factory=lambda: ScanFindings(tool="trivy", available=False))
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


def _run_tool(cmd: list[str], valid_exit_codes: frozenset[int] = frozenset({0})) -> _ToolRun:
    try:
        result = subprocess.run(cmd, capture_output=True, check=False, text=True, timeout=120)
        if result.returncode in valid_exit_codes:
            return _ToolRun(available=True, succeeded=True, stdout=result.stdout)
        detail = result.stderr.strip()
        error = f"Exited with status {result.returncode}"
        if detail:
            error = f"{error}: {detail}"
        return _ToolRun(available=True, succeeded=False, stdout=result.stdout, error=error)
    except FileNotFoundError:
        return _ToolRun(available=False, succeeded=False, error="Tool not installed")
    except subprocess.TimeoutExpired:
        return _ToolRun(available=True, succeeded=False, error="Timed out after 120s")
    except OSError as exc:
        return _ToolRun(available=True, succeeded=False, error=f"Could not start scanner: {exc}")


def _project_path(project_path: str) -> tuple[Path | None, str]:
    path = Path(project_path).expanduser()
    if not path.is_dir():
        return None, f"Project path is not a directory: {path}"
    return path, ""


def _source_path(project_path: str) -> tuple[Path | None, str]:
    path, error = _project_path(project_path)
    if path is None:
        return None, error
    source = path / "src"
    if not source.is_dir():
        return None, f"Source path is not a directory: {source}"
    return source, ""


def _failed_scan(
    tool: str, error: str, *, available: bool = True, failed: bool = True
) -> ScanFindings:
    return ScanFindings(tool=tool, available=available, error=error, failed=failed)


def _parse_json(tool: str, stdout: str) -> tuple[dict | None, str]:
    if not stdout.strip():
        return None, f"{tool} produced no JSON output"
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return None, f"{tool} produced invalid JSON: {exc.msg}"
    if not isinstance(data, dict):
        return None, f"{tool} produced JSON that is not an object"
    return data, ""


def run_bandit(project_path: str) -> ScanFindings:
    source, error = _source_path(project_path)
    if source is None:
        return _failed_scan("bandit", error)
    run = _run_tool(
        ["bandit", "-r", str(source), "-f", "json", "-q"], valid_exit_codes=frozenset({0, 1})
    )
    if not run.succeeded:
        return _failed_scan(
            "bandit", run.error, available=run.available, failed=run.available
        )
    data, error = _parse_json("bandit", run.stdout)
    if data is None:
        return _failed_scan("bandit", error)
    findings = data.get("results")
    if not isinstance(findings, list):
        return _failed_scan("bandit", "bandit JSON did not contain a results list")
    return ScanFindings(tool="bandit", available=True, findings=findings)


def run_semgrep(project_path: str) -> ScanFindings:
    source, error = _source_path(project_path)
    if source is None:
        return _failed_scan("semgrep", error)
    run = _run_tool(
        ["semgrep", "scan", "--config", "auto", str(source), "--json", "--quiet"]
    )
    if not run.succeeded:
        return _failed_scan(
            "semgrep", run.error, available=run.available, failed=run.available
        )
    data, error = _parse_json("semgrep", run.stdout)
    if data is None:
        return _failed_scan("semgrep", error)
    findings = data.get("results")
    if not isinstance(findings, list):
        return _failed_scan("semgrep", "semgrep JSON did not contain a results list")
    return ScanFindings(tool="semgrep", available=True, findings=findings)


def run_trivy(project_path: str) -> ScanFindings:
    path, error = _project_path(project_path)
    if path is None:
        return _failed_scan("trivy", error)
    run = _run_tool(["trivy", "fs", str(path), "--format", "json", "--quiet"])
    if not run.succeeded:
        return _failed_scan(
            "trivy", run.error, available=run.available, failed=run.available
        )
    data, error = _parse_json("trivy", run.stdout)
    if data is None:
        return _failed_scan("trivy", error)
    results = data.get("Results")
    if not isinstance(results, list):
        return _failed_scan("trivy", "trivy JSON did not contain a Results list")
    findings = []
    for result in results:
        if not isinstance(result, dict):
            return _failed_scan("trivy", "trivy Results contained a non-object entry")
        vulnerabilities = result.get("Vulnerabilities", [])
        if not isinstance(vulnerabilities, list):
            return _failed_scan("trivy", "trivy Results contained a non-list Vulnerabilities field")
        findings.extend(vulnerabilities)
    return ScanFindings(tool="trivy", available=True, findings=findings)


def full_scan(project_path: str) -> SecurityReport:
    return SecurityReport(
        bandit=run_bandit(project_path),
        semgrep=run_semgrep(project_path),
        trivy=run_trivy(project_path),
    )
