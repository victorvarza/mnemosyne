from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Evidence:
    """Concrete evidence attached to a security finding."""

    tool: str
    summary: str
    target: str = ""
    command: list[str] = field(default_factory=list)
    request_method: str = ""
    request_url: str = ""
    response_status: int | None = None
    response_excerpt: str = ""
    output_excerpt: str = ""
    artifact_path: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class Finding:
    """Normalized finding model for scanner, tool, and pentest results."""

    title: str
    category: str
    severity: Severity = Severity.INFO
    target: str = ""
    description: str = ""
    remediation: str = ""
    verified: bool = False
    cwe: str = ""
    cve: str = ""
    cvss: float | None = None
    evidence: list[Evidence] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["severity"] = self.severity.value
        data["evidence"] = [item.to_dict() for item in self.evidence]
        return data


@dataclass
class AssessmentReport:
    """Serializable report envelope used by active and passive security workflows."""

    assessment_id: str
    target: str
    summary: str
    findings: list[Finding] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    def severity_counts(self) -> dict[str, int]:
        counts = {severity.value: 0 for severity in Severity}
        for finding in self.findings:
            counts[finding.severity.value] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "target": self.target,
            "summary": self.summary,
            "generated_at": self.generated_at.isoformat(),
            "finding_count": self.finding_count,
            "severity_counts": self.severity_counts(),
            "metadata": self.metadata,
            "findings": [finding.to_dict() for finding in self.findings],
        }
