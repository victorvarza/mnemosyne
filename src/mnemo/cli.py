from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.table import Table

from mnemo.config import (
    DEFAULT_EMBED_MODEL,
    DEFAULT_LLM_MODEL,
    DEFAULT_OLLAMA_URL,
    MNEMO_EMBED_MODEL,
    MNEMO_LLM_MODEL,
    MNEMO_OLLAMA_URL,
)
from mnemo.core.embeddings import EmbeddingModel
from mnemo.core.llm import LLMClient
from mnemo.core.store import MemoryStore
from mnemo.core.types import Memory, MemoryQuery, MemoryType, TrustLevel
from mnemo.eval.usefulness import UsefulnessModel
from mnemo.lifecycle import run_lifecycle
from mnemo.ops.inject import format_memories_block
from mnemo.ops.retrieve import retrieve
from mnemo.security.pentest import Pentester
from mnemo.security.redteam import run_campaign
from mnemo.security.reports import write_json_report, write_markdown_report
from mnemo.security.sanitize import is_safe_to_store
from mnemo.security.scanner import full_scan
from mnemo.security.scope import ScopePolicy, ScopeViolation
from mnemo.security.tools import ToolMode, ToolRunner, list_tools

app = typer.Typer(name="mnemo", help="Mnemosyne — security-focused personalized context memory for AI assistants")
assess_app = typer.Typer(
    help="Record authorized-assessment context and concise local records; does not execute tools."
)
tools_app = typer.Typer(help="List and run registered security tools locally or in Docker/Kali.")
app.add_typer(assess_app, name="assess")
app.add_typer(tools_app, name="tools")
console = Console()

DEFAULT_DB = Path.home() / ".local" / "share" / "mnemo" / "memory.db"
DEFAULT_REDTEAM_DB = Path.home() / ".local" / "share" / "mnemo" / "redteam-assessment.db"
REDTEAM_DB_OPTION = typer.Option(DEFAULT_REDTEAM_DB, "--db")
ASSESSMENT_DB_OPTION = typer.Option(DEFAULT_DB, "--db")


def _get_store(db_path: Path, dimensions: int | None) -> MemoryStore:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return MemoryStore(db_path=db_path, dimensions=dimensions)


def _get_embedder(model: str, base_url: str) -> EmbeddingModel:
    embedder = EmbeddingModel(model=model, base_url=base_url)
    if not embedder.is_available():
        embedder.close()
        console.print(
            f"[red]Ollama not reachable at {base_url}. "
            "Start it with: ollama serve[/red]"
        )
        raise typer.Exit(1)
    return embedder


def _require_nonempty(value: str, option_name: str) -> str:
    value = value.strip()
    if not value:
        raise typer.BadParameter(f"{option_name} must not be empty")
    return value


def _assessment_context(store: MemoryStore, assessment_id: str) -> Memory | None:
    for memory in store.list_all():
        metadata = memory.metadata
        if (
            metadata.get("assessment_id") == assessment_id
            and metadata.get("record_kind") == "context"
        ):
            return memory
    return None


def _store_assessment_record(
    store: MemoryStore,
    embedder: EmbeddingModel,
    *,
    assessment_id: str,
    target_identifier: str,
    authorized_declaration: str,
    authorized_at: str,
    record_kind: str,
    content: str,
    severity: str,
    evidence_reference: str,
    verification_status: str,
    project: str = "",
    extra_metadata: dict[str, str | int] | None = None,
) -> Memory:
    metadata = {
        "assessment_id": assessment_id,
        "target_identifier": target_identifier,
        "authorized_declaration": authorized_declaration,
        "authorized_at": authorized_at,
        "record_kind": record_kind,
        "severity": severity,
        "evidence_reference": evidence_reference,
        "verification_status": verification_status,
    }
    if project:
        metadata["project"] = project
    if extra_metadata:
        metadata.update(extra_metadata)

    searchable_content = f"Assessment {assessment_id} | {record_kind}: {content}"
    memory = Memory(
        content=searchable_content,
        memory_type=MemoryType.PROCEDURAL if record_kind == "procedural_preference" else MemoryType.EPISODIC,
        trust_level=TrustLevel.USER_STATED,
        source="assessment_user_stated",
        embedding=embedder.embed(searchable_content),
        metadata=metadata,
    )
    store.insert(memory)
    return memory


def _scan_summary(report) -> tuple[str, dict[str, int]]:
    scans = [report.bandit, report.semgrep, report.trivy]
    failed = [scan.tool for scan in scans if scan.failed]
    if failed:
        raise typer.BadParameter(f"source scan failed for: {', '.join(failed)}")

    counts = {f"{scan.tool}_findings": scan.count for scan in scans if scan.available}
    unavailable = [scan.tool for scan in scans if not scan.available]
    summary = ", ".join(f"{tool}: {count}" for tool, count in counts.items())
    if unavailable:
        summary = f"{summary}; unavailable: {', '.join(unavailable)}"
    return summary or "No scanners available", counts


@app.command()
def add(
    content: str = typer.Argument(..., help="The fact or memory to store"),
    memory_type: MemoryType = typer.Option(MemoryType.SEMANTIC, "--type", "-t"),
    trust_level: TrustLevel = typer.Option(TrustLevel.USER_STATED, "--trust"),
    source: str = typer.Option("cli", "--source", "-s"),
    sanitize_content: bool = typer.Option(
        False,
        "--sanitize",
        help="Reject prompt-injection or secret-bearing content before storing "
        "(used by the plugin auto-capture path)",
    ),
    db: Path = typer.Option(DEFAULT_DB, "--db", envvar="MNEMO_DB"),
    embed_model: str = typer.Option(
        DEFAULT_EMBED_MODEL, "--embed-model", envvar=MNEMO_EMBED_MODEL
    ),
    ollama_url: str = typer.Option(
        DEFAULT_OLLAMA_URL, "--ollama-url", envvar=MNEMO_OLLAMA_URL
    ),
):
    """Store a new memory."""
    if sanitize_content:
        safe, reasons = is_safe_to_store(content)
        if not safe:
            console.print(
                f"[yellow]Skipped storing unsafe content: {', '.join(reasons)}[/yellow]"
            )
            return
    embedder = _get_embedder(embed_model, ollama_url)
    embedding = embedder.embed(content)
    store = _get_store(db, dimensions=len(embedding))

    memory = Memory(
        content=content,
        memory_type=memory_type,
        trust_level=trust_level,
        source=source,
        embedding=embedding,
    )
    store.insert(memory)
    console.print(f"[green]Stored memory {memory.id[:8]}...[/green]")
    store.close()
    embedder.close()


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    top_k: int = typer.Option(5, "--top-k", "-k"),
    recency_weight: float = typer.Option(0.3, "--recency"),
    db: Path = typer.Option(DEFAULT_DB, "--db", envvar="MNEMO_DB"),
    embed_model: str = typer.Option(
        DEFAULT_EMBED_MODEL, "--embed-model", envvar=MNEMO_EMBED_MODEL
    ),
    ollama_url: str = typer.Option(
        DEFAULT_OLLAMA_URL, "--ollama-url", envvar=MNEMO_OLLAMA_URL
    ),
):
    """Search memories by semantic similarity."""
    embedder = _get_embedder(embed_model, ollama_url)
    store = _get_store(db, dimensions=embedder.dimensions)

    # Apply the trained Phase 2 usefulness model when one is available.
    try:
        usefulness_model = UsefulnessModel.load_or_none()
    except (OSError, ValueError, KeyError, TypeError):  # corrupt model must not break retrieval
        usefulness_model = None
    mq = MemoryQuery(text=query, top_k=top_k, recency_weight=recency_weight)
    results = retrieve(store, embedder, mq, usefulness_model=usefulness_model)

    if not results:
        console.print("[yellow]No memories found.[/yellow]")
    else:
        table = Table(title=f"Search: '{query}'")
        table.add_column("Rank", style="dim", width=4)
        table.add_column("Score", width=6)
        table.add_column("Type", width=10)
        table.add_column("Trust", width=16)
        table.add_column("Content")
        table.add_column("ID", style="dim", width=10)

        for r in results:
            table.add_row(
                str(r.retrieval_rank + 1),
                f"{r.score:.3f}",
                r.memory.memory_type.value,
                r.memory.trust_level.value,
                r.memory.content[:80],
                r.memory.id[:8] + "...",
            )
        console.print(table)

        console.print()
        console.print(format_memories_block(results))

    store.close()
    embedder.close()


@assess_app.command("create")
def create_assessment(
    assessment_id: str = typer.Argument(..., help="Stable identifier for this authorized assessment"),
    target: str = typer.Option(..., "--target", help="Authorized target identifier"),
    authorized: str = typer.Option(
        ...,
        "--authorized",
        help="Your explicit declaration that this assessment is authorized",
    ),
    db: Path = ASSESSMENT_DB_OPTION,
    embed_model: str = typer.Option(
        DEFAULT_EMBED_MODEL, "--embed-model", envvar=MNEMO_EMBED_MODEL
    ),
    ollama_url: str = typer.Option(
        DEFAULT_OLLAMA_URL, "--ollama-url", envvar=MNEMO_OLLAMA_URL
    ),
):
    """Create a local context record for an explicitly authorized assessment."""
    assessment_id = _require_nonempty(assessment_id, "assessment ID")
    target = _require_nonempty(target, "--target")
    authorized = _require_nonempty(authorized, "--authorized")
    embedder = _get_embedder(embed_model, ollama_url)
    store: MemoryStore | None = None
    try:
        store = _get_store(db, dimensions=embedder.dimensions)
        if _assessment_context(store, assessment_id) is not None:
            console.print(f"[red]Assessment '{assessment_id}' already exists.[/red]")
            raise typer.Exit(1)

        authorized_at = datetime.now(UTC).isoformat()
        memory = _store_assessment_record(
            store,
            embedder,
            assessment_id=assessment_id,
            target_identifier=target,
            authorized_declaration=authorized,
            authorized_at=authorized_at,
            record_kind="context",
            content=f"Authorized assessment context for target {target}",
            severity="none",
            evidence_reference="",
            verification_status="authorized",
        )
        console.print(
            f"[green]Created authorized assessment {assessment_id} "
            f"({memory.id[:8]}...)[/green]"
        )
    finally:
        if store is not None:
            store.close()
        embedder.close()


@assess_app.command("record")
def record_assessment(
    assessment_id: str = typer.Argument(..., help="Existing authorized assessment identifier"),
    content: str = typer.Argument(..., help="Concise observation, finding, or outcome"),
    kind: str = typer.Option("observation", "--kind", help="Record kind, such as observation or finding"),
    severity: str = typer.Option("info", "--severity", help="User-stated severity"),
    evidence: str = typer.Option("", "--evidence", help="Evidence reference or local reference"),
    verification: str = typer.Option(
        "unverified", "--verification", help="Verification status stated by the user"
    ),
    db: Path = ASSESSMENT_DB_OPTION,
    embed_model: str = typer.Option(
        DEFAULT_EMBED_MODEL, "--embed-model", envvar=MNEMO_EMBED_MODEL
    ),
    ollama_url: str = typer.Option(
        DEFAULT_OLLAMA_URL, "--ollama-url", envvar=MNEMO_OLLAMA_URL
    ),
):
    """Save a concise user-stated record under an authorized assessment."""
    assessment_id = _require_nonempty(assessment_id, "assessment ID")
    content = _require_nonempty(content, "content")
    kind = _require_nonempty(kind, "--kind")
    severity = _require_nonempty(severity, "--severity")
    verification = _require_nonempty(verification, "--verification")
    embedder = _get_embedder(embed_model, ollama_url)
    store: MemoryStore | None = None
    try:
        store = _get_store(db, dimensions=embedder.dimensions)
        context = _assessment_context(store, assessment_id)
        if context is None:
            console.print(f"[red]No authorized context found for '{assessment_id}'.[/red]")
            raise typer.Exit(1)

        metadata = context.metadata
        memory = _store_assessment_record(
            store,
            embedder,
            assessment_id=assessment_id,
            target_identifier=metadata["target_identifier"],
            authorized_declaration=metadata["authorized_declaration"],
            authorized_at=metadata["authorized_at"],
            record_kind=kind,
            content=content,
            severity=severity,
            evidence_reference=evidence,
            verification_status=verification,
        )
        console.print(f"[green]Stored assessment record {memory.id[:8]}...[/green]")
    finally:
        if store is not None:
            store.close()
        embedder.close()


@assess_app.command("preference")
def record_assessment_preference(
    assessment_id: str = typer.Argument(..., help="Existing authorized assessment identifier"),
    project: str = typer.Argument(..., help="Project to which this preference applies"),
    preference: str = typer.Argument(..., help="User-stated procedural preference"),
    db: Path = ASSESSMENT_DB_OPTION,
    embed_model: str = typer.Option(
        DEFAULT_EMBED_MODEL, "--embed-model", envvar=MNEMO_EMBED_MODEL
    ),
    ollama_url: str = typer.Option(
        DEFAULT_OLLAMA_URL, "--ollama-url", envvar=MNEMO_OLLAMA_URL
    ),
):
    """Store a project-specific preference without executing any tool."""
    assessment_id = _require_nonempty(assessment_id, "assessment ID")
    project = _require_nonempty(project, "project")
    preference = _require_nonempty(preference, "preference")
    embedder = _get_embedder(embed_model, ollama_url)
    store: MemoryStore | None = None
    try:
        store = _get_store(db, dimensions=embedder.dimensions)
        context = _assessment_context(store, assessment_id)
        if context is None:
            console.print(f"[red]No authorized context found for '{assessment_id}'.[/red]")
            raise typer.Exit(1)

        metadata = context.metadata
        memory = _store_assessment_record(
            store,
            embedder,
            assessment_id=assessment_id,
            target_identifier=metadata["target_identifier"],
            authorized_declaration=metadata["authorized_declaration"],
            authorized_at=metadata["authorized_at"],
            record_kind="procedural_preference",
            content=f"For project {project}, {preference}",
            severity="none",
            evidence_reference="",
            verification_status="user_stated",
            project=project,
        )
        console.print(f"[green]Stored project preference {memory.id[:8]}...[/green]")
    finally:
        if store is not None:
            store.close()
        embedder.close()


@assess_app.command("source-scan")
def scan_assessment_source(
    assessment_id: str = typer.Argument(..., help="Existing authorized assessment identifier"),
    source_path: Path = typer.Option(
        ".", "--path", "-p", help="Local project directory to analyze"
    ),
    db: Path = ASSESSMENT_DB_OPTION,
    embed_model: str = typer.Option(
        DEFAULT_EMBED_MODEL, "--embed-model", envvar=MNEMO_EMBED_MODEL
    ),
    ollama_url: str = typer.Option(
        DEFAULT_OLLAMA_URL, "--ollama-url", envvar=MNEMO_OLLAMA_URL
    ),
):
    """Analyze local source and save its result; never contacts the assessment target."""
    assessment_id = _require_nonempty(assessment_id, "assessment ID")
    resolved_source_path = source_path.expanduser().resolve()
    report = full_scan(str(resolved_source_path))
    try:
        summary, counts = _scan_summary(report)
    except typer.BadParameter as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    embedder = _get_embedder(embed_model, ollama_url)
    store: MemoryStore | None = None
    try:
        store = _get_store(db, dimensions=embedder.dimensions)
        context = _assessment_context(store, assessment_id)
        if context is None:
            console.print(f"[red]No authorized context found for '{assessment_id}'.[/red]")
            raise typer.Exit(1)

        metadata = context.metadata
        memory = _store_assessment_record(
            store,
            embedder,
            assessment_id=assessment_id,
            target_identifier=metadata["target_identifier"],
            authorized_declaration=metadata["authorized_declaration"],
            authorized_at=metadata["authorized_at"],
            record_kind="source_scan",
            content=f"Local source scan for {resolved_source_path}: {summary}",
            severity="info",
            evidence_reference=str(resolved_source_path),
            verification_status="tool_reported",
            extra_metadata={"source_path": str(resolved_source_path), **counts},
        )
        console.print(f"[green]Stored source scan record {memory.id[:8]}...[/green]")
    finally:
        if store is not None:
            store.close()
        embedder.close()


@assess_app.command("list")
def list_assessment_records(
    assessment_id: str | None = typer.Argument(None, help="Optionally filter by assessment identifier"),
    db: Path = ASSESSMENT_DB_OPTION,
):
    """List local authorized-assessment contexts and records."""
    store = _get_store(db, dimensions=None)
    try:
        records = [
            memory
            for memory in store.list_all()
            if "assessment_id" in memory.metadata
            and (assessment_id is None or memory.metadata["assessment_id"] == assessment_id)
        ]
        if not records:
            console.print("[yellow]No assessment records found.[/yellow]")
            return

        table = Table(title=f"Assessment records ({len(records)} total)")
        table.add_column("Assessment", width=16)
        table.add_column("Kind", width=22)
        table.add_column("Target", width=18)
        table.add_column("Severity", width=10)
        table.add_column("Verification", width=14)
        table.add_column("Content")
        for memory in records:
            metadata = memory.metadata
            table.add_row(
                metadata["assessment_id"],
                metadata["record_kind"],
                metadata["target_identifier"],
                metadata["severity"],
                metadata["verification_status"],
                memory.content[:80],
            )
        console.print(table)
    finally:
        store.close()


@app.command(name="list")
def list_memories(
    memory_type: MemoryType | None = typer.Option(None, "--type", "-t"),
    db: Path = typer.Option(DEFAULT_DB, "--db", envvar="MNEMO_DB"),
):
    """List all stored memories."""
    store = _get_store(db, dimensions=768)
    memories = store.list_all(memory_type=memory_type)

    if not memories:
        console.print("[yellow]No memories stored yet.[/yellow]")
    else:
        table = Table(title=f"Memories ({len(memories)} total)")
        table.add_column("ID", style="dim", width=10)
        table.add_column("Type", width=10)
        table.add_column("Trust", width=16)
        table.add_column("Decay", width=6)
        table.add_column("Content")
        table.add_column("Created", width=12)

        for m in memories:
            table.add_row(
                m.id[:8] + "...",
                m.memory_type.value,
                m.trust_level.value,
                f"{m.decay_score:.2f}",
                m.content[:60],
                m.created_at.strftime("%Y-%m-%d"),
            )
        console.print(table)

    store.close()


@app.command()
def forget(
    memory_id: str = typer.Argument(..., help="Memory ID (or prefix) to delete"),
    db: Path = typer.Option(DEFAULT_DB, "--db", envvar="MNEMO_DB"),
):
    """Delete a memory by ID."""
    store = _get_store(db, dimensions=768)

    if len(memory_id) < 32:
        all_memories = store.list_all()
        matches = [m for m in all_memories if m.id.startswith(memory_id)]
        if len(matches) == 0:
            console.print(f"[red]No memory found with prefix '{memory_id}'[/red]")
            store.close()
            raise typer.Exit(1)
        if len(matches) > 1:
            console.print(f"[red]Ambiguous prefix '{memory_id}' — matches {len(matches)} memories[/red]")
            store.close()
            raise typer.Exit(1)
        memory_id = matches[0].id

    if store.delete(memory_id):
        console.print(f"[green]Deleted memory {memory_id[:8]}...[/green]")
    else:
        console.print(f"[red]Memory {memory_id[:8]}... not found[/red]")

    store.close()


@app.command()
def stats(
    db: Path = typer.Option(DEFAULT_DB, "--db", envvar="MNEMO_DB"),
):
    """Show memory store statistics."""
    store = _get_store(db, dimensions=768)
    total = store.count()
    memories = store.list_all()

    type_counts = {}
    trust_counts = {}
    for m in memories:
        type_counts[m.memory_type.value] = type_counts.get(m.memory_type.value, 0) + 1
        trust_counts[m.trust_level.value] = trust_counts.get(m.trust_level.value, 0) + 1

    console.print(f"[bold]Total memories:[/bold] {total}")
    console.print(f"[bold]By type:[/bold] {type_counts}")
    console.print(f"[bold]By trust:[/bold] {trust_counts}")
    if memories:
        oldest = min(m.created_at for m in memories)
        newest = max(m.created_at for m in memories)
        console.print(f"[bold]Date range:[/bold] {oldest:%Y-%m-%d} → {newest:%Y-%m-%d}")

    store.close()


@app.command()
def scan(
    project_path: str = typer.Option(".", "--path", "-p", help="Project path to scan"),
):
    """Run security scanners (bandit, semgrep, trivy) on the project."""
    console.print("[bold]Running security scan...[/bold]\n")
    report = full_scan(project_path)

    table = Table(title="Security Scan Results")
    table.add_column("Tool", width=10)
    table.add_column("Status", width=14)
    table.add_column("Findings", width=10)
    table.add_column("Details")

    scans = [report.bandit, report.semgrep, report.trivy]
    for sf in scans:
        if sf.failed:
            status = "[red]error[/red]"
            details = sf.error
        elif not sf.available:
            status = "[yellow]not installed[/yellow]"
            details = sf.error or "Install to enable"
        elif sf.count == 0:
            status = "[green]clean[/green]"
            details = "No issues found"
        else:
            status = "[red]findings[/red]"
            details = f"{sf.count} issue(s) detected"
        table.add_row(sf.tool, status, str(sf.count), details)

    console.print(table)
    for sf in scans:
        if sf.failed:
            console.print(f"[red]{sf.tool} scan error: {sf.error}[/red]")
    console.print(f"\nScan completed at {report.timestamp:%Y-%m-%d %H:%M:%S UTC}")
    if any(sf.failed for sf in scans):
        raise typer.Exit(1)


@tools_app.command("list")
def list_security_tools(
    category: str | None = typer.Option(None, "--category", "-c", help="Filter by category"),
):
    """List registered security tools available to local or Docker/Kali runners."""
    tools = list_tools(category=category)
    if not tools:
        console.print("[yellow]No registered tools matched.[/yellow]")
        return

    table = Table(title=f"Registered security tools ({len(tools)})")
    table.add_column("Tool", width=22)
    table.add_column("Category", width=20)
    table.add_column("Mode", width=12)
    table.add_column("Authorization", width=15)
    table.add_column("Package/Hint")
    for tool in tools:
        table.add_row(
            tool.name,
            tool.category,
            "passive" if tool.passive else "active",
            "required" if tool.requires_authorization else "not required",
            tool.package_hint,
        )
    console.print(table)


@tools_app.command("run", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def run_security_tool(
    ctx: typer.Context,
    tool: str = typer.Argument(..., help="Registered tool name, e.g. nmap, nuclei, sqlmap"),
    mode: ToolMode = typer.Option(ToolMode.DOCKER, "--mode", help="Execution mode"),
    docker_image: str = typer.Option(
        "shannon-tools",
        "--docker-image",
        envvar="MNEMO_SECURITY_DOCKER_IMAGE",
        help="Docker image containing Kali/security tools",
    ),
    workdir: Path | None = typer.Option(
        None, "--workdir", "-w", help="Directory mounted at /workspace in Docker mode"
    ),
    timeout: int = typer.Option(300, "--timeout", help="Tool timeout in seconds", min=1),
    authorization: str = typer.Option(
        "",
        "--authorized",
        envvar="MNEMO_SECURITY_AUTHORIZATION",
        help="Explicit authorization text required for active tools",
    ),
):
    """Run a registered security tool locally or inside a Docker/Kali image.

    Any arguments after the tool name are passed through to the tool. Example:

    mnemo tools run nmap --authorized "ticket SEC-123" -- -sV example.com
    """
    args = list(ctx.args)
    if args and args[0] == "--":
        args = args[1:]
    runner = ToolRunner(
        mode=mode,
        docker_image=docker_image,
        workdir=workdir,
        timeout_seconds=timeout,
        authorization=authorization,
    )
    try:
        execution = runner.run(tool, args)
    except (PermissionError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    console.print(f"[bold]Command:[/bold] {' '.join(execution.command)}")
    if execution.stdout:
        console.print(execution.stdout.rstrip())
    if execution.stderr:
        console.print(f"[red]{execution.stderr.rstrip()}[/red]")
    if not execution.succeeded:
        raise typer.Exit(execution.returncode or 1)


@app.command()
def redteam(
    attacks_per_type: int = typer.Option(10, "--attacks-per-type", "-n", min=1),
    db: Path = REDTEAM_DB_OPTION,
    embed_model: str = typer.Option(
        DEFAULT_EMBED_MODEL, "--embed-model", envvar=MNEMO_EMBED_MODEL
    ),
    ollama_url: str = typer.Option(
        DEFAULT_OLLAMA_URL, "--ollama-url", envvar=MNEMO_OLLAMA_URL
    ),
    llm_model: str = typer.Option(DEFAULT_LLM_MODEL, "--llm-model", envvar=MNEMO_LLM_MODEL),
):
    """Run a red-team campaign against an isolated assessment store."""
    embedder = _get_embedder(embed_model, ollama_url)
    llm: LLMClient | None = None
    store: MemoryStore | None = None
    try:
        llm = LLMClient(model=llm_model, base_url=ollama_url)
        if not llm.is_available():
            console.print("[red]LLM not available. Start Ollama first.[/red]")
            raise typer.Exit(1)

        store = _get_store(db, dimensions=embedder.dimensions)
        console.print(f"[bold]Red-team campaign: {attacks_per_type} attacks per type[/bold]\n")
        results = run_campaign(llm, store, embedder, n_per_type=attacks_per_type)

        if not results:
            console.print(
                "[yellow]Red-team campaign produced no results; no defense rate can be calculated.[/yellow]"
            )
            raise typer.Exit(1)

        type_stats: dict[str, dict[str, int]] = {}
        for r in results:
            key = r.attack_type.value
            if key not in type_stats:
                type_stats[key] = {"total": 0, "blocked": 0, "entered": 0}
            type_stats[key]["total"] += 1
            if r.entered_store:
                type_stats[key]["entered"] += 1
            else:
                type_stats[key]["blocked"] += 1

        table = Table(title="Red-Team Results")
        table.add_column("Attack Type", width=24)
        table.add_column("Total", width=8)
        table.add_column("Blocked", width=8)
        table.add_column("Entered Store", width=14)
        table.add_column("Defense Rate", width=12)

        for attack_type, s in type_stats.items():
            rate = s["blocked"] / s["total"] * 100 if s["total"] > 0 else 0
            color = "green" if rate >= 80 else "yellow" if rate >= 50 else "red"
            table.add_row(
                attack_type,
                str(s["total"]),
                str(s["blocked"]),
                str(s["entered"]),
                f"[{color}]{rate:.0f}%[/{color}]",
            )

        console.print(table)
        total = len(results)
        blocked = sum(1 for r in results if not r.entered_store)
        console.print(
            f"\n[bold]Overall:[/bold] {blocked}/{total} attacks blocked ({blocked/total*100:.0f}%)"
        )
    except httpx.HTTPError:
        console.print("[red]Red-team campaign failed due to an Ollama HTTP error.[/red]")
        raise typer.Exit(1)
    finally:
        if store is not None:
            store.close()
        if llm is not None:
            llm.close()
        embedder.close()


@app.command()
def context(
    query: str = typer.Argument(..., help="Query to fetch memories for"),
    top_k: int = typer.Option(5, "--top-k", "-k"),
    db: Path = typer.Option(DEFAULT_DB, "--db", envvar="MNEMO_DB"),
    embed_model: str = typer.Option(
        DEFAULT_EMBED_MODEL, "--embed-model", envvar=MNEMO_EMBED_MODEL
    ),
    ollama_url: str = typer.Option(
        DEFAULT_OLLAMA_URL, "--ollama-url", envvar=MNEMO_OLLAMA_URL
    ),
):
    """Print only the formatted memory block for a query (for prompt injection).

    Bare output on stdout, no tables or decorations; empty output when nothing
    is relevant. Used by the OpenCode plugin's prompt hook.
    """
    embedder = _get_embedder(embed_model, ollama_url)
    store = _get_store(db, dimensions=embedder.dimensions)
    try:
        try:
            usefulness_model = UsefulnessModel.load_or_none()
        except (OSError, ValueError, KeyError, TypeError):
            usefulness_model = None
        results = retrieve(
            store, embedder, MemoryQuery(text=query, top_k=top_k),
            usefulness_model=usefulness_model,
        )
        block = format_memories_block(results)
    finally:
        store.close()
        embedder.close()
    if block:
        print(block)


@app.command()
def score(
    content: str = typer.Argument(..., help="Memory content to score"),
    query: str = typer.Option("", "--query", "-q", help="Query context for the score"),
    db: Path = typer.Option(DEFAULT_DB, "--db", envvar="MNEMO_DB"),
    embed_model: str = typer.Option(
        DEFAULT_EMBED_MODEL, "--embed-model", envvar=MNEMO_EMBED_MODEL
    ),
    ollama_url: str = typer.Option(
        DEFAULT_OLLAMA_URL, "--ollama-url", envvar=MNEMO_OLLAMA_URL
    ),
):
    """Print the trained model's P(helpful) for a (query, memory) pair.

    Used by the OpenCode plugin's predictMemoryUsefulness(); exits non-zero
    when no trained model is available so callers can fall back gracefully.
    """
    model = UsefulnessModel.load_or_none()
    if model is None:
        console.print("[red]No trained usefulness model. Run train-usefulness first.[/red]")
        raise typer.Exit(1)

    embedder = _get_embedder(embed_model, ollama_url)
    try:
        if query:
            q_emb = embedder.embed(query)
            m_emb = embedder.embed(content)
            dot = sum(a * b for a, b in zip(q_emb, m_emb, strict=True))
            nq = sum(a * a for a in q_emb) ** 0.5 or 1.0
            nm = sum(b * b for b in m_emb) ** 0.5 or 1.0
            similarity = dot / (nq * nm)
        else:
            similarity = 0.5
        p = model.score(similarity=similarity, recency=1.0)
    finally:
        embedder.close()
    # Bare number on stdout so shell/plugin callers can parse it directly.
    print(f"{p:.4f}")


@app.command()
def lifecycle(
    db: Path = typer.Option(DEFAULT_DB, "--db", envvar="MNEMO_DB"),
    half_life_days: float = typer.Option(30.0, "--half-life", help="Decay half-life in days"),
    prune_below: float | None = typer.Option(
        0.05, "--prune-below", help="Delete memories with decay_score below this"
    ),
    dedup_threshold: float = typer.Option(
        0.92, "--dedup-threshold", help="Cosine similarity above which memories merge"
    ),
    resolve_conflicts: bool = typer.Option(
        False, "--resolve-conflicts", help="Delete the stale member of each conflict pair"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report changes without applying"),
):
    """Run memory lifecycle maintenance: decay, dedup, conflict handling (Phase 3)."""
    store = _get_store(db, dimensions=None)
    try:
        report = run_lifecycle(
            store,
            half_life_days=half_life_days,
            prune_below=prune_below,
            dedup_threshold=dedup_threshold,
            resolve_conflicts=resolve_conflicts,
            dry_run=dry_run,
        )
    finally:
        store.close()

    mode = "[yellow]DRY RUN[/yellow] " if report.dry_run else ""
    console.print(f"{mode}[bold]Lifecycle report[/bold]")
    console.print(f"  Decay recomputed: {report.decayed} memories")
    console.print(f"  Pruned (stale):   {len(report.pruned_ids)}")
    console.print(
        f"  Duplicates:       {report.duplicates_removed} merged "
        f"across {len(report.duplicate_clusters)} clusters"
    )
    console.print(f"  Conflicts found:  {len(report.conflicts)}")
    for conflict in report.conflicts[:10]:
        console.print(
            f"    [dim]{conflict.reason} (sim={conflict.similarity:.2f})[/dim]\n"
            f"      keep:  {conflict.keeper.content[:70]}\n"
            f"      stale: {conflict.stale.content[:70]}"
        )


@app.command("generate-dataset")
def generate_dataset_cmd(
    out: Path = typer.Option(
        Path("data/sample_conversations/dataset.json"), "--out"
    ),
    n: int = typer.Option(10, "--n", help="Number of conversations"),
    seed: int = typer.Option(42, "--seed"),
):
    """Generate a synthetic multi-session conversation dataset (Phase 4 data)."""
    from mnemo.eval.dataset import generate_dataset

    dataset = generate_dataset(n_conversations=n, seed=seed)
    path = dataset.save(out)
    n_qa = sum(len(c.qa_pairs) for c in dataset.conversations)
    console.print(f"[green]Wrote {n} conversations ({n_qa} QA pairs) to {path}[/green]")


@app.command("label-usefulness")
def label_usefulness_cmd(
    dataset_path: Path = typer.Option(
        Path("data/sample_conversations/dataset.json"), "--dataset"
    ),
    out: Path = typer.Option(
        Path("data/sample_conversations/usefulness-labels.json"), "--out"
    ),
    top_k: int = typer.Option(5, "--top-k"),
    embed_model: str = typer.Option(DEFAULT_EMBED_MODEL, "--embed-model", envvar=MNEMO_EMBED_MODEL),
    ollama_url: str = typer.Option(DEFAULT_OLLAMA_URL, "--ollama-url", envvar=MNEMO_OLLAMA_URL),
):
    """Label (query, memory) pairs as helpful/not for Phase 2 training."""
    from mnemo.eval.dataset import Dataset, label_usefulness_examples, save_examples

    embedder = _get_embedder(embed_model, ollama_url)
    try:
        dataset = Dataset.load(dataset_path)
        examples = label_usefulness_examples(dataset, embedder, top_k=top_k)
        path = save_examples(examples, out)
    finally:
        embedder.close()

    n_pos = sum(1 for e in examples if e.helpful)
    console.print(
        f"[green]Wrote {len(examples)} labeled examples "
        f"({n_pos} helpful / {len(examples) - n_pos} not) to {path}[/green]"
    )


@app.command("train-usefulness")
def train_usefulness_cmd(
    labels: Path = typer.Option(
        Path("data/sample_conversations/usefulness-labels.json"), "--labels"
    ),
    out: Path = typer.Option(None, "--out", help="Model output path (default: mnemo data dir)"),
    test_fraction: float = typer.Option(0.25, "--test-fraction"),
):
    """Train the Phase 2 usefulness model from labeled examples."""
    import random

    from mnemo.eval.dataset import load_examples
    from mnemo.eval.usefulness import evaluate_usefulness_model, train_usefulness_model

    examples = load_examples(labels)
    if len(examples) < 4:
        console.print(
            f"[red]Need at least 4 labeled examples, got {len(examples)}. "
            "Run label-usefulness first.[/red]"
        )
        raise typer.Exit(1)

    # Stratified split so the rare "helpful" class appears in both sets.
    rng = random.Random(42)
    positives = [e for e in examples if e.helpful]
    negatives = [e for e in examples if not e.helpful]
    rng.shuffle(positives)
    rng.shuffle(negatives)
    n_test_pos = max(1, int(len(positives) * test_fraction)) if positives else 0
    test_set = positives[:n_test_pos] + negatives[: int(len(negatives) * test_fraction)]
    train_set = positives[n_test_pos:] + negatives[int(len(negatives) * test_fraction):]
    rng.shuffle(train_set)

    model = train_usefulness_model(train_set)
    metrics = evaluate_usefulness_model(model, test_set)
    path = model.save(out)

    console.print(f"[green]Trained on {len(train_set)} examples → {path}[/green]")
    console.print(
        f"  holdout: acc={metrics['accuracy']:.2f} prec={metrics['precision']:.2f} "
        f"rec={metrics['recall']:.2f} f1={metrics['f1']:.2f} (n={int(metrics['n'])})"
    )


@app.command("benchmark")
def benchmark_cmd(
    dataset_path: Path = typer.Option(
        Path("data/sample_conversations/dataset.json"), "--dataset"
    ),
    out: Path = typer.Option(Path("data/benchmark-report.json"), "--out"),
    top_k: int = typer.Option(5, "--top-k"),
    usefulness_threshold: float = typer.Option(0.5, "--usefulness-threshold"),
    embed_model: str = typer.Option(DEFAULT_EMBED_MODEL, "--embed-model", envvar=MNEMO_EMBED_MODEL),
    ollama_url: str = typer.Option(DEFAULT_OLLAMA_URL, "--ollama-url", envvar=MNEMO_OLLAMA_URL),
    llm_model: str = typer.Option(DEFAULT_LLM_MODEL, "--llm-model", envvar=MNEMO_LLM_MODEL),
):
    """Run the ablation benchmark (no-memory / memory-only / +selection / +lifecycle).

    Phase 4 impact analysis: QA F1, retrieval Recall@k, and stale-fact bias per
    configuration. --dataset accepts other multi-session QA data (e.g. a
    converted LoCoMo / LongMemEval subset) with the same schema.
    """
    from mnemo.eval.benchmark import format_report, run_benchmark
    from mnemo.eval.dataset import Dataset

    embedder = _get_embedder(embed_model, ollama_url)
    llm = LLMClient(model=llm_model, base_url=ollama_url)
    if not llm.is_available():
        console.print("[red]LLM not available. Start Ollama first.[/red]")
        raise typer.Exit(1)

    usefulness_model = UsefulnessModel.load_or_none()
    if usefulness_model is None:
        console.print(
            "[yellow]No trained usefulness model found — "
            "the memory+selection configuration will be skipped.[/yellow]"
        )

    try:
        dataset = Dataset.load(dataset_path)
        report = run_benchmark(
            dataset,
            embedder,
            llm,
            usefulness_model=usefulness_model,
            top_k=top_k,
            usefulness_threshold=usefulness_threshold,
        )
        report.save(out)
    finally:
        embedder.close()
        llm.close()

    console.print(format_report(report))
    console.print(f"\n[green]Full report saved to {out}[/green]")


@app.command()
def pentest(
    source_path: str = typer.Option(".", "--source", "-s", help="Source code path to analyze"),
    target_url: str = typer.Option(..., "--target", "-t", help="Deployment URL to test against"),
    assessment_id: str = typer.Option(
        ..., "--assessment", "-a", help="Existing authorized assessment identifier"
    ),
    db: Path = ASSESSMENT_DB_OPTION,
    allow_subdomains: bool = typer.Option(
        False, "--allow-subdomains", help="Allow testing subdomains of the target host"
    ),
    allow_private_ips: bool = typer.Option(
        False, "--allow-private-ips", help="Allow private/localhost targets for lab environments"
    ),
    max_requests: int = typer.Option(100, "--max-requests", help="Maximum active HTTP requests", min=1),
    report_dir: Path = typer.Option(Path("."), "--report-dir", help="Directory for reports"),
):
    """Perform authorized active testing against a deployed target.

    Create the required authorization context first with:
    mnemo assess create <id> --target <url> --authorized <approval text>
    """
    try:
        store = _get_store(db, dimensions=None)
        try:
            context = _assessment_context(store, assessment_id)
        finally:
            store.close()
        if context is None:
            console.print(f"[red]No authorized context found for '{assessment_id}'.[/red]")
            raise typer.Exit(1)

        metadata = context.metadata
        authorization = str(metadata["authorized_declaration"])
        declared_target = str(metadata["target_identifier"])
        if declared_target.startswith(("http://", "https://")) and declared_target.rstrip("/") != target_url.rstrip("/"):
            console.print(
                "[red]Pentest target must match the assessment target "
                f"({declared_target}).[/red]"
            )
            raise typer.Exit(1)

        scope_policy = ScopePolicy.from_target_url(
            target_url,
            authorization,
            allow_subdomains=allow_subdomains,
            allow_private_ips=allow_private_ips,
            max_requests=max_requests,
        )
        console.print(
            f"[bold]Authorized pentest campaign:[/bold] {source_path} → {target_url} "
            f"(assessment {assessment_id})\n"
        )
        
        async def run_pentest():
            async with Pentester(
                target_url,
                scope_policy=scope_policy,
                assessment_id=assessment_id,
            ) as pentester:
                await pentester.execute_attacks(source_path)
                report = pentester.generate_report()
                assessment_report = pentester.assessment_report()
                
                # Display summary
                summary = report["summary"]
                console.print(f"Total tests: {summary['total_tests']}")
                console.print(f"Verified payload indicators: {summary['successful_attacks']}")
                console.print(f"Indicator rate: {summary['success_rate']:.1%}")
                
                # Show vulnerable endpoints
                vulnerable = report["vulnerable_endpoints"]
                if vulnerable:
                    console.print("\n[bold]Vulnerable endpoints found:[/bold]")
                    for endpoint in vulnerable[:10]:  # Limit to first 10
                        console.print(f"  - {endpoint}")
                    if len(vulnerable) > 10:
                        console.print(f"  ... and {len(vulnerable) - 10} more")
                else:
                    console.print("\n[yellow]No payload indicators matched.[/yellow]")
                
                return report, assessment_report

        # Run the async pentest
        import asyncio
        import json
        report, assessment_report = asyncio.run(run_pentest())
        
        # Save report to file
        report_file = report_dir / f"{assessment_id}-pentest-legacy.json"
        with open(report_file, "w") as f:
            json.dump(report, f, indent=2)
        json_report = write_json_report(
            assessment_report, report_dir / f"{assessment_id}-pentest.json"
        )
        markdown_report = write_markdown_report(
            assessment_report, report_dir / f"{assessment_id}-pentest.md"
        )
        console.print(f"\n[green]Legacy report saved to {report_file}[/green]")
        console.print(f"[green]JSON report saved to {json_report}[/green]")
        console.print(f"[green]Markdown report saved to {markdown_report}[/green]")
        
    except (OSError, RuntimeError, ScopeViolation, httpx.HTTPError, httpx.InvalidURL) as e:
        console.print(f"[red]Pentest failed: {e}[/red]")
        raise typer.Exit(1) from e


if __name__ == "__main__":
    app()
