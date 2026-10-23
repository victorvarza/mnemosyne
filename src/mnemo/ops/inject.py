from __future__ import annotations

from mnemo.core.types import MemoryResult


def format_memories_block(results: list[MemoryResult]) -> str:
    if not results:
        return ""

    lines = ["## Remembered Context", ""]
    for r in results:
        m = r.memory
        tag = f"[{m.memory_type.value}|{m.trust_level.value}]"
        lines.append(f"- {tag} {m.content}")

    return "\n".join(lines)


def format_profile_block(results: list[MemoryResult], target: str = "") -> str:
    """Render retrieved target-profile entries as a prompt context block.

    This is the ``phi_p`` prompt-construction step: the retrieved profile
    entries are concatenated into a provenance-labelled block that gets
    combined with the scan/test prompt before the model is called.
    """
    if not results:
        return ""

    heading = "## Target Profile Context"
    if target:
        heading += f" — {target}"
    lines = [heading, ""]
    for r in results:
        m = r.memory
        lines.append(f"- [{m.trust_level.value}] {m.content}")

    return "\n".join(lines)


def build_personalized_prompt(
    prompt: str, results: list[MemoryResult], target: str = ""
) -> str:
    """Combine a user scan/test prompt with retrieved profile entries.

    Produces the final in-prompt-augmented (IPA) input sent to the language
    model: the target-profile context block followed by the task prompt.
    """
    block = format_profile_block(results, target=target)
    if not block:
        return prompt
    return f"{block}\n\nTask: {prompt}"

