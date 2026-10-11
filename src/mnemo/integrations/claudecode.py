"""Claude Code integration for Mnemosyne.

Implements the ``UserPromptSubmit`` hook that powers the Claude Code plugin
under ``claudecode-plugin/``. On every user prompt it pattern-matches and stores
important information, then retrieves the relevant memories and returns them to
Claude Code as ``additionalContext``.

This mirrors the OpenCode plugin's prompt/context hooks, and shells out to the
same ``mnemo`` CLI commands (``add`` and ``context``) so retrieval, usefulness
filtering, and auto-capture behave identically across both integrations.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import IO

HOOK_EVENT = "UserPromptSubmit"

# Same capture patterns as the OpenCode plugin's extractImportantInfo().
IMPORTANT_PATTERNS = [
    re.compile(r"user prefers", re.IGNORECASE),
    re.compile(r"important.*note", re.IGNORECASE),
    re.compile(r"remember.*for.*later", re.IGNORECASE),
    re.compile(r"configuration.*setting", re.IGNORECASE),
    re.compile(r"project.*convention", re.IGNORECASE),
    re.compile(r"security.*consideration", re.IGNORECASE),
    re.compile(r"performance.*optimization", re.IGNORECASE),
]

# A runner takes `mnemo` CLI arguments and returns the command's stdout.
Runner = Callable[[Sequence[str]], str]


def extract_important_info(text: str) -> str | None:
    """Return ``text`` when it looks worth remembering, else ``None``."""
    for pattern in IMPORTANT_PATTERNS:
        if pattern.search(text):
            return text
    return None


def _cli_runner(args: Sequence[str]) -> str:
    """Run the `mnemo` CLI, returning stdout and raising on a non-zero exit.

    Honors ``MNEMO_BIN`` (a `mnemo` executable, e.g. ``<repo>/.venv/bin/mnemo``)
    and otherwise falls back to ``python3 -m mnemo.cli`` under the current
    interpreter, matching the OpenCode plugins.
    """
    bin_ = os.environ.get("MNEMO_BIN")
    base = [bin_] if bin_ else [sys.executable, "-m", "mnemo.cli"]
    result = subprocess.run([*base, *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"mnemo exited with code {result.returncode}"
        )
        raise RuntimeError(message)
    return result.stdout


def build_context(prompt: str, runner: Runner, *, top_k: int = 5) -> str:
    """Return the formatted memory block for ``prompt`` (``""`` when empty).

    ``--`` stops a prompt that starts with ``-`` from being parsed as a flag.
    """
    out = runner(["context", "--top-k", str(top_k), "--", prompt]).strip()
    return f"## Relevant Context from Memory\n{out}" if out else ""


def process_prompt(prompt: str, runner: Runner, *, top_k: int = 5) -> dict | None:
    """Store important info and build the hook response for a user prompt.

    Returns a ``UserPromptSubmit`` hook payload with the memory block as
    ``additionalContext``, or ``None`` when there is nothing to inject. Both
    the store and retrieve steps are best-effort: a failing `mnemo` call (for
    example, an unreachable Ollama worker) must never block the turn.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return None

    important = extract_important_info(prompt)
    if important:
        try:
            runner(["add", "--", f"User mentioned: {important}"])
        except Exception:
            pass  # auto-store is best-effort; never block the turn

    try:
        block = build_context(prompt, runner, top_k=top_k)
    except Exception:
        block = ""
    if not block:
        return None

    return {
        "hookSpecificOutput": {
            "hookEventName": HOOK_EVENT,
            "additionalContext": block,
        }
    }


def run_hook(
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
    runner: Runner | None = None,
) -> int:
    """Read a Claude Code hook payload from stdin and emit the response.

    Claude Code sends ``{"prompt": ..., ...}`` on stdin; this prints the
    ``additionalContext`` JSON on stdout when relevant memories exist. Always
    returns ``0`` so a hook failure is non-blocking.
    """
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    runner = runner or _cli_runner

    raw = stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}

    result = process_prompt(str(payload.get("prompt", "")), runner)
    if result is not None:
        json.dump(result, stdout)
        stdout.write("\n")
    return 0
