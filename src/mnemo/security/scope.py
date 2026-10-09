from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from urllib.parse import urlparse


class ScopeViolation(ValueError):
    """Raised when a requested target is outside an authorized assessment scope."""


def _normalize_host(host: str) -> str:
    return host.strip().lower().rstrip(".")


def _hostname_from_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ScopeViolation(f"Only http(s) targets are supported: {url}")
    if not parsed.hostname:
        raise ScopeViolation(f"URL does not contain a hostname: {url}")
    return _normalize_host(parsed.hostname)


def _is_private_or_local(host: str) -> bool:
    if host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


@dataclass(frozen=True)
class ScopePolicy:
    """Authorization and target-boundary checks for active security testing."""

    allowed_hosts: set[str]
    authorization: str
    allow_subdomains: bool = False
    allow_private_ips: bool = False
    max_requests: int = 100
    _normalized_hosts: set[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        normalized = {_normalize_host(host) for host in self.allowed_hosts if host.strip()}
        object.__setattr__(self, "_normalized_hosts", normalized)
        if not normalized:
            raise ScopeViolation("At least one allowed host is required")
        if not self.authorization.strip():
            raise ScopeViolation("Explicit authorization text is required")
        if self.max_requests < 1:
            raise ScopeViolation("max_requests must be at least 1")
        if not self.allow_private_ips:
            for host in normalized:
                if _is_private_or_local(host):
                    raise ScopeViolation(
                        f"Private/local target '{host}' requires allow_private_ips=True"
                    )

    @classmethod
    def from_target_url(
        cls,
        target_url: str,
        authorization: str,
        *,
        allow_subdomains: bool = False,
        allow_private_ips: bool = False,
        max_requests: int = 100,
    ) -> ScopePolicy:
        return cls(
            allowed_hosts={_hostname_from_url(target_url)},
            authorization=authorization,
            allow_subdomains=allow_subdomains,
            allow_private_ips=allow_private_ips,
            max_requests=max_requests,
        )

    def assert_allowed_url(self, url: str) -> None:
        host = _hostname_from_url(url)
        if not self.allow_private_ips and _is_private_or_local(host):
            raise ScopeViolation(f"Private/local URL is outside scope: {url}")
        if host in self._normalized_hosts:
            return
        if self.allow_subdomains and any(
            host.endswith(f".{allowed}") for allowed in self._normalized_hosts
        ):
            return
        allowed = ", ".join(sorted(self._normalized_hosts))
        raise ScopeViolation(f"URL host '{host}' is outside authorized scope: {allowed}")
