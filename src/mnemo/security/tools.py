from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ToolMode(str, Enum):
    LOCAL = "local"
    DOCKER = "docker"


@dataclass(frozen=True)
class SecurityTool:
    name: str
    category: str
    package_hint: str = ""
    passive: bool = False
    requires_authorization: bool = True
    description: str = ""


@dataclass(frozen=True)
class ToolExecution:
    tool: str
    mode: ToolMode
    command: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    available: bool = True

    @property
    def succeeded(self) -> bool:
        return self.available and not self.timed_out and self.returncode == 0


def _tool(
    name: str,
    category: str,
    *,
    package_hint: str = "",
    passive: bool = False,
    requires_authorization: bool = True,
    description: str = "",
) -> SecurityTool:
    return SecurityTool(
        name=name,
        category=category,
        package_hint=package_hint or name,
        passive=passive,
        requires_authorization=requires_authorization,
        description=description,
    )


# Broad Kali / bug-bounty / web-app security catalog. Tools may be executed locally
# when installed, or through a caller-provided Docker image such as a custom Kali
# image, shannon-tools, or another security-toolbox image that contains them.
DEFAULT_TOOL_REGISTRY: dict[str, SecurityTool] = {
    item.name: item
    for item in [
        _tool("nmap", "network-recon", description="Port and service discovery"),
        _tool("masscan", "network-recon"),
        _tool("rustscan", "network-recon"),
        _tool("naabu", "network-recon"),
        _tool("amass", "dns-recon"),
        _tool("subfinder", "dns-recon"),
        _tool("assetfinder", "dns-recon"),
        _tool("dnsx", "dns-recon"),
        _tool("dnsrecon", "dns-recon"),
        _tool("dnsenum", "dns-recon"),
        _tool("whois", "osint", passive=True, requires_authorization=False),
        _tool("whatweb", "web-fingerprint"),
        _tool("wafw00f", "web-fingerprint"),
        _tool("httpx", "web-recon"),
        _tool("httprobe", "web-recon"),
        _tool("gowitness", "web-recon"),
        _tool("aquatone", "web-recon"),
        _tool("nikto", "web-scan"),
        _tool("nuclei", "web-scan"),
        _tool("jaeles", "web-scan"),
        _tool("wapiti", "web-scan"),
        _tool("arachni", "web-scan"),
        _tool("zap-baseline.py", "web-scan", package_hint="zaproxy"),
        _tool("sqlmap", "injection"),
        _tool("nosqlmap", "injection"),
        _tool("commix", "injection"),
        _tool("dalfox", "xss"),
        _tool("xsser", "xss"),
        _tool("kxss", "xss"),
        _tool("ffuf", "content-discovery"),
        _tool("gobuster", "content-discovery"),
        _tool("dirsearch", "content-discovery"),
        _tool("feroxbuster", "content-discovery"),
        _tool("dirb", "content-discovery"),
        _tool("wfuzz", "content-discovery"),
        _tool("arjun", "parameter-discovery"),
        _tool("paramspider", "parameter-discovery"),
        _tool("waybackurls", "url-discovery", passive=True),
        _tool("gau", "url-discovery", passive=True),
        _tool("hakrawler", "crawler"),
        _tool("katana", "crawler"),
        _tool("gospider", "crawler"),
        _tool("cewl", "password"),
        _tool("hydra", "password"),
        _tool("medusa", "password"),
        _tool("ncrack", "password"),
        _tool("john", "password"),
        _tool("hashcat", "password"),
        _tool("hashid", "password"),
        _tool("hash-identifier", "password"),
        _tool("metasploit", "exploitation", package_hint="metasploit-framework"),
        _tool("msfconsole", "exploitation", package_hint="metasploit-framework"),
        _tool("searchsploit", "exploitation", package_hint="exploitdb", passive=True),
        _tool("exploitdb", "exploitation", passive=True),
        _tool("yersinia", "network-attack"),
        _tool("bettercap", "network-attack"),
        _tool("ettercap", "network-attack"),
        _tool("responder", "network-attack"),
        _tool("impacket-smbclient", "windows-ad", package_hint="impacket-scripts"),
        _tool("impacket-psexec", "windows-ad", package_hint="impacket-scripts"),
        _tool("crackmapexec", "windows-ad"),
        _tool("netexec", "windows-ad"),
        _tool("bloodhound-python", "windows-ad"),
        _tool("enum4linux", "smb"),
        _tool("smbmap", "smb"),
        _tool("smbclient", "smb"),
        _tool("ldapsearch", "ldap"),
        _tool("sslscan", "tls"),
        _tool("sslyze", "tls"),
        _tool("testssl.sh", "tls"),
        _tool("trivy", "supply-chain", passive=True, requires_authorization=False),
        _tool("grype", "supply-chain", passive=True, requires_authorization=False),
        _tool("syft", "supply-chain", passive=True, requires_authorization=False),
        _tool("semgrep", "static-analysis", passive=True, requires_authorization=False),
        _tool("bandit", "static-analysis", passive=True, requires_authorization=False),
        _tool("gitleaks", "secret-scan", passive=True, requires_authorization=False),
        _tool("trufflehog", "secret-scan", passive=True, requires_authorization=False),
        _tool("detect-secrets", "secret-scan", passive=True, requires_authorization=False),
        _tool("retire", "dependency-scan", passive=True, requires_authorization=False),
        _tool("snyk", "dependency-scan", passive=True, requires_authorization=False),
        _tool("kube-hunter", "cloud-container"),
        _tool("kube-bench", "cloud-container", passive=True, requires_authorization=False),
        _tool("kubesec", "cloud-container", passive=True, requires_authorization=False),
        _tool("checkov", "iac", passive=True, requires_authorization=False),
        _tool("tfsec", "iac", passive=True, requires_authorization=False),
        _tool("prowler", "cloud"),
        _tool("scout", "cloud"),
        _tool("cloudsplaining", "cloud", passive=True, requires_authorization=False),
        _tool("corsy", "cors"),
        _tool("jwt_tool", "api-auth"),
        _tool("graphql-cop", "api"),
        _tool("inql", "api"),
        _tool("postman", "api", passive=True, requires_authorization=False),
        _tool("playwright", "browser"),
        _tool("chromium", "browser"),
        _tool("curl", "utility"),
        _tool("wget", "utility"),
        _tool("jq", "utility", passive=True, requires_authorization=False),
    ]
}


def list_tools(category: str | None = None) -> list[SecurityTool]:
    tools = sorted(DEFAULT_TOOL_REGISTRY.values(), key=lambda tool: (tool.category, tool.name))
    if category is None:
        return tools
    return [tool for tool in tools if tool.category == category]


def get_tool(name: str) -> SecurityTool:
    try:
        return DEFAULT_TOOL_REGISTRY[name]
    except KeyError as exc:
        known = ", ".join(sorted(DEFAULT_TOOL_REGISTRY)[:12])
        raise ValueError(f"Unknown tool '{name}'. Known examples: {known}, ...") from exc


@dataclass
class ToolRunner:
    mode: ToolMode = ToolMode.DOCKER
    docker_image: str = "shannon-tools"
    workdir: Path | None = None
    timeout_seconds: int = 300
    require_authorization: bool = True
    authorization: str = ""

    def _assert_runnable(self, tool: SecurityTool) -> None:
        if self.require_authorization and tool.requires_authorization and not self.authorization.strip():
            raise PermissionError(f"Tool '{tool.name}' requires explicit authorization")

    def _local_command(self, tool: SecurityTool, args: Iterable[str]) -> list[str]:
        executable = shutil.which(tool.name)
        if executable is None:
            raise FileNotFoundError(f"Tool not installed locally: {tool.name}")
        return [executable, *args]

    def _docker_command(self, tool: SecurityTool, args: Iterable[str]) -> list[str]:
        command = ["docker", "run", "--rm", "--network", "host"]
        if self.workdir is not None:
            host_dir = self.workdir.expanduser().resolve()
            command.extend(["-v", f"{host_dir}:/workspace", "-w", "/workspace"])
        command.extend([self.docker_image, tool.name, *args])
        return command

    def build_command(self, tool_name: str, args: Iterable[str]) -> list[str]:
        tool = get_tool(tool_name)
        self._assert_runnable(tool)
        if self.mode == ToolMode.LOCAL:
            return self._local_command(tool, args)
        return self._docker_command(tool, args)

    def run(self, tool_name: str, args: Iterable[str]) -> ToolExecution:
        tool = get_tool(tool_name)
        self._assert_runnable(tool)
        try:
            command = self.build_command(tool.name, list(args))
        except FileNotFoundError as exc:
            return ToolExecution(
                tool=tool.name,
                mode=self.mode,
                command=[tool.name, *list(args)],
                returncode=127,
                stderr=str(exc),
                available=False,
            )
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                check=False,
                text=True,
                timeout=self.timeout_seconds,
            )
            return ToolExecution(
                tool=tool.name,
                mode=self.mode,
                command=command,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        except FileNotFoundError as exc:
            return ToolExecution(
                tool=tool.name,
                mode=self.mode,
                command=command,
                returncode=127,
                stderr=str(exc),
                available=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ToolExecution(
                tool=tool.name,
                mode=self.mode,
                command=command,
                returncode=124,
                stdout=exc.stdout or "",
                stderr=exc.stderr or f"Timed out after {self.timeout_seconds}s",
                timed_out=True,
            )
