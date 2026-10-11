import io
import json
from pathlib import Path

from typer.testing import CliRunner

from mnemo import cli
from mnemo.integrations import claudecode

runner = CliRunner()

PLUGIN_ROOT = Path(__file__).parent.parent / "claudecode-plugin"


def _recording_runner(outputs):
    """Return a runner that records calls and replays canned outputs by command."""
    calls = []

    def run(args):
        args = list(args)
        calls.append(args)
        value = outputs.get(args[0], "")
        if isinstance(value, Exception):
            raise value
        return value

    return run, calls


def test_extract_important_info_matches_patterns():
    assert claudecode.extract_important_info("the user prefers pytest") == "the user prefers pytest"
    assert claudecode.extract_important_info("Remember this for later please") is not None
    assert claudecode.extract_important_info("tell me a joke") is None
    assert claudecode.extract_important_info("") is None


def test_process_prompt_stores_important_info_and_injects_context():
    run, calls = _recording_runner(
        {
            "add": "Stored memory abc123...\n",
            "context": "- [semantic|user_stated] I use pytest\n",
        }
    )

    prompt = "Remember this for later: user prefers pytest"
    result = claudecode.process_prompt(prompt, run)

    assert calls == [
        ["add", "--", f"User mentioned: {prompt}"],
        ["context", "--top-k", "5", "--", prompt],
    ]
    expected_block = "## Relevant Context from Memory\n- [semantic|user_stated] I use pytest"
    assert result == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": expected_block,
        }
    }


def test_process_prompt_skips_store_when_nothing_important():
    run, calls = _recording_runner({"context": "- [semantic|user_stated] a\n"})

    result = claudecode.process_prompt("which editor do I use?", run)

    assert calls == [["context", "--top-k", "5", "--", "which editor do I use?"]]
    assert result["hookSpecificOutput"]["additionalContext"].startswith(
        "## Relevant Context from Memory"
    )


def test_process_prompt_returns_none_when_no_relevant_memories():
    run, calls = _recording_runner({"context": "  \n"})

    assert claudecode.process_prompt("tell me a joke", run) is None
    assert calls == [["context", "--top-k", "5", "--", "tell me a joke"]]


def test_process_prompt_is_noop_for_empty_prompt():
    run, calls = _recording_runner({})

    assert claudecode.process_prompt("   ", run) is None
    assert calls == []


def test_process_prompt_degrades_gracefully_when_context_fails():
    run, calls = _recording_runner({"context": RuntimeError("Ollama not reachable")})

    assert claudecode.process_prompt("tell me a joke", run) is None
    assert calls == [["context", "--top-k", "5", "--", "tell me a joke"]]


def test_process_prompt_still_injects_when_store_fails():
    run, calls = _recording_runner(
        {
            "add": RuntimeError("Ollama not reachable"),
            "context": "- [semantic|user_stated] I use pytest\n",
        }
    )

    result = claudecode.process_prompt("user prefers pytest", run)

    assert calls[0][0] == "add"
    assert calls[1][0] == "context"
    assert "I use pytest" in result["hookSpecificOutput"]["additionalContext"]


def test_run_hook_reads_stdin_and_writes_additional_context():
    run, _ = _recording_runner({"context": "- [semantic|user_stated] I use pytest\n"})
    stdin = io.StringIO(json.dumps({"prompt": "which tools do I use?", "cwd": "/repo"}))
    stdout = io.StringIO()

    code = claudecode.run_hook(stdin=stdin, stdout=stdout, runner=run)

    assert code == 0
    payload = json.loads(stdout.getvalue())
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "I use pytest" in payload["hookSpecificOutput"]["additionalContext"]


def test_run_hook_emits_nothing_on_invalid_json():
    run, calls = _recording_runner({})
    stdout = io.StringIO()

    code = claudecode.run_hook(stdin=io.StringIO("not json"), stdout=stdout, runner=run)

    assert code == 0
    assert stdout.getvalue() == ""
    assert calls == []


def test_run_hook_emits_nothing_when_no_memories():
    run, _ = _recording_runner({"context": ""})
    stdout = io.StringIO()

    code = claudecode.run_hook(
        stdin=io.StringIO(json.dumps({"prompt": "hi"})), stdout=stdout, runner=run
    )

    assert code == 0
    assert stdout.getvalue() == ""


def test_cli_command_wires_run_hook(monkeypatch):
    calls = []

    def fake_runner(args):
        calls.append(list(args))
        return "- [semantic|user_stated] I use pytest\n" if args[0] == "context" else ""

    monkeypatch.setattr(claudecode, "_cli_runner", fake_runner)

    result = runner.invoke(
        cli.app, ["claudecode-hook"], input=json.dumps({"prompt": "what do I use?"})
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "I use pytest" in payload["hookSpecificOutput"]["additionalContext"]
    assert calls == [["context", "--top-k", "5", "--", "what do I use?"]]


def test_plugin_manifest_is_valid():
    manifest = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "mnemosyne"
    assert manifest["description"]
    assert manifest["version"]


def test_plugin_hooks_reference_an_executable_entrypoint():
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
    entries = hooks["hooks"]["UserPromptSubmit"]
    command = entries[0]["hooks"][0]["command"]
    assert command.endswith("hooks/mnemo-hook.sh")

    script = PLUGIN_ROOT / "hooks" / "mnemo-hook.sh"
    assert script.exists()
    assert script.stat().st_mode & 0o111, "hook script must be executable"
    assert "claudecode-hook" in script.read_text()


def test_plugin_ships_slash_commands():
    commands = {path.stem for path in (PLUGIN_ROOT / "commands").glob("*.md")}
    assert {"remember", "recall", "scan", "pentest"} <= commands
