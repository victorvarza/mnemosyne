import httpx
from typer.testing import CliRunner

from mnemo import cli
from mnemo.core.embeddings import EmbeddingModel
from mnemo.core.llm import LLMClient
from mnemo.core.store import MemoryStore
from mnemo.security.redteam import AttackResult, AttackType
from mnemo.security.scanner import ScanFindings, SecurityReport

runner = CliRunner()


class _FakeEmbedder:
    dimensions = 4

    def embed(self, _content: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]

    def close(self) -> None:
        pass


class _FakeStore:
    def insert(self, _memory) -> None:
        pass

    def close(self) -> None:
        pass


def test_assessment_requires_authorization_and_target():
    missing_authorization = runner.invoke(cli.app, ["assess", "create", "assessment-1", "--target", "app-1"])
    missing_target = runner.invoke(
        cli.app, ["assess", "create", "assessment-1", "--authorized", "I am authorized"]
    )

    assert missing_authorization.exit_code != 0
    assert "--authorized" in missing_authorization.output
    assert missing_target.exit_code != 0
    assert "--target" in missing_target.output


def test_assessment_records_context_preference_and_metadata(monkeypatch, tmp_path):
    db = tmp_path / "assessment.db"
    monkeypatch.setattr(cli, "_get_embedder", lambda *_args: _FakeEmbedder())
    # Keep the test hermetic: never pick up a locally trained usefulness model.
    monkeypatch.setenv("MNEMO_USEFULNESS_MODEL", str(tmp_path / "no-model.json"))

    create = runner.invoke(
        cli.app,
        [
            "assess",
            "create",
            "assessment-1",
            "--target",
            "inventory-api",
            "--authorized",
            "I confirm approval ticket SEC-123",
            "--db",
            str(db),
        ],
    )
    record = runner.invoke(
        cli.app,
        [
            "assess",
            "record",
            "assessment-1",
            "Observed a configuration gap",
            "--kind",
            "finding",
            "--severity",
            "medium",
            "--evidence",
            "evidence/SEC-123-note",
            "--verification",
            "verified",
            "--db",
            str(db),
        ],
    )
    preference = runner.invoke(
        cli.app,
        [
            "assess",
            "preference",
            "assessment-1",
            "inventory",
            "prefer Metasploit for approved validation tasks",
            "--db",
            str(db),
        ],
    )
    listing = runner.invoke(cli.app, ["assess", "list", "assessment-1", "--db", str(db)])
    search = runner.invoke(cli.app, ["search", "assessment-1", "--db", str(db)])

    assert create.exit_code == 0, create.output
    assert record.exit_code == 0, record.output
    assert preference.exit_code == 0, preference.output
    assert listing.exit_code == 0, listing.output
    assert search.exit_code == 0, search.output
    assert "inventory-api" in listing.output
    assert "finding" in listing.output
    assert "assessment-1" in search.output

    store = MemoryStore(db, dimensions=4)
    records = store.list_all()
    store.close()
    assert len(records) == 3
    finding = next(m for m in records if m.metadata["record_kind"] == "finding")
    assert finding.trust_level.value == "user_stated"
    assert finding.source == "assessment_user_stated"
    preference_record = next(
        m for m in records if m.metadata["record_kind"] == "procedural_preference"
    )
    assert preference_record.metadata["project"] == "inventory"
    assert finding.metadata == {
        "assessment_id": "assessment-1",
        "target_identifier": "inventory-api",
        "authorized_declaration": "I confirm approval ticket SEC-123",
        "authorized_at": finding.metadata["authorized_at"],
        "record_kind": "finding",
        "severity": "medium",
        "evidence_reference": "evidence/SEC-123-note",
        "verification_status": "verified",
    }


def test_assessment_source_scan_stores_local_summary(monkeypatch, tmp_path):
    db = tmp_path / "assessment.db"
    source_path = tmp_path / "project"
    source_path.mkdir()
    monkeypatch.setattr(cli, "_get_embedder", lambda *_args: _FakeEmbedder())
    monkeypatch.setattr(
        cli,
        "full_scan",
        lambda _path: SecurityReport(
            bandit=ScanFindings(tool="bandit", available=True, findings=[{"issue": "one"}]),
            semgrep=ScanFindings(tool="semgrep", available=False, error="Tool not installed"),
            trivy=ScanFindings(tool="trivy", available=True, findings=[{"issue": "two"}]),
        ),
    )

    create = runner.invoke(
        cli.app,
        [
            "assess",
            "create",
            "assessment-1",
            "--target",
            "inventory-api",
            "--authorized",
            "I confirm approval ticket SEC-123",
            "--db",
            str(db),
        ],
    )
    result = runner.invoke(
        cli.app,
        ["assess", "source-scan", "assessment-1", "--path", str(source_path), "--db", str(db)],
    )

    assert create.exit_code == 0, create.output
    assert result.exit_code == 0, result.output
    store = MemoryStore(db, dimensions=4)
    record = next(m for m in store.list_all() if m.metadata["record_kind"] == "source_scan")
    store.close()
    assert record.metadata["source_path"] == str(source_path)
    assert record.metadata["bandit_findings"] == 1
    assert record.metadata["trivy_findings"] == 1
    assert "unavailable: semgrep" in record.content


def test_assessment_list_empty_custom_db_does_not_set_embedding_dimensions(monkeypatch, tmp_path):
    db = tmp_path / "assessment.db"
    monkeypatch.setattr(cli, "_get_embedder", lambda *_args: _FakeEmbedder())

    listing = runner.invoke(cli.app, ["assess", "list", "--db", str(db)])
    create = runner.invoke(
        cli.app,
        [
            "assess",
            "create",
            "assessment-1",
            "--target",
            "inventory-api",
            "--authorized",
            "I confirm approval ticket SEC-123",
            "--embed-model",
            "non-768-embedding-model",
            "--db",
            str(db),
        ],
    )

    assert listing.exit_code == 0, listing.output
    assert "No assessment records found" in listing.output
    assert create.exit_code == 0, create.output

    store = MemoryStore(db, dimensions=_FakeEmbedder.dimensions)
    assert store.count() == 1
    store.close()


def test_assessment_record_requires_existing_context(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_get_embedder", lambda *_args: _FakeEmbedder())

    result = runner.invoke(
        cli.app,
        ["assess", "record", "missing", "An observation", "--db", str(tmp_path / "assessment.db")],
    )

    assert result.exit_code == 1
    assert "No authorized context found" in result.output


def test_pentest_requires_existing_authorized_assessment(tmp_path):
    result = runner.invoke(
        cli.app,
        [
            "pentest",
            "--assessment",
            "missing",
            "--target",
            "https://example.com",
            "--db",
            str(tmp_path / "assessment.db"),
        ],
    )

    assert result.exit_code == 1
    assert "No authorized context found" in result.output


def test_tools_list_shows_registered_catalog():
    result = runner.invoke(cli.app, ["tools", "list", "--category", "network-recon"])

    assert result.exit_code == 0, result.output
    assert "nmap" in result.output
    assert "network-recon" in result.output


def test_add_sanitize_blocks_secret_before_storing(monkeypatch, tmp_path):
    db = tmp_path / "memory.db"
    # If the embedder were reached, the test would need Ollama; the sanitize
    # gate must short-circuit before any embedding call.
    def fail_embedder(*_args, **_kwargs):
        raise AssertionError("embedder must not be called for blocked content")

    monkeypatch.setattr(cli, "_get_embedder", fail_embedder)

    result = runner.invoke(
        cli.app,
        ["add", "--sanitize", "the token is ghp_0123456789abcdef0123456789abcdef0123", "--db", str(db)],
    )

    assert result.exit_code == 0, result.output
    assert "Skipped storing unsafe content" in result.output
    assert "github_token" in result.output
    assert not db.exists()


def test_add_sanitize_allows_benign_content(monkeypatch, tmp_path):
    db = tmp_path / "memory.db"
    monkeypatch.setattr(cli, "_get_embedder", lambda *_args: _FakeEmbedder())
    monkeypatch.setattr(cli, "_get_store", lambda *_args, **_kwargs: _FakeStore())

    result = runner.invoke(
        cli.app,
        ["add", "--sanitize", "User prefers Python over Java", "--db", str(db)],
    )

    assert result.exit_code == 0, result.output
    assert "Stored memory" in result.output


def test_add_uses_environment_inference_defaults(monkeypatch):
    received: dict[str, str] = {}

    def get_embedder(model: str, base_url: str) -> _FakeEmbedder:
        received.update(model=model, base_url=base_url)
        return _FakeEmbedder()

    monkeypatch.setattr(cli, "_get_embedder", get_embedder)
    monkeypatch.setattr(cli, "_get_store", lambda *_args, **_kwargs: _FakeStore())

    result = runner.invoke(
        cli.app,
        ["add", "User prefers Python"],
        env={
            "MNEMO_OLLAMA_URL": "http://worker.internal:11434",
            "MNEMO_EMBED_MODEL": "custom-embed",
        },
    )

    assert result.exit_code == 0, result.output
    assert received == {
        "model": "custom-embed",
        "base_url": "http://worker.internal:11434",
    }


def test_explicit_inference_options_override_environment(monkeypatch):
    received: dict[str, str] = {}

    def get_embedder(model: str, base_url: str) -> _FakeEmbedder:
        received.update(model=model, base_url=base_url)
        return _FakeEmbedder()

    monkeypatch.setattr(cli, "_get_embedder", get_embedder)
    monkeypatch.setattr(cli, "_get_store", lambda *_args, **_kwargs: _FakeStore())

    result = runner.invoke(
        cli.app,
        [
            "add",
            "User prefers Python",
            "--ollama-url",
            "http://override.internal:11434",
            "--embed-model",
            "override-embed",
        ],
        env={
            "MNEMO_OLLAMA_URL": "http://worker.internal:11434",
            "MNEMO_EMBED_MODEL": "custom-embed",
        },
    )

    assert result.exit_code == 0, result.output
    assert received == {
        "model": "override-embed",
        "base_url": "http://override.internal:11434",
    }


def test_redteam_uses_llm_environment_default(monkeypatch):
    received: dict[str, str | object] = {}

    class FakeLLM:
        def __init__(self, model: str, base_url: str) -> None:
            received.update(model=model, base_url=base_url)

        def is_available(self) -> bool:
            return True

        def close(self) -> None:
            pass

    monkeypatch.setattr(cli, "_get_embedder", lambda *_args: _FakeEmbedder())
    monkeypatch.setattr(
        cli,
        "_get_store",
        lambda db, **_kwargs: received.update(db=db) or _FakeStore(),
    )
    monkeypatch.setattr(cli, "LLMClient", FakeLLM)
    monkeypatch.setattr(
        cli,
        "run_campaign",
        lambda *_args, **_kwargs: [
            AttackResult(
                attack_type=AttackType.PROMPT_INJECTION,
                payload="assessment payload",
                survived_sanitization=False,
                entered_store=False,
            )
        ],
    )

    result = runner.invoke(
        cli.app,
        ["redteam", "--attacks-per-type", "1"],
        env={
            "MNEMO_OLLAMA_URL": "http://worker.internal:11434",
            "MNEMO_LLM_MODEL": "custom-llm",
        },
    )

    assert result.exit_code == 0, result.output
    assert received == {
        "model": "custom-llm",
        "base_url": "http://worker.internal:11434",
        "db": cli.DEFAULT_REDTEAM_DB,
    }


def test_redteam_allows_intentional_database_override(monkeypatch, tmp_path):
    received: dict[str, object] = {}

    class FakeLLM:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def is_available(self) -> bool:
            return True

        def close(self) -> None:
            pass

    assessment_db = tmp_path / "intentional-assessment.db"
    monkeypatch.setattr(cli, "_get_embedder", lambda *_args: _FakeEmbedder())
    monkeypatch.setattr(
        cli,
        "_get_store",
        lambda db, **_kwargs: received.update(db=db) or _FakeStore(),
    )
    monkeypatch.setattr(cli, "LLMClient", FakeLLM)
    monkeypatch.setattr(
        cli,
        "run_campaign",
        lambda *_args, **_kwargs: [
            AttackResult(
                attack_type=AttackType.PROMPT_INJECTION,
                payload="assessment payload",
                survived_sanitization=False,
                entered_store=False,
            )
        ],
    )

    result = runner.invoke(
        cli.app,
        ["redteam", "--attacks-per-type", "1", "--db", str(assessment_db)],
    )

    assert result.exit_code == 0, result.output
    assert received["db"] == assessment_db


def test_scan_displays_failed_scans_as_errors(monkeypatch):
    monkeypatch.setattr(
        cli,
        "full_scan",
        lambda _path: SecurityReport(
            bandit=ScanFindings(
                tool="bandit",
                available=True,
                error="Exited with status 2: invalid configuration",
                failed=True,
            )
        ),
    )

    result = runner.invoke(cli.app, ["scan"])

    assert result.exit_code == 1, result.output
    assert "error" in result.output
    assert "Exited with status 2: invalid configuration" in result.output
    assert "No issues found" not in result.output
    assert "Scan completed at" in result.output


def test_scan_allows_unavailable_optional_tools(monkeypatch):
    monkeypatch.setattr(
        cli,
        "full_scan",
        lambda _path: SecurityReport(
            bandit=ScanFindings(tool="bandit", available=False, error="Tool not installed"),
            semgrep=ScanFindings(tool="semgrep", available=False, error="Tool not installed"),
            trivy=ScanFindings(tool="trivy", available=False, error="Tool not installed"),
        ),
    )

    result = runner.invoke(cli.app, ["scan"])

    assert result.exit_code == 0, result.output
    assert result.output.count("Tool not installed") == 3


def test_redteam_rejects_zero_attacks_per_type():
    result = runner.invoke(cli.app, ["redteam", "--attacks-per-type", "0"])

    assert result.exit_code != 0
    assert "Invalid value" in result.output
    assert "1" in result.output


def test_redteam_reports_empty_campaign_without_division_by_zero(monkeypatch):
    monkeypatch.setattr(cli, "_get_embedder", lambda *_args: _FakeEmbedder())
    monkeypatch.setattr(cli, "_get_store", lambda *_args, **_kwargs: _FakeStore())

    class FakeLLM:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def is_available(self) -> bool:
            return True

        def close(self) -> None:
            pass

    monkeypatch.setattr(cli, "LLMClient", FakeLLM)
    monkeypatch.setattr(cli, "run_campaign", lambda *_args, **_kwargs: [])

    result = runner.invoke(cli.app, ["redteam", "--attacks-per-type", "1"])

    assert result.exit_code == 1
    assert "produced no results" in result.output


def test_redteam_http_failure_exits_and_closes_resources(monkeypatch):
    closed = {"embedder": 0, "llm": 0, "store": 0}

    class FakeEmbedder(_FakeEmbedder):
        def close(self) -> None:
            closed["embedder"] += 1

    class FakeLLM:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def is_available(self) -> bool:
            return True

        def close(self) -> None:
            closed["llm"] += 1

    class FakeStore(_FakeStore):
        def close(self) -> None:
            closed["store"] += 1

    def fail_campaign(*_args, **_kwargs):
        raise httpx.ReadTimeout("remote worker timed out")

    monkeypatch.setattr(cli, "_get_embedder", lambda *_args: FakeEmbedder())
    monkeypatch.setattr(cli, "_get_store", lambda *_args, **_kwargs: FakeStore())
    monkeypatch.setattr(cli, "LLMClient", FakeLLM)
    monkeypatch.setattr(cli, "run_campaign", fail_campaign)

    result = runner.invoke(cli.app, ["redteam", "--attacks-per-type", "1"])

    assert result.exit_code == 1
    assert "Red-team campaign failed due to an Ollama HTTP error" in result.output
    assert closed == {"embedder": 1, "llm": 1, "store": 1}


def test_embedding_model_availability_handles_http_error(monkeypatch):
    embedder = EmbeddingModel()
    monkeypatch.setattr(
        embedder._client,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(httpx.ReadTimeout("timed out")),
    )

    assert not embedder.is_available()
    embedder.close()


def test_llm_client_availability_handles_http_error(monkeypatch):
    llm = LLMClient()
    monkeypatch.setattr(
        llm._client,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(httpx.RemoteProtocolError("bad response")),
    )

    assert not llm.is_available()
    llm.close()
